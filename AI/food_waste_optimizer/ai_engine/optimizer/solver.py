"""PART 5 — แบบจำลอง MILP: แบ่งทุก lot พร้อมกัน (joint) ให้กำไรสุทธิสูงสุด

กำไรต่อหน่วย "รวมต้นทุนสินค้า (COGS = lot.unit_cost) ไว้ทุกเส้นทาง" ทุกหน่วยถูกนับครั้งเดียว จึงเทียบกันได้ตรง ๆ
และตรงกับตัวอย่างใน Swagger (DISCARD = −จำนวน × unit_cost)

ตัวแปร (ต่อ lot L)
  t[L,d]  binary  เลือกระดับส่วนลด d (1 lot มีราคาเดียว -> เลือกได้ 1 ระดับ; d=0 = ราคาปกติ)
  s[L,d]  int     จำนวนที่ขายที่ระดับ d   s ≤ cap[L,d]·t[L,d]   กำไร/หน่วย = ราคา_d − unit_cost
  x[L,P]  int     จำนวนส่ง partner P      กำไร/หน่วย = (buyback − handling)·kg − unit_cost
  z[P]    binary  เปิดเที่ยวรับของ partner P  ต้นทุน = fixed (+travel ถ้าไม่ใช่ DONATION) ต่อเที่ยว
                  Σkg ≤ capacity·z   และ Σkg ≥ min_kg_per_pickup·z
  n[r,d]  int     จำนวน batch ของสูตร r วัน d  กำไร = yield×ราคาขาย − utility_cost
  k[L,r,d]  int   หน่วยของ lot ที่เป็นวัตถุดิบหลัก (primary)  ต้นทุน = Cost_Primary = unit_cost
  k2[L,r,d] int   หน่วยของ lot ที่เป็นวัตถุดิบรอง (secondary)  เครดิต = base_cost − unit_cost
  sf[r,p,d] ≥0    ส่วนวัตถุดิบรองที่ต้องมาจากสต็อกที่ไม่เสี่ยง (เทียบ ingredient_stock)
  res[L]  int     หน่วยที่ไม่มีทางไป (โดนปรับหนัก)

ข้อจำกัดหลัก: สมดุลจำนวน (Σ ทุกทาง = current_quantity), ชั่วโมงครัวต่อแผนกต่อวัน,
  demand เมนู, วัตถุดิบหลักครอบคลุม ≥ need×batch, วัตถุดิบรองรวมทุกงาน ≤ สต็อก (suffix ตามวันหมดอายุ)
"""
from __future__ import annotations

import math
import time as _time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix


class SolverError(RuntimeError):
    pass


class _Builder:
    def __init__(self):
        self.lb, self.ub, self.integer, self.profit, self.rows = [], [], [], [], []

    def var(self, lb=0.0, ub=np.inf, integer=False, profit=0.0) -> int:
        self.lb.append(lb); self.ub.append(ub); self.integer.append(1 if integer else 0); self.profit.append(profit)
        return len(self.profit) - 1

    def row(self, coefs: dict, lo=-np.inf, hi=np.inf) -> None:
        if coefs:
            self.rows.append((coefs, lo, hi))


@dataclass
class Switches:
    """เปิด/ปิดเส้นทาง ใช้สร้าง baseline เปรียบเทียบ (ค่าเริ่มต้น = เปิดทั้งหมด)"""
    markdown_levels: Optional[frozenset] = None
    kitchen: bool = True
    partner_types: Optional[frozenset] = None


@dataclass
class Solution:
    x: np.ndarray
    var: dict
    objective: float
    status: str
    gap: Optional[float]
    time_ms: int
    penalty: float

    def amount(self, key) -> float:
        return float(self.x[self.var[key]]) if key in self.var else 0.0

    def count(self, key) -> int:
        return int(round(self.amount(key)))

    @property
    def unresolved_units(self) -> int:
        return sum(self.count(k) for k in self.var if k[0] == "res")

    @property
    def net_profit(self) -> float:
        """กำไรสุทธิ (รวม COGS) ไม่รวมค่าปรับ unresolved"""
        return self.objective + self.penalty * self.unresolved_units


