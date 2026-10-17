"""PART 7 — ตรวจแผนซ้ำด้วยกฎจากข้อมูลดิบ (ไม่เชื่อ solver) ก่อนส่งออก

solver ถูกสร้างให้ทำตามกฎอยู่แล้ว แต่ชั้นนี้คือตาข่ายนิรภัย: ถ้าแผนหลุดกฎข้อใด คืน violation
(รหัส H* = กฎเข้ม) แล้ว pipeline จะหยุดไม่ส่ง decision
  H1 จำนวนไม่สมดุล/ติดลบ        H2 ใช้วิธีที่สินค้าไม่อนุญาต/หมวดไม่รับ
  H3 markdown (ราคา/เพดานขาย/หมดอายุ/มีหลาย tier)   H4 partner (วัน-เวลารับ/อายุ/น้ำหนักขั้นต่ำ-สูงสุด)
  H5 ครัว (ชั่วโมง/วัตถุดิบ/ทันก่อนหมดอายุ/เพดานเมนู)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from ai_engine.optimizer.rules import (EPS, expiry_dt, is_expired, next_pickup, partner_reasons,tier_price)


def _v(rule: str, lot_id, detail: str) -> dict:
    return {"rule": rule, "lot_id": lot_id, "detail": detail}


def validate_plan(plan: dict, ctx) -> list:
    inp, cfg, now = ctx.inputs, ctx.cfg, ctx.now
    out: list = []
    kg_by_partner: dict = defaultdict(float)

    for lo in plan["lots"]:
        lid = lo["lot_id"]
        lc = ctx.lots[lid]
        lot, product = lc.lot, lc.product
        units = [p["units"] for p in lo["portions"]]
        if sum(units) != lot.quantity or any(u < 0 for u in units):
            out.append(_v("H1_MASS_BALANCE", lid, f"{sum(units)} หน่วยที่จัดสรร vs {lot.quantity} ในสต็อก"))
        if sum(1 for p in lo["portions"] if p["method"] in ("SELL_REGULAR", "MARKDOWN")) > 1:
            out.append(_v("H3_MULTIPLE_PRICE_TIERS", lid, "1 lot ต้องมีราคาขายเดียว"))

        for p in lo["portions"]:
            m, u, d = p["method"], p["units"], p["details"]
            if m in ("SELL_REGULAR", "MARKDOWN"):
                if is_expired(lot, now, cfg):
                    out.append(_v("H3_EXPIRED_ON_SHELF", lid, "ขายสินค้าที่หมดอายุแล้ว"))
                pct = d["discount_pct"]
                price = tier_price(lot.price, pct)
                if m == "MARKDOWN":
                    if not product.allow_markdown:
                        out.append(_v("H2_MARKDOWN_NOT_ALLOWED", lid, product.product_id))
                    if product.min_price is not None and price < product.min_price - EPS:
                        out.append(_v("H3_BELOW_MIN_PRICE", lid, f"{price} < {product.min_price}"))
                    if not 0 < pct < 100:
                        out.append(_v("H3_BAD_DISCOUNT", lid, str(pct)))
                if u > d["demand_cap"]:
                    out.append(_v("H3_OVER_DEMAND_CAP", lid, f"{u} > {d['demand_cap']}"))
            elif m == "KITCHEN":
                if not product.allow_kitchen:
                    out.append(_v("H2_KITCHEN_NOT_ALLOWED", lid, product.product_id))
                if is_expired(lot, now, cfg):
                    out.append(_v("H5_EXPIRED_TO_KITCHEN", lid, "ส่งของหมดอายุเข้าครัว"))
            elif m == "UNRESOLVED":
                continue
            else:  # partner
                pid = d["partner_id"]
                pc = ctx.partners[pid]
                pickup = next_pickup(pc.partner, now, cfg)
                if pickup is None or d["pickup_at"] != pickup.isoformat():
                    out.append(_v("H4_PICKUP_SLOT_MISMATCH", lid, f"{pid} {d['pickup_at']} vs {pickup}"))
                for reason in partner_reasons(lot, product, pc.partner, pickup, pc.cap_kg, cfg, now):
                    prefix = "H2_" if reason[:2] in ("P1", "P2") else "H4_"
                    out.append(_v(prefix + reason, lid, f"{pid}: {reason}"))
                kg_by_partner[pid] += p["weight_kg"]

    for pid, kg in kg_by_partner.items():
        pc = ctx.partners[pid]
        if kg > pc.cap_kg + 1e-3:
            out.append(_v("H4_PARTNER_CAPACITY", None, f"{pid}: {kg:.2f} kg > {pc.cap_kg:.2f} kg"))
        if kg < pc.partner.min_kg - 1e-3:
            out.append(_v("H4_BELOW_MIN_KG", None, f"{pid}: {kg:.2f} kg < min_kg_per_pickup {pc.partner.min_kg:g}"))

    # ---- ครัว ----
    used_hours: dict = defaultdict(float)
    out_units: dict = defaultdict(float)
    shortfall: dict = defaultdict(lambda: defaultdict(float))   # product -> day -> g/ml ที่ต้องมาจากสต็อกไม่เสี่ยง
    for j in plan["kitchen_jobs"]:
        rc = ctx.recipes[j["recipe_id"]]
        r, day = rc.recipe, date.fromisoformat(j["date"])
        if not r.active:
            out.append(_v("H5_RECIPE_INACTIVE", None, r.recipe_id))
        used_hours[(r.department_id, day)] += j["batches"] * rc.hours_per_batch
        out_units[r.recipe_id] += j["batches"] * r.output_qty
        due = datetime.fromisoformat(j["due_by"])
        for ing in rc.primary:
            have = sum(u for lid, u in j["primary_lots"].items() if ctx.lots[lid].product.product_id == ing.product_id)
            content = inp.products[ing.product_id].content
            if have * content + EPS < ing.need * j["batches"]:
                out.append(_v("H5_PRIMARY_SHORT", None, f"{j['job_id']} {ing.product_id}"))
        for lid in list(j["primary_lots"]) + list(j["secondary_lots"]):
            if expiry_dt(ctx.lots[lid].lot, cfg) < due:
                out.append(_v("H5_NOT_IN_TIME", lid, f"{j['job_id']} due {due.isoformat()} หลังหมดอายุ"))
        for ing in rc.secondary:
            content = inp.products[ing.product_id].content
            have = sum(u for lid, u in j["secondary_lots"].items() if ctx.lots[lid].product.product_id == ing.product_id)
            shortfall[ing.product_id][day] += max(0.0, ing.need * j["batches"] - have * content)
    for key, hrs in used_hours.items():
        if hrs > ctx.hours[key].hours + 1e-6:
            out.append(_v("H5_KITCHEN_HOURS", None, f"{key[0]} {key[1]}: {hrs:.2f} > {ctx.hours[key].hours:.2f} ชม."))
    for rid, units in out_units.items():
        if units > ctx.recipes[rid].demand_units + 1e-6:
            out.append(_v("H5_OVER_MENU_DEMAND", None, f"{rid}: {units} > {ctx.recipes[rid].demand_units}"))
    for pid, per_day in shortfall.items():                       # รวมความต้องการทุกงานเทียบ ingredient_stock
        for d in sorted(per_day):
            need = sum(v for d2, v in per_day.items() if d2 >= d)
            if need > ctx.nr_stock(pid, d) + 1e-6:
                out.append(_v("H5_INGREDIENT_STOCK", None, f"{pid} ต้องการ {need:.0f} > สต็อก {ctx.nr_stock(pid, d):.0f} (จากวัน {d})"))
    return out
