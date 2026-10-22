"""PART 5 — MILP (HiGHS ผ่าน scipy): แบ่งทุก lot พร้อมกันให้กำไรสุทธิสูงสุด (ขาดทุนน้อยสุด)

ทุกหน่วยของ lot เสี่ยงถูกนับต้นทุนสินค้า (unit_cost) ครั้งเดียวในทางที่มันไป จึงเทียบทุกทางได้ตรงกัน
(DISCARD เปล่า = -จำนวน x unit_cost ตามตัวอย่าง Swagger)

ตัวแปร                                                     กำไรต่อหน่วยในเป้าหมาย
  t[L,d] bin   เลือกราคา d ของ lot (1 lot 1 ราคา, Σt <= 1)    -lost_sales_cost (ยอดที่ล็อตอื่นเสียไป)
  shelf[L] int หน่วยที่วางบนชั้น = Σ_d Σ_seg s                    -unit_cost
  s[L,d,i]     หน่วยบนชั้นในช่วง i ของ demand (<= ความกว้าง·t)     p_i·price_d  (p_i = โอกาสขายออก จาก P10/P50/P90)
               ช่วงขายง่ายมีกำไรต่อหน่วยมากกว่า (รายได้ concave) solver จึงเติมจากช่วงแรกเองโดยไม่ต้องใช้ binary
  ค่าส่ง partner P ต่อ kg: r_P = buyback - handling - fee_per_kg   (fee_per_kg = ค่าเที่ยวเฉลี่ยต่อ kg ของโหมด BIN, DEDICATED = 0)
  y[L,P]       ราคาปกติ: หน่วยที่คาดว่าขายไม่หมด ส่ง P หลังหมดเวลาขาย                  r_P·kg
               Σ_P y (+ rese) = Σ_i (1 - p_i)·s[L,0,i]
  ym[L,P]      ลดราคา: ของที่ขายไม่หมดอยู่ใน lot ใหม่ที่แยกตอนติดป้าย (IDLE) รอบถัดไปวางแผนกำจัดใหม่
               รอบนี้ประมาณค่ากำจัดไว้เท่านั้น (เฉพาะ partner โหมด BIN)  Σ_P ym (+ resem) = Σ_{d>0} Σ_i (1 - p_i)·s[L,d,i]
               อยู่ในเที่ยวเดียวกับของเหลือราคาปกติของวันนั้น (เพดานเที่ยวเต็มใช้ร่วมกัน)
  rese[L] / resem[L]  ของที่ขายไม่หมดแต่ไม่มี partner end-of-life รับ (ทิ้งเองในร้าน)  -factor·unit_cost (เป้าหมายเท่านั้น)
  x[L,P] int   ดึงออกจากชั้นตอนนี้ ส่ง partner P                 r_P·kg - unit_cost
  z[P,วัน] bin เฉพาะ partner โหมด DEDICATED: เรียกรถเฉพาะของรอบนี้ (x + y) kg >= min·z   -(fixed + travel) [DONATION: -fixed]
               ไม่จำกัด kg: เกินความจุ = รอบขนเพิ่มของเที่ยวเดียวกัน ไม่มีค่าเที่ยวเพิ่ม (ยังคิด handling ต่อ kg)
               โหมด BIN ไม่มี z / ขั้นต่ำต่อรอบ: ของเข้าถัง เรียกรถเมื่อถังถึงปริมาณที่คุ้ม (ค่าเที่ยวอยู่ใน fee_per_kg แล้ว)
  w[k,P,วัน] bin + credit  โหมด BIN: ค่าเที่ยวรวมของ (partner, วันรับ) = min(fee_per_kg x kg, ค่าเรียกรถ 1 ครั้ง)
               ของก้อนใหญ่ (เกินปริมาณที่คุ้ม) เรียกรถเต็มเที่ยวจ่ายครั้งเดียว ไม่ใช่คิดค่าเที่ยวต่อ kg ซ้ำหลายสิบเที่ยว
               เฉพาะของที่ขายไม่ได้แล้ว: ดึงออกจาก lot ที่ไม่มีราคาขาย (หมดอายุ / ห้ามขาย) + ของเหลือหลังหมดเวลาขาย (y, ym)
               ของที่ยังขายได้แต่ดึงออกตอนนี้ (x ของ lot ที่มี tier) จ่ายค่าเฉลี่ยต่อ kg เสมอ
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

import time as _time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

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
        return sum(self.amount(k) for k in self.var if k[0] in ("rese", "resem"))

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
    rate = lambda pc: pc.partner.buyback - pc.handling - pc.fee_per_kg     # บาท/kg (ไม่รวมต้นทุนสินค้า)
    trips = defaultdict(dict)                                # (partner DEDICATED, วัน) -> {var: kg ต่อหน่วย}
    bin_loads = defaultdict(dict)                            # ("bin", partner BIN, วัน) -> {var: kg ต่อหน่วย}
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
        on_shelf = {shelf: -1.0}
        leftover = {"": {}, "m": {}}                         # "" = ราคาปกติ (รอบนี้), "m" = ลดราคา (รอบถัดไป)
        for t in tiers:
            d = t["discount_pct"]
            part = leftover["" if d == 0 else "m"]
            ti = V[("t", lid, d)] = b.var(0, 1, True, -t["lost_sales_cost"])
            for i, (width, p) in enumerate(t["segments"] + [(qty, 0.0)]):     # ช่วงสุดท้าย = เกินหาง ขายไม่ได้
                si = V[("s", lid, d, i)] = b.var(0, width, False, p * t["price"])
                b.row({si: 1.0, ti: -width}, hi=0.0)
                on_shelf[si] = 1.0
                part[si] = -(1.0 - p)
        b.row({V[("t", lid, t["discount_pct"])]: 1.0 for t in tiers}, hi=1.0)
        b.row(on_shelf, 0.0, 0.0)                                           # shelf = Σ s
        eol = [pid for pid in lc.eol if types_ok(pid)]
        for tag, part in leftover.items():
            if not part:
                continue
            # ลดราคา: ของเหลือถูกตัดสินใจรอบหน้า ใช้ได้เฉพาะถังของ partner โหมด BIN (รถ DEDICATED ของรอบนี้ขนไม่ได้)
            routes = [pid for pid in eol if not tag or ctx.partners[pid].mode == "BIN"]
            for pid in routes:
                pc = ctx.partners[pid]
                yi = V[("y" + tag, lid, pid)] = b.var(0, qty, False, rate(pc) * w)
                part[yi] = 1.0
                day = lc.eol[pid].date()
                if pc.mode == "BIN":
                    # ของเหลือราคาปกติ (y) และของเหลือจากการลดราคา (ym) ออกจากร้านเวลาเดียวกัน ใช้เที่ยวเดียวกัน
                    bin_loads[("bin", pid, day)][yi] = w
                elif not tag:
                    trips[(pid, day)][yi] = w
            if not routes:
                pen = cfg.eol_no_route_penalty_factor * c
                ri = V[("rese" + tag, lid)] = b.var(0, qty, False, -pen)
                eol_penalty[ri] = pen
                part[ri] = 1.0
            b.row(part, 0.0, 0.0)                                           # Σ y = Σ (1 - p)·s

    # ---- 5.2 partner: ดึงออกตอนนี้ (x) + เที่ยวรถต่อ (partner, วัน)
    for lid, lc in ctx.lots.items():
        for pid in lc.partner_ok:
            if not types_ok(pid):
                continue
            pc, w = ctx.partners[pid], lc.weight_kg
            # tie-break: ถ้ายังวางขายได้ ให้เก็บไว้บนชั้นก่อนเมื่อต้นทุนเท่ากัน (ยังมีโอกาสขายเกินที่คาด)
            tie = TIE_BREAK if lc.tiers else 0.0
            xi = V[("x", lid, pid)] = b.var(0, lc.lot.quantity, True, rate(pc) * w - lc.lot.unit_cost - tie)
            balance[lid][xi] = 1.0
            if pc.mode == "DEDICATED":
                trips[(pid, pc.pickup.date())][xi] = w
            elif not lc.tiers:
                # ของที่ยังขายได้ไม่เข้าเพดานเที่ยวเต็ม: ไม่งั้นพอเที่ยวเต็มเปิดแล้ว ของบนชั้นจะติดรถไปฟรี (เทลง landfill)
                bin_loads[("bin", pid, pc.pickup.date())][xi] = w
    for (pid, day), loads in trips.items():                  # DEDICATED: เรียกรถเฉพาะ จ่ายเต็ม + ขั้นต่ำต่อรอบ
        pc = ctx.partners[pid]
        zi = V[("z", pid, day)] = b.var(0, 1, True, -pc.trip_cost)
        _trip_rows(b, loads, zi, pc.min_kg)
    for (kind, pid, day), loads in bin_loads.items():       # BIN: ค่าเที่ยวไม่เกินเรียกรถ 1 ครั้ง (ของก้อนใหญ่)
        _full_call_cap(b, V, ctx.partners[pid], (kind, pid, day), loads)

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


def _trip_rows(b: _Builder, loads: dict, zi: int, min_kg: float) -> None:
    """ขนได้เมื่อเปิดเที่ยว (z = 1) โดยไม่จำกัด kg: ของเกินความจุใช้รอบขนเพิ่มของเที่ยวเดียวกัน จ่ายค่าเที่ยวครั้งเดียว
    ขอบบน = kg สูงสุดที่ตัวแปรของเที่ยวนี้รับได้ทั้งหมด (big-M ที่แคบที่สุด) ขั้นต่ำต่อเที่ยวยังบังคับ"""
    most = sum(b.ub[v] * kg for v, kg in loads.items())
    b.row({**loads, zi: -most}, hi=0.0)
    if min_kg > 0:
        b.row({**loads, zi: -min_kg}, lo=0.0)


def _full_call_cap(b: _Builder, V: dict, pc, key: tuple, loads: dict) -> None:
    """เพดานค่าเที่ยวของถัง (partner โหมด BIN) ต่อ (partner, วันรับ): ค่าเฉลี่ยต่อ kg x kg แต่ไม่เกินค่าเรียกรถ 1 ครั้ง
    ของรอบนี้หนักถึงปริมาณที่คุ้ม (fee_per_kg x kg >= ค่าเรียกรถ) = เรียกรถเต็มเที่ยวทันที (w = 1) จ่ายครั้งเดียว
    kg ที่เกินเสียแค่ handling (รอบขนเพิ่มฟรี) ต้นทุนต่อเนื่องที่จุดเปลี่ยน จึงไม่จูงใจให้ดึงของมาให้ถึงเกณฑ์
    g = kg ที่ไปกับเที่ยวเต็ม (มีได้เฉพาะ w = 1, ไม่เกิน kg ของกลุ่ม) คืนค่าเฉลี่ยต่อ kg ของ g แล้วคิดค่าเรียกรถ 1 ครั้งแทน
      เป้าหมาย: -fee_per_kg·kg (ที่ตัวแปรของแต่ละหน่วยแล้ว) + fee_per_kg·g - ค่าเรียกรถ·w
      w = 1 -> g = kg ทั้งกลุ่ม -> จ่ายค่าเรียกรถ 1 ครั้ง; w = 0 -> g = 0 -> จ่ายค่าเฉลี่ยต่อ kg
    เขียนเป็นหน่วย kg (ไม่ใช่บาท x kg) ให้สัมประสิทธิ์ไม่ห่างกันมาก (big-M เป็นบาทเคยทำ HiGHS พัง: Solve error)
    key = ("bin", partner, วันรับ) รวมของเหลือจากการลดราคา (ym ค่าประมาณ) ที่ออกจากร้านวันเดียวกันด้วย"""
    if pc.trip_cost <= 0 or pc.fee_per_kg <= 0:
        return
    most_kg = sum(b.ub[v] * kg for v, kg in loads.items())
    if pc.fee_per_kg * most_kg <= pc.trip_cost + 1e-6:       # ต่อให้ขนทุกอย่างก็ไม่ถึงปริมาณที่คุ้ม
        return
    wi = V[("w",) + key] = b.var(0, 1, True, -pc.trip_cost)
    gi = V[("full_kg",) + key] = b.var(0, most_kg, False, pc.fee_per_kg)
    b.row({gi: 1.0, **{v: -kg for v, kg in loads.items()}}, hi=0.0)     # g <= kg ของกลุ่ม
    b.row({gi: 1.0, wi: -most_kg}, hi=0.0)                              # g <= kg สูงสุด x w


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