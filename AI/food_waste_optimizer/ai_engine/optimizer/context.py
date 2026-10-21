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
  เวลา: เริ่มงาน = kitchen_start (วันนี้ = ตอนนี้ + lead), เมนูเริ่มขายเมื่อ batch แรกเสร็จ (เริ่ม + เวลาทำ 1 batch)
        งานเสร็จ (due_by) = เริ่ม + เวลาทำ x batch ต้องไม่เกินเลิกกะ (kitchen_due_time) และไม่เกินเวลาหมดอายุของ lot หลัก
  ตรวจ: สูตร active / แผนกมีในตารางครัว / ครัวว่างพอ (FULL = 0) / ทำเสร็จก่อน lot หมดอายุ / มีคนซื้อเมนู
        (recipe_demand) ในช่วงที่ของออกจากครัว / หน่วย G-ML ตรงกัน / วัตถุดิบอื่นมีพอ

Partner 2 จังหวะ (ต่อ lot ต่อ partner):
  NOW          ดึงของออกจากชั้นตอนนี้ ส่งรอบรับเร็วสุด (next_pickup) - partner_ok
  END_OF_LIFE  ของที่วางขายแล้วขายไม่หมด ส่งรอบแรกหลังหมดเวลาขาย (eol_pickup) - eol (เฉพาะ lot ที่ยังขายได้)
  เที่ยวรถ = (partner, วันที่รับ) 1 เที่ยว; ถ้าหลายจังหวะตกวันเดียวกัน ใช้เวลารับที่ช้าสุดของวันนั้น แล้วตรวจกฎซ้ำที่เวลานั้น
  รหัส U0 สูตรไม่ active  U1 ไม่มีแผนก/เวลาทำ หรือแผนกไม่มีในตารางครัว  U2 สินค้าห้ามเข้าครัว / ไม่ใช่วัตถุดิบหลัก
       U3 ชั่วโมงครัวไม่พอ  U4 lot หมดอายุก่อนงานเสร็จ  U5 ไม่มีความต้องการเมนูในช่วงนั้น  U6 หน่วยไม่ตรง
       U7 ไม่รู้จักสินค้าผลผลิต  U8 วัตถุดิบตัวอื่นในสต็อกไม่พอ 1 batch
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from ai_engine.optimizer.config import OptimizerConfig, simulated_now
from ai_engine.optimizer.demand import lot_curve, menu_segments
from ai_engine.optimizer.models import Inputs
from ai_engine.optimizer.rules import (EPS, eol_pickup, expiry_dt, is_expired, kitchen_due, kitchen_hours_budget,
                                       kitchen_start, lot_skip_reasons, markdown_tiers, next_pickup,
                                       partner_handling_per_kg, partner_min_kg, partner_reasons, partner_trip_cost,
                                       sell_end, stale_notes)


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
    sell_end: Optional[datetime] = None
    eol: dict = field(default_factory=dict)        # partner_id -> เวลารับของที่ขายไม่หมด (END_OF_LIFE)


@dataclass
class PartnerCtx:
    partner: object
    pickup: Optional[datetime]                     # รอบรับเร็วสุดของของที่ดึงออกตอนนี้ (ก่อนรวมเที่ยว)
    cap_kg: float
    trip_cost: float
    handling: float
    min_kg: float = 0.0


@dataclass
class DayCtx:
    department_id: str
    day: date
    hours: float
    due: datetime                                  # เลิกกะครัว: งานต้องเสร็จก่อนเวลานี้
    start: Optional[datetime] = None               # ครัวเริ่มงานได้


@dataclass
class Job:
    """งานครัว 1 งาน = 1 decision: สูตร r วัน d โดยใช้ lot หลัก a"""
    job_id: str
    recipe_id: str
    day: date
    due: datetime                      # เสร็จช้าสุดที่ยอมได้ = min(เลิกกะ, หมดอายุของ lot หลัก)
    anchor_lot_id: str
    anchor_product_id: str
    anchor_need: float                 # g/ml ต่อ batch ของวัตถุดิบหลักตัวนี้
    anchor_content: float              # g/ml ต่อ 1 หน่วยของ lot หลัก
    others: list                       # [(product_id, need ต่อ batch, is_primary)] DB ตัดเองแบบ FEFO
    hours_per_batch: float
    nmax: int
    start: Optional[datetime] = None   # เวลาเริ่มงาน; due_by จริง = start + hours_per_batch x batch

    def due_by(self, batches: int) -> datetime:
        return self.start + timedelta(hours=self.hours_per_batch * batches)


