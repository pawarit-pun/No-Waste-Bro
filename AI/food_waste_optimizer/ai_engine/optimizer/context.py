"""PART 4 — ประกอบ Context: เอากฎ (rules.py) ไปตรวจกับข้อมูลจริงทุก lot / partner / สูตร ก่อนเข้า solver

ผลลัพธ์คือ "ทางเลือกที่ผ่านกฎแล้วเท่านั้น" + เหตุผลของทางที่ถูกตัด (excluded) ต่อ lot
Solver ไม่ต้องตรวจกฎซ้ำ มีหน้าที่แค่เลือกสัดส่วนที่กำไรสูงสุดจากทางที่ผ่านกฎ
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Optional

from ai_engine.clock import now_for
from ai_engine.optimizer.config import OptimizerConfig
from ai_engine.optimizer.demand import resolve_demand
from ai_engine.optimizer.models import Inputs
from ai_engine.optimizer.rules import (EPS, expiry_dt, is_expired, kitchen_due, kitchen_hours_budget,markdown_tiers, next_pickup, partner_handling_per_kg,partner_reasons, partner_trip_cost)


@dataclass
class LotCtx:
    lot: object
    product: object
    tiers: list
    partner_ok: list
    excluded: dict
    weight_kg: Optional[float]
    expired: bool


@dataclass
class PartnerCtx:
    partner: object
    pickup: Optional[datetime]
    booked_kg: float
    cap_kg: float                     # ความจุที่เหลือของรอบรับ = max - ที่จองไปแล้ว
    trip_cost: float                  # fixed (+ travel ถ้าไม่ใช่ DONATION)
    handling: float                   # ต่อ kg
    sunk: bool                        # จองเที่ยวไว้แล้ว -> ไม่คิดค่าเที่ยวซ้ำ


@dataclass
class DayCtx:
    department_id: str
    day: date
    hours: float
    due: datetime


@dataclass
class RecipeCtx:
    recipe: object
    eligible: bool
    reasons: list
    days: list
    hours_per_batch: float
    out_price: float
    demand_units: float
    batch_profit: float               # yield × ราคาขาย − utility_cost
    primary: list
    secondary: list
    suppliers: dict                   # (product_id, day) -> [lot_id]  วัตถุดิบหลักจาก lot เสี่ยง
    sec_suppliers: dict               # (product_id, day) -> [lot_id]  วัตถุดิบรองจาก lot เสี่ยง


@dataclass
class Context:
    inputs: Inputs
    cfg: OptimizerConfig
    now: datetime
    lots: dict
    partners: dict
    recipes: dict
    hours: dict
    warnings: list = field(default_factory=list)

    def nr_stock(self, product_id: str, day: date) -> float:
        """สต็อกวัตถุดิบ (g/ml) จาก lot ที่ "ไม่ใช่ lot เสี่ยง" และยังไม่หมดอายุ ณ วัน day
        (ingredient_stock.total_content ลบส่วนของ lot เสี่ยงที่ถูกจัดสรรไปทางอื่น)"""
        product = self.inputs.products.get(product_id)
        if product is None or not product.content:
            return 0.0
        return sum(s.quantity * product.content for s in self.inputs.stock.get(product_id, [])
                   if s.lot_id not in self.lots and s.expiration_date >= day)


def build_context(inputs: Inputs, demand: Optional[dict] = None, now: Optional[datetime] = None,
                  cfg: Optional[OptimizerConfig] = None,
                  booked_kg: Optional[Callable[[str, date], float]] = None) -> Context:
    cfg = cfg or OptimizerConfig()
    now = now or now_for(inputs.reference_date)
    curves, menu = resolve_demand(inputs, demand, cfg)
    warnings: list = []

    # ---- lot + markdown ----
    lots: dict = {}
    for lot in inputs.lots:
        product = inputs.products.get(lot.product_id)
        if product is None:
            warnings.append(f"lot {lot.lot_id}: ไม่พบ product {lot.product_id} ใน products — ข้าม")
            continue
        tiers, excluded = markdown_tiers(lot, product, curves.get(lot.lot_id, []), now, cfg)
        lots[lot.lot_id] = LotCtx(lot, product, tiers, [], excluded, product.weight_kg, is_expired(lot, now, cfg))
    if inputs.lots and any(v is None for p in inputs.products.values() for v in p.disposal.values()):
        warnings.append("products ไม่มี allow_animal_feed/composting/anaerobic_digestion/landfill "
                        f"(นโยบาย={cfg.missing_flag_policy}) — ดู io.enrich_products_with_flags")

    # ---- partner ----
    partners: dict = {}
    for p in inputs.partners.values():
        pickup = next_pickup(p, now, cfg)
        booked = booked_kg(p.partner_id, pickup.date()) if (booked_kg and pickup) else 0.0
        partners[p.partner_id] = PartnerCtx(p, pickup, booked, max(0.0, p.max_kg - booked),
                                            partner_trip_cost(p), partner_handling_per_kg(p), booked > 0)

    possible_kg: dict = defaultdict(float)
    for lc in lots.values():
        for pid, pc in partners.items():
            reasons = partner_reasons(lc.lot, lc.product, pc.partner, pc.pickup, pc.cap_kg, cfg, now)
            if reasons:
                lc.excluded[f"{pc.partner.partner_type}:{pid}"] = reasons
            else:
                lc.partner_ok.append(pid)
                possible_kg[pid] += lc.lot.quantity * lc.weight_kg
    # P7: ต่อให้ส่งทุก lot ที่เข้าเกณฑ์ ก็ไม่ถึง min_kg_per_pickup -> partner นี้ใช้ไม่ได้รอบนี้
    for pid, pc in partners.items():
        if pid in possible_kg and pc.partner.min_kg > possible_kg[pid] + EPS:
            for lc in lots.values():
                if pid in lc.partner_ok:
                    lc.partner_ok.remove(pid)
                    lc.excluded[f"{pc.partner.partner_type}:{pid}"] = [
                        f"P7_BELOW_MIN_KG_{possible_kg[pid]:.1f}_NEED_{pc.partner.min_kg:g}"]

    # ---- ครัว: ชั่วโมงต่อ (แผนก, วัน) ----
    hours: dict = {}
    for (dept, day), kd in inputs.kitchen.items():
        if day < now.date():
            continue
        hours[(dept, day)] = DayCtx(dept, day, kitchen_hours_budget(kd.remaining_hrs, kd.status, day, now, cfg),
                                    kitchen_due(day, cfg))

    ctx = Context(inputs, cfg, now, lots, partners, {}, hours, warnings)

    # ---- สูตรอาหาร ----
    for r in inputs.recipes.values():
        ctx.recipes[r.recipe_id] = _recipe_ctx(ctx, r, menu)
    for rid, rc in ctx.recipes.items():
        for ing in rc.primary + rc.secondary:
            for lc in lots.values():
                if lc.product.product_id != ing.product_id:
                    continue
                if not lc.product.allow_kitchen:
                    lc.excluded[f"KITCHEN:{rid}"] = ["U1_KITCHEN_NOT_ALLOWED"]
                elif not rc.eligible:
                    lc.excluded[f"KITCHEN:{rid}"] = list(rc.reasons)
    return ctx


def _recipe_ctx(ctx: Context, r, menu: dict) -> RecipeCtx:
    inputs, cfg, now = ctx.inputs, ctx.cfg, ctx.now
    reasons: list = []
    out = inputs.products.get(r.output_product_id)
    primary = [i for i in r.ingredients if i.primary]
    secondary = [i for i in r.ingredients if not i.primary]
    if not r.active:
        reasons.append("U0_RECIPE_INACTIVE")
    if out is None:
        reasons.append("U7_OUTPUT_PRODUCT_UNKNOWN")
    if not r.department_id or not r.prep_mins or r.output_qty <= 0:
        reasons.append("U1_NO_DEPARTMENT_OR_PREP_TIME")
    daily = float(menu.get(r.recipe_id, 0.0))
    if daily <= 0:
        reasons.append("U5_NO_MENU_DEMAND")
    if not primary:
        reasons.append("U2_NO_PRIMARY_INGREDIENT")
    for ing in r.ingredients:
        prod = inputs.products.get(ing.product_id)
        if prod is None or not prod.content or ing.need is None or prod.family != ing.family:
            reasons.append(f"U6_UNIT_MISMATCH_{ing.product_id}")

    hours_per_batch = (r.prep_mins or 0) / 60.0
    out_price = out.regular_price if out else 0.0
    # ASSUMPTION: ขายสินค้าที่ผลิตได้ภายใน shelf_life_days + 1 วัน (0 = ขายให้หมดในวันนั้น)
    demand_units = math.floor(daily * max(1, r.shelf_life_days + 1) + EPS)
    rc = RecipeCtx(r, False, reasons, [], hours_per_batch, out_price, float(demand_units),
                   r.output_qty * out_price - r.utility_cost, primary, secondary, {}, {})
    if reasons:
        return rc

    # lot เสี่ยงที่เป็นวัตถุดิบของสูตร + ทำทันก่อนหมดอายุ (due_by ของวันนั้นต้องไม่เกินเวลาหมดอายุ)
    def usable(lc, day) -> bool:
        return lc.product.allow_kitchen and not lc.expired and expiry_dt(lc.lot, cfg) >= ctx.hours[(r.department_id, day)].due

    day_hours = {d: dc.hours for (dept, d), dc in ctx.hours.items() if dept == r.department_id}
    hour_days = [d for d, h in sorted(day_hours.items()) if h >= hours_per_batch - EPS]
    if not hour_days:
        reasons.append("U3_NO_KITCHEN_HOURS")
        return rc
    for ing in primary:
        if not any(lc.product.product_id == ing.product_id and lc.product.allow_kitchen and not lc.expired
                   for lc in ctx.lots.values()):
            reasons.append(f"U2_PRIMARY_MISSING_{ing.product_id}")
    if reasons:
        return rc

    feasible = []
    for d in hour_days:
        ok = True
        for ing in primary:
            sup = [lid for lid, lc in ctx.lots.items() if lc.product.product_id == ing.product_id and usable(lc, d)]
            rc.suppliers[(ing.product_id, d)] = sup
            ok = ok and bool(sup)
        for ing in secondary:
            rc.sec_suppliers[(ing.product_id, d)] = [
                lid for lid, lc in ctx.lots.items() if lc.product.product_id == ing.product_id and usable(lc, d)]
        if ok:
            feasible.append(d)
    if not feasible:
        reasons.append("U4_CANNOT_FINISH_BEFORE_EXPIRY")
        return rc
    # วัตถุดิบรองต้องมีพอ (สต็อกที่ไม่เสี่ยง + lot เสี่ยง) อย่างน้อย 1 batch
    for ing in secondary:
        prod = inputs.products[ing.product_id]
        have = ctx.nr_stock(ing.product_id, feasible[0]) + sum(
            ctx.lots[lid].lot.quantity * prod.content for lid in rc.sec_suppliers.get((ing.product_id, feasible[0]), []))
        if have + EPS < ing.need:
            reasons.append(f"U7_SECONDARY_SHORT_{ing.product_id}")
    if reasons:
        return rc
    rc.days, rc.eligible = feasible, True
    return rc
