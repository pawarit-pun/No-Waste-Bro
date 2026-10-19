"""PART 4 — ประกอบ Context: เอากฎ (rules.py) ไปตรวจกับข้อมูลจริงทุก lot / partner / สูตร / ครัว ก่อนเข้า solver

ผลลัพธ์ = "ทางเลือกที่ผ่านกฎแล้วเท่านั้น" + รหัสเหตุผลของทางที่ถูกตัด (excluded) ต่อ lot
solver ไม่ตรวจกฎซ้ำ มีหน้าที่เลือกสัดส่วนที่กำไรสุทธิสูงสุดจากทางที่ผ่านกฎ

งานครัว (ให้ตรงกับที่ server ทำจริงตอน POST /tasks และ complete_task):
  1 decision KITCHEN_REPURPOSE = 1 งาน (สูตร r, วัน d, lot หลัก a)
    - lot หลัก a = lot เสี่ยงที่เป็นวัตถุดิบหลัก (is_primary_ingredient) ของสูตร
      action_quantity = ceil(required_quantity x batch_count / net_content)  (สูตรเดียวกับ demo_seed ใน DB)
    - วัตถุดิบตัวอื่นของสูตร DB ตัดเองตอน complete แบบหมดอายุก่อนตัดก่อน (FEFO) จาก ingredient_stock
      -> Optimizer ต้องรวมความต้องการทุกงานเองแล้วเทียบกับสต็อก และนับว่า lot เสี่ยงที่ถูก FEFO ตัดไปก็ถูกใช้ในครัวด้วย
    - ชั่วโมงครัวที่ server จอง = estimated_prep_time_mins x batch_count ของแต่ละ decision (ไม่จองซ้ำ)
  ตรวจ: สูตร active / แผนกมีในตารางครัว / ครัวว่างพอ (FULL = 0) / ทำเสร็จก่อน lot หมดอายุ / มีคนซื้อเมนู
        (recipe_demand) ในช่วงที่ของออกจากครัว / หน่วย G-ML ตรงกัน / วัตถุดิบอื่นมีพอ
  รหัส U0 สูตรไม่ active  U1 ไม่มีแผนก/เวลาทำ หรือแผนกไม่มีในตารางครัว  U2 สินค้าห้ามเข้าครัว / ไม่ใช่วัตถุดิบหลัก
       U3 ชั่วโมงครัวไม่พอ  U4 lot หมดอายุก่อนงานเสร็จ  U5 ไม่มีความต้องการเมนูในช่วงนั้น  U6 หน่วยไม่ตรง
       U7 ไม่รู้จักสินค้าผลผลิต  U8 วัตถุดิบตัวอื่นในสต็อกไม่พอ 1 batch
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from ai_engine.optimizer.config import OptimizerConfig, simulated_now
from ai_engine.optimizer.demand import conservative, lot_curve, menu_cap
from ai_engine.optimizer.models import Inputs
from ai_engine.optimizer.rules import (EPS, expiry_dt, is_expired, kitchen_due, kitchen_hours_budget,
                                       lot_skip_reasons, markdown_tiers, next_pickup, partner_handling_per_kg,
                                       partner_reasons, partner_trip_cost, stale_notes)


@dataclass
class LotCtx:
    lot: object
    product: object
    tiers: list
    partner_ok: list
    excluded: dict
    notes: list
    weight_kg: Optional[float]
    expired: bool
    demand_source: str
    demand_fraction: float


@dataclass
class PartnerCtx:
    partner: object
    pickup: Optional[datetime]
    cap_kg: float
    trip_cost: float
    handling: float


@dataclass
class DayCtx:
    department_id: str
    day: date
    hours: float
    due: datetime


@dataclass
class Job:
    """งานครัว 1 งาน = 1 decision: สูตร r วัน d โดยใช้ lot หลัก a"""
    job_id: str
    recipe_id: str
    day: date
    due: datetime
    anchor_lot_id: str
    anchor_product_id: str
    anchor_need: float                 # g/ml ต่อ batch ของวัตถุดิบหลักตัวนี้
    anchor_content: float              # g/ml ต่อ 1 หน่วยของ lot หลัก
    others: list                       # [(product_id, need ต่อ batch, is_primary)] DB ตัดเองแบบ FEFO
    hours_per_batch: float
    nmax: int


@dataclass
class RecipeDay:
    recipe_id: str
    day: date
    cap_units: float                   # เมนูที่คาดว่าขายได้ (แบบระวัง) ถ้าของออกจากครัววันนั้น
    expected: float
    low: float
    fraction: float


@dataclass
class FefoLot:
    lot_id: str
    product_id: str
    content: float
    quantity: int
    expiration_date: date
    at_risk: bool


@dataclass
class Context:
    inputs: Inputs
    cfg: OptimizerConfig
    now: datetime
    lots: dict
    skipped: dict
    partners: dict
    hours: dict
    jobs: list
    recipe_days: dict
    fefo: dict                          # product_id -> [FefoLot] เรียง FEFO
    fefo_days: dict                     # product_id -> [date]
    recipe_status: dict                 # recipe_id -> {"eligible": bool, "reasons": [...]}
    warnings: list = field(default_factory=list)


def build_context(inputs: Inputs, now: Optional[datetime] = None, cfg: Optional[OptimizerConfig] = None,
                  decided: frozenset = frozenset()) -> Context:
    cfg = cfg or OptimizerConfig()
    now = now or simulated_now(inputs.reference_date)
    warnings = list(inputs.warnings)
    if now.date() != inputs.reference_date:
        warnings.append(f"T1_NOW_NOT_REFERENCE_DATE now {now.date()} vs reference_date {inputs.reference_date}")

    # ---- 4.1 lot ที่ต้องจัดการ + markdown
    lots, skipped = {}, {}
    for lot in inputs.lots:
        product = inputs.products.get(lot.product_id)
        reasons = lot_skip_reasons(lot, product, decided, cfg)
        if reasons:
            skipped[lot.lot_id] = {"assessment_id": lot.assessment_id, "reasons": reasons}
            continue
        rows, frac, source = lot_curve(lot, now, inputs.reference_date, cfg)
        tiers, excluded, notes = markdown_tiers(lot, product, rows, now, cfg)
        notes = stale_notes(lot, inputs.reference_date) + notes
        lots[lot.lot_id] = LotCtx(lot, product, tiers, [], excluded, notes, product.weight_kg,
                                  is_expired(lot, now, cfg), source, round(frac, 4))
    if any(v is None for lc in lots.values() for v in lc.product.disposal.values()):
        warnings.append("W0_DISPOSAL_FLAGS_MISSING: ไม่มี allow_animal_feed / composting / anaerobic_digestion / landfill "
                        f"ของบางสินค้า (นโยบาย {cfg.missing_flag_policy}) ส่ง products จาก GET /products มาด้วย")

    # ---- 4.2 partner
    partners = {}
    for p in inputs.partners.values():
        pickup = next_pickup(p, now, cfg)
        partners[p.partner_id] = PartnerCtx(p, pickup, p.max_kg, partner_trip_cost(p), partner_handling_per_kg(p))
    possible_kg = defaultdict(float)
    for lc in lots.values():
        for pid, pc in partners.items():
            reasons = partner_reasons(lc.lot, lc.product, pc.partner, pc.pickup, pc.cap_kg, cfg, now)
            if reasons:
                lc.excluded[f"{pc.partner.partner_type}:{pid}"] = reasons
            else:
                lc.partner_ok.append(pid)
                possible_kg[pid] += lc.lot.quantity * lc.weight_kg
    for pid, pc in partners.items():       # P7: ต่อให้ส่งทุก lot ที่เข้าเกณฑ์ยังไม่ถึงขั้นต่ำต่อรอบ
        if pid in possible_kg and pc.partner.min_kg > possible_kg[pid] + EPS:
            for lc in lots.values():
                if pid in lc.partner_ok:
                    lc.partner_ok.remove(pid)
                    lc.excluded[f"{pc.partner.partner_type}:{pid}"] = [
                        f"P7_BELOW_MIN_KG {possible_kg[pid]:.2f} kg < {pc.partner.min_kg:g} kg"]

    # ---- 4.3 ชั่วโมงครัวต่อ (แผนก, วัน)
    hours = {}
    for (dept, day), kd in inputs.kitchen.items():
        if day >= now.date():
            hours[(dept, day)] = DayCtx(dept, day, kitchen_hours_budget(kd.remaining_hrs, kd.status, day, now, cfg),
                                        kitchen_due(day, cfg))

    ctx = Context(inputs, cfg, now, lots, skipped, partners, hours, [], {}, {}, {}, {}, warnings)
    _build_kitchen(ctx)
    return ctx


def _stock_content(ctx: Context, product_id: str, day: date) -> float:
    prod = ctx.inputs.products.get(product_id)
    if prod is None or not prod.content:
        return 0.0
    return sum(s.quantity * prod.content for s in ctx.inputs.stock.get(product_id, []) if s.expiration_date >= day)


def _build_kitchen(ctx: Context) -> None:
    inputs, cfg = ctx.inputs, ctx.cfg
    ingredient_of = defaultdict(set)
    for r in inputs.recipes.values():
        for ing in r.ingredients:
            ingredient_of[ing.product_id].add(r.recipe_id)
    for lc in ctx.lots.values():
        if not ingredient_of.get(lc.product.product_id):
            lc.excluded["KITCHEN:ALL"] = ["U2_NOT_AN_INGREDIENT"]
        elif not lc.product.allow_kitchen:
            lc.excluded["KITCHEN:ALL"] = ["U2_KITCHEN_NOT_ALLOWED"]

    lot_reasons = defaultdict(lambda: defaultdict(set))       # lot_id -> recipe_id -> reasons
    for r in inputs.recipes.values():
        reasons = []
        out = inputs.products.get(r.output_product_id)
        if not r.active:
            reasons.append("U0_RECIPE_INACTIVE")
        if out is None:
            reasons.append("U7_OUTPUT_PRODUCT_UNKNOWN")
        if not r.department_id or not r.prep_mins or r.output_qty <= 0:
            reasons.append("U1_NO_DEPARTMENT_OR_PREP_TIME")
        elif not any(dept == r.department_id for dept, _ in inputs.kitchen):
            reasons.append(f"U1_DEPARTMENT_{r.department_id}_NOT_IN_KITCHEN_CAPACITY")
        for ing in r.ingredients:
            prod = inputs.products.get(ing.product_id)
            if prod is None or not prod.content or ing.need is None or prod.family != ing.family:
                reasons.append(f"U6_UNIT_MISMATCH_{ing.product_id}")
        primaries = [i for i in r.ingredients if i.primary]
        anchors_possible = [lc for lc in ctx.lots.values()
                            if lc.product.allow_kitchen and any(i.product_id == lc.product.product_id for i in primaries)]
        if not reasons and not anchors_possible:
            reasons.append("U2_NO_AT_RISK_PRIMARY_INGREDIENT")
        ctx.recipe_status[r.recipe_id] = {"eligible": not reasons, "reasons": list(reasons)}
        if reasons:
            for lc in ctx.lots.values():
                if lc.product.product_id in {i.product_id for i in r.ingredients}:
                    lot_reasons[lc.lot.lot_id][r.recipe_id].update(reasons)
            continue

        day_reasons = []
        for (dept, day), dc in sorted(ctx.hours.items(), key=lambda kv: kv[0][1]):
            if dept != r.department_id:
                continue
            if dc.hours + EPS < r.hours_per_batch:
                day_reasons.append(f"U3_KITCHEN_HOURS {day} {dc.hours:.2f}h < {r.hours_per_batch:.2f}h")
                continue
            expected, low, frac = menu_cap(inputs.recipe_demand.get(r.recipe_id), dc.due, cfg)
            cap = conservative(expected, low, cfg.demand_kappa)
            if cap < 0.5:
                day_reasons.append(f"U5_NO_MENU_DEMAND {day} cap {cap:.2f}")
                continue
            ctx.recipe_days[(r.recipe_id, day)] = RecipeDay(r.recipe_id, day, cap, round(expected, 3), round(low, 3), frac)
            for ing in primaries:
                for lc in anchors_possible:
                    if lc.product.product_id != ing.product_id:
                        continue
                    lot = lc.lot
                    if lc.expired or expiry_dt(lot.expiration_date, cfg) < dc.due:
                        lot_reasons[lot.lot_id][r.recipe_id].add(f"U4_EXPIRES_BEFORE_DUE {day}")
                        continue
                    others = [(i.product_id, i.need, i.primary) for i in r.ingredients if i.product_id != ing.product_id]
                    short = [pid for pid, need, _ in others if _stock_content(ctx, pid, day) + EPS < need]
                    if short:
                        lot_reasons[lot.lot_id][r.recipe_id].add(f"U8_INGREDIENT_SHORT {','.join(short)} {day}")
                        continue
                    content = lc.product.content
                    nmax = min(int(math.floor(dc.hours / r.hours_per_batch + EPS)),
                               int(math.ceil(cap / r.output_qty - EPS)),
                               int(math.floor(lot.quantity * content / ing.need + EPS)))
                    if nmax < 1:
                        lot_reasons[lot.lot_id][r.recipe_id].add(f"U8_LOT_TOO_SMALL_FOR_1_BATCH {day}")
                        continue
                    ctx.jobs.append(Job(f"{r.recipe_id}@{day.isoformat()}#{lot.lot_id}", r.recipe_id, day, dc.due,
                                        lot.lot_id, lc.product.product_id, ing.need, content, others,
                                        r.hours_per_batch, nmax))
        if not any(j.recipe_id == r.recipe_id for j in ctx.jobs):
            ctx.recipe_status[r.recipe_id]["eligible"] = False
            ctx.recipe_status[r.recipe_id]["reasons"] = day_reasons or ["U4_NO_FEASIBLE_JOB"]
            for lc in anchors_possible:
                lot_reasons[lc.lot.lot_id][r.recipe_id].update(day_reasons)

    for lot_id, per_recipe in lot_reasons.items():
        lc = ctx.lots[lot_id]
        for rid, rs in per_recipe.items():
            if rs and not any(j.anchor_lot_id == lot_id and j.recipe_id == rid for j in ctx.jobs):
                lc.excluded[f"KITCHEN:{rid}"] = sorted(rs)

    # ---- FEFO: วัตถุดิบที่ DB ตัดเองตอน complete
    for j in ctx.jobs:
        for pid, _, _ in j.others:
            days = ctx.fefo_days.setdefault(pid, [])
            if j.day not in days:
                days.append(j.day)
    for pid, days in ctx.fefo_days.items():
        days.sort()
        prod = inputs.products[pid]
        rows = []
        for s in inputs.stock.get(pid, []):
            lc = ctx.lots.get(s.lot_id)
            qty = lc.lot.quantity if lc else s.quantity
            rows.append(FefoLot(s.lot_id, pid, prod.content, qty, s.expiration_date, lc is not None))
        ctx.fefo[pid] = rows