@dataclass
class RecipeDay:
    recipe_id: str
    day: date
    cap_units: float                   # ยอดเมนูที่คาดว่าขายได้สูงสุด = ผลรวม p x ความกว้างของทุกช่วง
    expected: float
    low: float
    fraction: float
    segments: list = field(default_factory=list)   # [(ความกว้าง, โอกาสขายออก)] ถ้าของออกจากครัววันนั้น
    sale_start: Optional[datetime] = None


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
    slots: dict = field(default_factory=dict)       # (partner_id, date) -> เวลารับของเที่ยวนั้น


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
                                  is_expired(lot, now, cfg), source, round(frac, 4), sell_end(lot, cfg))
    if any(v is None for lc in lots.values() for v in lc.product.disposal.values()):
        warnings.append("W0_DISPOSAL_FLAGS_MISSING: ไม่มี allow_animal_feed / composting / anaerobic_digestion / landfill "
                        f"ของบางสินค้า (นโยบาย {cfg.missing_flag_policy}) ส่ง products จาก GET /products มาด้วย")

    # ---- 4.2 partner (NOW / END_OF_LIFE)
    partners = {}
    for p in inputs.partners.values():
        partners[p.partner_id] = PartnerCtx(p, next_pickup(p, now, cfg), p.max_kg, partner_trip_cost(p, cfg),
                                            partner_handling_per_kg(p), partner_min_kg(p, cfg))
    possible_kg = defaultdict(float)
    for lc in lots.values():
        for pid, pc in partners.items():
            key = f"{pc.partner.partner_type}:{pid}"
            reasons = partner_reasons(lc.lot, lc.product, pc.partner, pc.pickup, pc.cap_kg, cfg, now)
            if reasons:
                lc.excluded[key] = reasons
            else:
                lc.partner_ok.append(pid)
            if lc.tiers:
                when = eol_pickup(pc.partner, lc.lot, now, cfg)
                eol_reasons = partner_reasons(lc.lot, lc.product, pc.partner, when, pc.cap_kg, cfg, now)
                if eol_reasons:
                    lc.excluded[f"EOL:{key}"] = eol_reasons
                else:
                    lc.eol[pid] = when
            if pid in lc.partner_ok or pid in lc.eol:
                possible_kg[pid] += lc.lot.quantity * lc.weight_kg
    for pid, pc in partners.items():       # P7: ต่อให้ส่งทุก lot ที่เข้าเกณฑ์ยังไม่ถึงขั้นต่ำต่อรอบ
        if pid in possible_kg and pc.min_kg > possible_kg[pid] + EPS:
            reason = [f"P7_BELOW_MIN_KG {possible_kg[pid]:.2f} kg < {pc.min_kg:g} kg"]
            for lc in lots.values():
                if pid in lc.partner_ok:
                    lc.partner_ok.remove(pid)
                    lc.excluded[f"{pc.partner.partner_type}:{pid}"] = reason
                if lc.eol.pop(pid, None) is not None:
                    lc.excluded[f"EOL:{pc.partner.partner_type}:{pid}"] = reason
    slots = _merge_slots(lots, partners, cfg, now)

    # ---- 4.3 ชั่วโมงครัวต่อ (แผนก, วัน)
    hours = {}
    for (dept, day), kd in inputs.kitchen.items():
        if day >= now.date():
            hours[(dept, day)] = DayCtx(dept, day, kitchen_hours_budget(kd.remaining_hrs, kd.status, day, now, cfg),
                                        kitchen_due(day, cfg), kitchen_start(day, now, cfg))

    ctx = Context(inputs, cfg, now, lots, skipped, partners, hours, [], {}, {}, {}, {}, warnings, slots)
    _build_kitchen(ctx)
    return ctx


def _merge_slots(lots: dict, partners: dict, cfg, now: datetime) -> dict:
    """รวมรอบรับเป็นเที่ยว (partner, วันที่) เวลารับ = ช้าสุดที่มีคนต้องการในวันนั้น (ยังอยู่ในช่วงเวลารับเดิม)
    แล้วตรวจกฎ partner ซ้ำที่เวลานั้น (เช่น บริจาค: อายุคงเหลือ ณ เวลารับ) ไม่ผ่าน = ตัดคู่นั้นทิ้ง"""
    slots = {}
    for lc in lots.values():
        for pid in lc.partner_ok:
            t = partners[pid].pickup
            slots[(pid, t.date())] = max(t, slots.get((pid, t.date()), t))
        for pid, t in lc.eol.items():
            slots[(pid, t.date())] = max(t, slots.get((pid, t.date()), t))
    for lc in lots.values():
        for pid in list(lc.partner_ok):
            pc = partners[pid]
            t = slots[(pid, pc.pickup.date())]
            if t != pc.pickup:
                reasons = partner_reasons(lc.lot, lc.product, pc.partner, t, pc.cap_kg, cfg, now)
                if reasons:
                    lc.partner_ok.remove(pid)
                    lc.excluded[f"{pc.partner.partner_type}:{pid}"] = [f"P9_SHARED_TRIP_AT {t.isoformat()}"] + reasons
        for pid, when in list(lc.eol.items()):
            pc = partners[pid]
            t = slots[(pid, when.date())]
            if t != when:
                reasons = partner_reasons(lc.lot, lc.product, pc.partner, t, pc.cap_kg, cfg, now)
                if reasons:
                    del lc.eol[pid]
                    lc.excluded[f"EOL:{pc.partner.partner_type}:{pid}"] = [f"P9_SHARED_TRIP_AT {t.isoformat()}"] + reasons
                else:
                    lc.eol[pid] = t
    used = {(pid, partners[pid].pickup.date()) for lc in lots.values() for pid in lc.partner_ok}
    used |= {(pid, t.date()) for lc in lots.values() for pid, t in lc.eol.items()}
    return {k: v for k, v in slots.items() if k in used}


