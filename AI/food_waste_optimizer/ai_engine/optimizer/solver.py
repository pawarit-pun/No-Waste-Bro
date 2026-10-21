"""PART 5 — MILP (HiGHS ผ่าน scipy): แบ่งทุก lot พร้อมกันให้กำไรสุทธิสูงสุด (ขาดทุนน้อยสุด)

ทุกหน่วยของ lot เสี่ยงถูกนับต้นทุนสินค้า (unit_cost) ครั้งเดียวในทางที่มันไป จึงเทียบทุกทางได้ตรงกัน
(DISCARD เปล่า = -จำนวน x unit_cost ตามตัวอย่าง Swagger)

ตัวแปร                                                     กำไรต่อหน่วยในเป้าหมาย
  t[L,d] bin   เลือกราคา d ของ lot (1 lot 1 ราคา, Σt <= 1)    -lost_sales_cost (ยอดที่ล็อตอื่นเสียไป)
  shelf[L] int หน่วยที่วางบนชั้น = Σ_d Σ_seg s                    -unit_cost
  s[L,d,i]     หน่วยบนชั้นในช่วง i ของ demand (<= ความกว้าง·t)     p_i·price_d  (p_i = โอกาสขายออก จาก P10/P50/P90)
               ช่วงขายง่ายมีกำไรต่อหน่วยมากกว่า (รายได้ concave) solver จึงเติมจากช่วงแรกเองโดยไม่ต้องใช้ binary
  y[L,P]       หน่วยที่คาดว่าขายไม่หมด ส่ง P รอบหลังหมดเวลาขาย    (buyback - handling)·kg
               Σ_P y (+ rese) = Σ (1 - p_i)·s
  rese[L]      ของที่ขายไม่หมดแต่ไม่มี partner end-of-life รับ (ทิ้งเองในร้าน)  -factor·unit_cost (เป้าหมายเท่านั้น)
  x[L,P] int   ดึงออกจากชั้นตอนนี้ ส่ง partner P                 (buyback - handling)·kg - unit_cost
  z[P,วัน] bin เที่ยวรับของ (kg ของ x + y <= max·z, >= min·z)      -(fixed + travel) [DONATION: -fixed; scheduled: 0]
  n[j]   int   batch ของงานครัว j                               -utility_cost  (ค่าไฟ+น้ำ+วัตถุดิบรอง)
  k[j]   int   หน่วยของ lot หลักที่งาน j ใช้ = ceil(need·n/content) -unit_cost      (= Cost_Primary)
  sold[r,d,i]  เมนูที่วางขายในช่วง i ของ demand เมนู Σ_i sold <= output·Σn   +p_i·regular_price ของเมนู
               Σ_{d'>=d} sold[i] <= ความกว้างช่วง i ณ วัน d (ความต้องการก้อนเดียวกันทั้ง window)
  c[f,ℓ,d,ρ]   หน่วยของสินค้า f ที่ DB ตัดจาก lot ℓ แบบ FEFO วัน d (ρ = วัตถุดิบหลัก/รอง)
               lot ไม่เสี่ยง: หลัก -base_cost, รอง 0 (อยู่ใน utility_cost แล้ว)
  u[ℓ]   int   หน่วยของ lot เสี่ยงที่ถูก FEFO ตัด = ceil(Σc)          -unit_cost  (+base_cost·c ส่วนวัตถุดิบรอง)
  g[f,ℓ,d] bin FEFO: lot ถัดไปถูกใช้ได้ก็ต่อเมื่อ lot ก่อนหน้า (หมดอายุก่อน) หมดแล้ว
  res[L] int   ไม่มีทางไป                                       -(unit_cost + penalty)
ข้อจำกัด: Σ ทุกทาง = current_quantity ของทุก lot, ชั่วโมงครัวต่อแผนกต่อวัน, ความจุ/ขั้นต่ำ partner, สต็อกวัตถุดิบ
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

from ai_engine.optimizer.context import trip_cost, trip_min_kg


TIE_BREAK = 1e-3                         # บาท/หน่วย: ไม่กระทบการตัดสินใจจริง ใช้แยกทางที่เท่ากันเท่านั้น
# ceil(x) เขียนเป็น x <= k <= x + 1 - CEIL_MARGIN: margin ต้องใหญ่กว่า feasibility tolerance ของ HiGHS (1e-6)
# ไม่งั้น solver ปัด k ขึ้นเกิน 1 ได้เมื่อ x เป็นจำนวนเต็มพอดี (เช่น วัตถุดิบ 8.0 หน่วย -> นับเป็น 9) แล้ว H5/H6 ไม่ผ่าน
CEIL_MARGIN = 1e-3


class SolverError(RuntimeError):
    pass


class _Builder:
    def __init__(self):
        self.lb, self.ub, self.integer, self.profit, self.rows = [], [], [], [], []

    def var(self, lb=0.0, ub=np.inf, integer=False, profit=0.0) -> int:
        self.lb.append(lb); self.ub.append(ub); self.integer.append(1 if integer else 0); self.profit.append(profit)
        return len(self.profit) - 1

    def row(self, coefs: dict, lo=-np.inf, hi=np.inf) -> None:
        coefs = {k: v for k, v in coefs.items() if v != 0}
        if coefs:
            self.rows.append((coefs, lo, hi))


@dataclass
class Switches:
    """เปิด/ปิดเส้นทาง ใช้สร้าง baseline เปรียบเทียบ"""
    discounts: Optional[frozenset] = None
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
    eol_penalty_thb: float = 0.0       # ค่าปรับของ rese ที่อยู่ในเป้าหมาย (ไม่ใช่เงินจริง)

    tie_break_thb: float = 0.0

    def amount(self, key) -> float:
        return float(self.x[self.var[key]]) if key in self.var else 0.0

    def count(self, key) -> int:
        return int(round(self.amount(key)))

    @property
    def unresolved_units(self) -> int:
        return sum(self.count(k) for k in self.var if k[0] == "res")

    @property
    def unresolved_eol_units(self) -> float:
        return sum(self.amount(k) for k in self.var if k[0] == "rese")

    @property
    def net_profit(self) -> float:
        return self.objective + self.penalty * self.unresolved_units + self.eol_penalty_thb + self.tie_break_thb


def solve(ctx, sw: Optional[Switches] = None) -> Solution:
    cfg, inp = ctx.cfg, ctx.inputs
    sw = sw or Switches()
    t0 = _time.perf_counter()
    b, V = _Builder(), {}
    M = cfg.unresolved_penalty_per_unit
    balance = {lid: {} for lid in ctx.lots}

    types_ok = lambda pid: sw.partner_types is None or ctx.partners[pid].partner.partner_type in sw.partner_types
    trips = defaultdict(dict)                                # (partner, วัน) -> {var: kg ต่อหน่วย}
    eol_penalty = {}                                         # var rese -> ค่าปรับต่อหน่วย (ไม่ใช่เงินจริง)

    # ---- 5.1 วางขายหน้าร้าน (ราคาปัจจุบัน / ลดราคา) + ของที่ขายไม่หมด (end-of-life)
    for lid, lc in ctx.lots.items():
        c, w = lc.lot.unit_cost, lc.weight_kg or 0.0
        tiers = [t for t in lc.tiers if sw.discounts is None or t["discount_pct"] in sw.discounts]
        if not tiers:
            continue
        qty = float(lc.lot.quantity)
        shelf = V[("shelf", lid)] = b.var(0, lc.lot.quantity, True, -c)
        balance[lid][shelf] = 1.0
        on_shelf, leftover = {shelf: -1.0}, {}
        for t in tiers:
            d = t["discount_pct"]
            ti = V[("t", lid, d)] = b.var(0, 1, True, -t["lost_sales_cost"])
            for i, (width, p) in enumerate(t["segments"] + [(qty, 0.0)]):     # ช่วงสุดท้าย = เกินหาง ขายไม่ได้
                si = V[("s", lid, d, i)] = b.var(0, width, False, p * t["price"])
                b.row({si: 1.0, ti: -width}, hi=0.0)
                on_shelf[si] = 1.0
                leftover[si] = -(1.0 - p)
        b.row({V[("t", lid, t["discount_pct"])]: 1.0 for t in tiers}, hi=1.0)
        b.row(on_shelf, 0.0, 0.0)                                           # shelf = Σ s
        eol = [pid for pid in lc.eol if types_ok(pid)]
        for pid in eol:
            pc = ctx.partners[pid]
            yi = V[("y", lid, pid)] = b.var(0, qty, False, (pc.partner.buyback - pc.handling) * w)
            leftover[yi] = 1.0
            trips[(pid, lc.eol[pid].date())][yi] = w
        if not eol:
            pen = cfg.eol_no_route_penalty_factor * c
            ri = V[("rese", lid)] = b.var(0, qty, False, -pen)
            eol_penalty[ri] = pen
            leftover[ri] = 1.0
        b.row(leftover, 0.0, 0.0)                                           # Σ y = Σ (1 - p)·s

    # ---- 5.2 partner: ดึงออกตอนนี้ (x) + เที่ยวรถต่อ (partner, วัน)
    for lid, lc in ctx.lots.items():
        for pid in lc.partner_ok:
            if not types_ok(pid):
                continue
            pc, w = ctx.partners[pid], lc.weight_kg
            ub = min(lc.lot.quantity, int(math.floor(pc.cap_kg / w + 1e-9)))
            if ub <= 0:
                continue
            # tie-break: ถ้ายังวางขายได้ ให้เก็บไว้บนชั้นก่อนเมื่อต้นทุนเท่ากัน (ยังมีโอกาสขายเกินที่คาด)
            tie = TIE_BREAK if lc.tiers else 0.0
            xi = V[("x", lid, pid)] = b.var(0, ub, True, (pc.partner.buyback - pc.handling) * w - lc.lot.unit_cost - tie)
            balance[lid][xi] = 1.0
            trips[(pid, pc.pickup.date())][xi] = w
    for (pid, day), loads in trips.items():
        pc = ctx.partners[pid]
        zi = V[("z", pid, day)] = b.var(0, 1, True, -trip_cost(ctx, pid, day))
        b.row({**loads, zi: -pc.cap_kg}, hi=0.0)
        min_kg = trip_min_kg(ctx, pid, day)
        if min_kg > 0:
            b.row({**loads, zi: -min_kg}, lo=0.0)

    # ---- 5.3 ไม่มีทางไป
    for lid, lc in ctx.lots.items():
        ri = V[("res", lid)] = b.var(0, lc.lot.quantity, True, -(lc.lot.unit_cost + M))
        balance[lid][ri] = 1.0

    # ---- 5.4 ครัว
    if sw.kitchen and ctx.jobs:
        _kitchen(ctx, b, V, balance)

    # ---- 5.5 สมดุลจำนวน: Σ ทุกทาง = current_quantity
    for lid, terms in balance.items():
        q = float(ctx.lots[lid].lot.quantity)
        b.row(terms, q, q)
    sol = _run(b, V, M, cfg, t0, eol_penalty)
    sol.tie_break_thb = TIE_BREAK * sum(sol.amount(k) for k in V
                                        if k[0] == "x" and ctx.lots[k[1]].tiers)
    return sol


def _kitchen(ctx, b, V, balance) -> None:
    inp = ctx.inputs
    hour_rows, out_rows = defaultdict(dict), defaultdict(dict)
    anchor_units = defaultdict(dict)                         # lot_id -> {k_index: 1}
    need = defaultdict(lambda: defaultdict(dict))            # (product, day) -> role -> {n_index: g/ml per batch}
    for j in ctx.jobs:
        r = inp.recipes[j.recipe_id]
        lot = ctx.lots[j.anchor_lot_id].lot
        ni = V[("n", j.job_id)] = b.var(0, j.nmax, True, -r.utility_cost)
        ki = V[("k", j.job_id)] = b.var(0, lot.quantity, True, -lot.unit_cost)
        per_batch = j.anchor_need / j.anchor_content                                          # หน่วยของ lot ต่อ batch
        b.row({ki: 1.0, ni: -per_batch}, lo=0.0)                                              # ครอบคลุม
        b.row({ki: 1.0, ni: -per_batch}, hi=1.0 - CEIL_MARGIN)                                # k = ceil(...)
        balance[j.anchor_lot_id][ki] = 1.0
        anchor_units[j.anchor_lot_id][ki] = 1.0
        hour_rows[(r.department_id, j.day)][ni] = j.hours_per_batch
        out_rows[(j.recipe_id, j.day)][ni] = r.output_qty
        for pid, q, primary in j.others:                                                      # หน่วยของสินค้าต่อ batch
            need[(pid, j.day)]["P" if primary else "S"][ni] = q / inp.products[pid].content
    for key, row in hour_rows.items():
        b.row(row, hi=ctx.hours[key].hours)

    # เมนูที่วางขาย: Σ_i sold <= ผลิตได้, ช่วง i ขายออกด้วยโอกาส p_i, ความต้องการก้อนเดียวกันตลอด window
    sold = defaultdict(dict)
    for (rid, day), row in out_rows.items():
        price = inp.products[inp.recipes[rid].output_product_id].regular_price
        rday = ctx.recipe_days[(rid, day)]
        segs = {}
        for i, (width, p) in enumerate(rday.segments):
            segs[i] = V[("sold", rid, day, i)] = b.var(0, width, False, p * price)
        b.row({**{si: 1.0 for si in segs.values()}, **{k: -v for k, v in row.items()}}, hi=0.0)
        sold[rid][day] = segs
    for rid, per_day in sold.items():
        days = sorted(per_day)
        for d in days:
            for i, (width, _) in enumerate(ctx.recipe_days[(rid, d)].segments):
                later = {per_day[d2][i]: 1.0 for d2 in days if d2 >= d and i in per_day[d2]}
                b.row(later, hi=width)

    # FEFO ของวัตถุดิบที่ DB ตัดเอง (คิดเป็น "หน่วยของสินค้า" ไม่ใช่ g/ml เพื่อให้ตัวเลขในโมเดลไม่ต่างกันมากเกินไป)
    for pid, lots in ctx.fefo.items():
        prod = inp.products[pid]
        days = ctx.fefo_days[pid]
        cum = defaultdict(dict)                              # lot_id -> {c_index: 1} สะสมทุกวัน
        for d in days:
            valid = [fl for fl in lots if fl.expiration_date >= d]
            roles = need.get((pid, d), {})
            day_c = {}
            for fl in valid:
                for rho in roles:
                    ci = V[("c", pid, fl.lot_id, d, rho)] = b.var(0, fl.quantity, False, _c_profit(fl, rho, prod))
                    day_c.setdefault(fl.lot_id, {})[ci] = 1.0
                    cum[fl.lot_id][ci] = 1.0
            for rho, row in roles.items():                   # Σ_ℓ c = ความต้องการรวมทุกงานของวันนั้น
                b.row({**{V[("c", pid, fl.lot_id, d, rho)]: 1.0 for fl in valid}, **{k: -v for k, v in row.items()}},
                      0.0, 0.0)
            for a, nxt in zip(valid, valid[1:]):              # FEFO: ใช้ lot ถัดไปได้เมื่อ lot ก่อนหน้าหมดแล้ว
                gi = V[("g", pid, a.lot_id, d)] = b.var(0, 1, True, 0.0)
                b.row({**day_c.get(nxt.lot_id, {}), gi: -float(nxt.quantity)}, hi=0.0)
                # สะสมถึงวันนี้: c + หน่วยที่งานหลักใช้ >= qty·g   (g = 1 -> lot a หมดแล้ว)
                coefs = dict(cum[a.lot_id])
                for ki in anchor_units.get(a.lot_id, {}):
                    coefs[ki] = coefs.get(ki, 0.0) + 1.0
                coefs[gi] = -float(a.quantity)
                b.row(coefs, lo=0.0)
        for fl in lots:                                      # รวมทุกวัน + หน่วยที่งานหลักใช้ <= qty
            if fl.lot_id not in cum:
                continue
            coefs = dict(cum[fl.lot_id])
            for ki in anchor_units.get(fl.lot_id, {}):
                coefs[ki] = coefs.get(ki, 0.0) + 1.0
            b.row(coefs, hi=float(fl.quantity))
            if fl.at_risk:                                   # หน่วยที่ถูกตัด = ceil(Σc) เข้าสมดุลจำนวนของ lot
                lot = ctx.lots[fl.lot_id].lot
                ui = V[("u", fl.lot_id)] = b.var(0, lot.quantity, True, -lot.unit_cost)
                b.row({ui: 1.0, **{k: -1.0 for k in cum[fl.lot_id]}}, lo=0.0)
                b.row({ui: 1.0, **{k: -1.0 for k in cum[fl.lot_id]}}, hi=1.0 - CEIL_MARGIN)
                balance[fl.lot_id][ui] = 1.0


def _c_profit(fl, rho: str, prod) -> float:
    """กำไรต่อ 1 หน่วยของวัตถุดิบที่ DB ตัดแบบ FEFO"""
    if fl.at_risk:      # ต้นทุนสินค้าคิดที่ u แล้ว; วัตถุดิบรองที่มาจาก lot เสี่ยงช่วยประหยัดค่าวัตถุดิบรองใน utility_cost
        return prod.base_cost if rho == "S" else 0.0
    return -prod.base_cost if rho == "P" else 0.0     # วัตถุดิบหลักจากสต็อกปกติ = Cost_Primary


def _run(b: _Builder, V: dict, M: float, cfg, t0: float, eol_penalty: Optional[dict] = None) -> Solution:
    n = len(b.profit)
    if n == 0:
        return Solution(np.zeros(0), V, 0.0, "optimal", 0.0, 0, M)
    eol_penalty = eol_penalty or {}
    ri, ci, data, lo, hi = [], [], [], [], []
    for i, (coefs, l, h) in enumerate(b.rows):
        for j, v in coefs.items():
            ri.append(i); ci.append(j); data.append(v)
        lo.append(l); hi.append(h)
    constraints = LinearConstraint(coo_matrix((data, (ri, ci)), shape=(len(b.rows), n)).tocsr(), lo, hi) if b.rows else None
    options = {"time_limit": cfg.solver_time_limit_s, "mip_rel_gap": cfg.solver_mip_gap}
    res = milp(c=-np.array(b.profit), constraints=constraints, integrality=np.array(b.integer),
               bounds=Bounds(b.lb, b.ub), options=options)
    if res.x is None:
        # โมเดลมีคำตอบเสมอ (ไม่ทำอะไรในครัว + หน่วยที่เหลือเป็น res) ถ้า HiGHS บอกว่าไม่มีคำตอบ = presolve พลาดทางตัวเลข
        res = milp(c=-np.array(b.profit), constraints=constraints, integrality=np.array(b.integer),
                   bounds=Bounds(b.lb, b.ub), options={**options, "presolve": False})
    if res.x is None:
        raise SolverError(f"solver failed: {res.message}")
    gap = getattr(res, "mip_gap", None)
    return Solution(res.x, V, float(-res.fun), "optimal" if res.status == 0 else "feasible_not_optimal",
                    None if gap is None or not np.isfinite(gap) else float(gap),
                    int((_time.perf_counter() - t0) * 1000), M,
                    sum(float(res.x[i]) * pen for i, pen in eol_penalty.items()))