def solve(ctx, sw: Optional[Switches] = None, time_limit: Optional[float] = None,
          mip_gap: Optional[float] = None) -> Solution:
    cfg = ctx.cfg
    sw = sw or Switches()
    t0 = _time.perf_counter()
    b, V = _Builder(), {}
    M = cfg.unresolved_penalty_per_unit
    lot_terms: dict = {lid: {} for lid in ctx.lots}

    # ---- 5.1 ขายหน้าร้าน (ราคาปกติ / markdown) ----
    for lid, lc in ctx.lots.items():
        c = lc.lot.unit_cost
        tiers = [t for t in lc.tiers if sw.markdown_levels is None or t["discount_pct"] in sw.markdown_levels]
        for t in tiers:
            d = t["discount_pct"]
            ti = V[("t", lid, d)] = b.var(0, 1, True)
            si = V[("s", lid, d)] = b.var(0, t["cap"], True, t["price"] - c)
            b.row({si: 1.0, ti: -float(t["cap"])}, hi=0.0)
            lot_terms[lid][si] = 1.0
        if tiers:
            b.row({V[("t", lid, t["discount_pct"])]: 1.0 for t in tiers}, 1.0, 1.0)

    # ---- 5.2 partner (donation / animal feed / composting / anaerobic / landfill) ----
    for pid, pc in ctx.partners.items():
        if sw.partner_types is not None and pc.partner.partner_type not in sw.partner_types:
            continue
        loads = {}
        for lid, lc in ctx.lots.items():
            if pid not in lc.partner_ok:
                continue
            w = lc.weight_kg
            ub = min(lc.lot.quantity, int(math.floor(pc.cap_kg / w + 1e-9)))
            if ub <= 0:
                continue
            profit = (pc.partner.buyback - pc.handling) * w - lc.lot.unit_cost
            xi = V[("x", lid, pid)] = b.var(0, ub, True, profit)
            loads[xi] = w
            lot_terms[lid][xi] = 1.0
        if not loads:
            continue
        zi = V[("z", pid)] = b.var(0, 1, True, -(0.0 if pc.sunk else pc.trip_cost))
        b.row({**loads, zi: -pc.cap_kg}, hi=0.0)
        if pc.partner.min_kg > 0:
            b.row({**loads, zi: -pc.partner.min_kg}, lo=0.0)

    # ---- 5.3 ไม่มีทางไป (ค่าปรับ) ----
    for lid, lc in ctx.lots.items():
        ri = V[("res", lid)] = b.var(0, lc.lot.quantity, True, -(lc.lot.unit_cost + M))
        lot_terms[lid][ri] = 1.0

    # ---- 5.4 ครัว (kitchen_repurposing) ----
    if sw.kitchen:
        hour_rows: dict = defaultdict(dict)
        sf_by: dict = defaultdict(lambda: defaultdict(list))
        for rid, rc in ctx.recipes.items():
            if not rc.eligible:
                continue
            r = rc.recipe
            total: dict = {}
            for day in rc.days:
                cap_n = min(int(math.floor(rc.demand_units / r.output_qty + 1e-9)),
                            int(math.floor(ctx.hours[(r.department_id, day)].hours / rc.hours_per_batch + 1e-9)))
                if cap_n < 1:
                    continue
                ni = V[("n", rid, day)] = b.var(0, cap_n, True, rc.batch_profit)
                hour_rows[(r.department_id, day)][ni] = rc.hours_per_batch
                total[ni] = r.output_qty
                for ing in rc.primary:                                   # วัตถุดิบหลัก: ต้องมาจาก lot เสี่ยงทั้งหมด
                    content = ctx.inputs.products[ing.product_id].content
                    row = {ni: -ing.need}
                    for lid in rc.suppliers.get((ing.product_id, day), []):
                        lot = ctx.lots[lid].lot
                        ki = V[("k", lid, rid, day)] = b.var(0, lot.quantity, True, -lot.unit_cost)
                        row[ki] = content
                        lot_terms[lid][ki] = 1.0
                    b.row(row, lo=0.0)                                   # ครอบคลุมความต้องการ
                    b.row(row, hi=content - 1.0)                         # เกินได้ไม่ถึง 1 หน่วยนับ
                for ing in rc.secondary:                                 # วัตถุดิบรอง: lot เสี่ยง + สต็อกไม่เสี่ยง
                    prod = ctx.inputs.products[ing.product_id]
                    base = {ni: -ing.need}
                    for lid in rc.sec_suppliers.get((ing.product_id, day), []):
                        lot = ctx.lots[lid].lot
                        ki = V[("k2", lid, rid, day)] = b.var(0, lot.quantity, True, prod.base_cost - lot.unit_cost)
                        base[ki] = prod.content
                        lot_terms[lid][ki] = 1.0
                    sfi = V[("sf", rid, ing.product_id, day)] = b.var(0, np.inf, False, 0.0)
                    b.row(base, hi=0.0)
                    b.row({**base, sfi: 1.0}, lo=0.0)
                    sf_by[ing.product_id][day].append(sfi)
            b.row(total, hi=rc.demand_units)
        for key, row in hour_rows.items():
            b.row(row, hi=ctx.hours[key].hours)
        # รวมความต้องการวัตถุดิบรองของ "ทุกงาน" เทียบสต็อก: งานวันหลัง ๆ ใช้ได้เฉพาะ lot ที่ยังไม่หมดอายุ
        for pid, per_day in sf_by.items():
            days = sorted(per_day)
            for d in days:
                b.row({i: 1.0 for d2 in days if d2 >= d for i in per_day[d2]}, hi=ctx.nr_stock(pid, d))

    # ---- 5.5 สมดุลจำนวนของทุก lot: Σ ทุกทาง = current_quantity ----
    for lid, terms in lot_terms.items():
        q = float(ctx.lots[lid].lot.quantity)
        b.row(terms, q, q)

    return _run(b, V, M, cfg, t0, time_limit, mip_gap)


def _run(b: _Builder, V: dict, M: float, cfg, t0: float, time_limit, mip_gap) -> Solution:
    n = len(b.profit)
    if n == 0:
        return Solution(np.zeros(0), V, 0.0, "optimal", 0.0, 0, M)
    ri, ci, data, lo, hi = [], [], [], [], []
    for i, (coefs, l, h) in enumerate(b.rows):
        for j, v in coefs.items():
            ri.append(i); ci.append(j); data.append(v)
        lo.append(l); hi.append(h)
    constraints = None
    if b.rows:
        constraints = LinearConstraint(coo_matrix((data, (ri, ci)), shape=(len(b.rows), n)).tocsr(), lo, hi)
    res = milp(c=-np.array(b.profit), constraints=constraints, integrality=np.array(b.integer),
               bounds=Bounds(b.lb, b.ub),
               options={"time_limit": time_limit or cfg.solver_time_limit_s,
                        "mip_rel_gap": cfg.solver_mip_gap if mip_gap is None else mip_gap})
    if res.x is None:
        raise SolverError(f"solver failed: {res.message}")
    gap = getattr(res, "mip_gap", None)
    return Solution(res.x, V, float(-res.fun), "optimal" if res.status == 0 else "feasible_not_optimal",
                    None if gap is None or not np.isfinite(gap) else float(gap),
                    int((_time.perf_counter() - t0) * 1000), M)