def trip_cost(ctx, pid: str, day: date) -> float:
    """ค่าเที่ยวของ (partner, วัน): วันรับรอบแรกของ partner = เต็ม, วันถัดไป = x deferred_trip_cost_share"""
    pc = ctx.partners[pid]
    first = pc.pickup.date() if pc.pickup else None
    return pc.trip_cost if day == first else pc.trip_cost * ctx.cfg.deferred_trip_cost_share


def trip_min_kg(ctx, pid: str, day: date) -> float:
    """ขั้นต่ำต่อเที่ยว: เที่ยววันถัดไปที่ไม่คิดค่าเที่ยว (share = 0) ถือว่ารวมกับของรอบหน้า ไม่บังคับขั้นต่ำ"""
    pc = ctx.partners[pid]
    first = pc.pickup.date() if pc.pickup else None
    return pc.min_kg if day == first or ctx.cfg.deferred_trip_cost_share > 0 else 0.0


def trip_key(ctx, lid: str, pid: str, timing: str):
    """เที่ยวที่หน่วยของ lot นี้ไปกับ partner นี้ (timing = NOW | END_OF_LIFE)"""
    when = ctx.partners[pid].pickup if timing == "NOW" else ctx.lots[lid].eol[pid]
    return (pid, when.date())


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
            start = dc.start
            sale_start = start + timedelta(hours=r.hours_per_batch)
            if sale_start > dc.due + timedelta(seconds=1):
                day_reasons.append(f"U3_KITCHEN_HOURS {day} เริ่ม {start:%H:%M} เสร็จไม่ทันเลิกกะ {dc.due:%H:%M}")
                continue
            rd = inputs.recipe_demand.get(r.recipe_id)
            segments, expected, frac = menu_segments(rd, sale_start, cfg)
            cap = sum(w * p for w, p in segments)
            if cap < 0.5:
                day_reasons.append(f"U5_NO_MENU_DEMAND {day} expected {cap:.2f}")
                continue
            low = min(rd.low_qty, rd.menu_qty) * frac
            ctx.recipe_days[(r.recipe_id, day)] = RecipeDay(r.recipe_id, day, cap, round(expected, 3), round(low, 3),
                                                            frac, segments, sale_start)
            demand_units = sum(w for w, _ in segments)
            for ing in primaries:
                for lc in anchors_possible:
                    if lc.product.product_id != ing.product_id:
                        continue
                    lot = lc.lot
                    latest = min(dc.due, expiry_dt(lot.expiration_date, cfg))
                    if lc.expired or latest < sale_start:
                        lot_reasons[lot.lot_id][r.recipe_id].add(f"U4_EXPIRES_BEFORE_DUE {day}")
                        continue
                    by_time = int(math.floor((latest - start).total_seconds() / 3600 / r.hours_per_batch + EPS))
                    others = [(i.product_id, i.need, i.primary) for i in r.ingredients if i.product_id != ing.product_id]
                    short = [pid for pid, need, _ in others if _stock_content(ctx, pid, day) + EPS < need]
                    if short:
                        lot_reasons[lot.lot_id][r.recipe_id].add(f"U8_INGREDIENT_SHORT {','.join(short)} {day}")
                        continue
                    content = lc.product.content
                    nmax = min(int(math.floor(dc.hours / r.hours_per_batch + EPS)), by_time,
                               int(math.ceil(demand_units / r.output_qty - EPS)),
                               int(math.floor(lot.quantity * content / ing.need + EPS)))
                    if nmax < 1:
                        lot_reasons[lot.lot_id][r.recipe_id].add(f"U8_LOT_TOO_SMALL_FOR_1_BATCH {day}")
                        continue
                    ctx.jobs.append(Job(f"{r.recipe_id}@{day.isoformat()}#{lot.lot_id}", r.recipe_id, day, latest,
                                        lot.lot_id, lc.product.product_id, ing.need, content, others,
                                        r.hours_per_batch, nmax, start))
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