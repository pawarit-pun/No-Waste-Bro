"""PART 7 — ตรวจแผนซ้ำด้วยกฎจากข้อมูลดิบ (ไม่เชื่อ solver) ก่อนส่ง ถ้าหลุดกฎข้อไหน pipeline หยุด ไม่ส่ง decision

  H1 จำนวนไม่สมดุล / ติดลบ                    H2 ใช้วิธีที่สินค้าไม่อนุญาต / partner ไม่รับหมวด
  H3 markdown: หลายราคาใน lot เดียว, ต่ำกว่า min_allowed_price, ขายเกินยอดที่คาด, ขายของหมดอายุ
  H4 partner: วัน-เวลารับไม่ตรงกฎ, อายุคงเหลือ, น้ำหนักต่ำกว่าขั้นต่ำ / เกินความจุต่อเที่ยว (partner, วัน),
              ของ end-of-life ต้องรับหลังหมดเวลาขาย
  H5 ครัว: ชั่วโมงเกิน, lot หลักไม่พอ batch, lot หมดอายุก่อนงานเสร็จ, ผลิตเกินความต้องการเมนู
  H6 FEFO: จำลองการตัดสต็อกของ DB (หมดอายุก่อนตัดก่อน) แล้วต้องตรงกับแผน และสต็อกต้องพอ
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime

from ai_engine.optimizer.context import trip_min_kg
from ai_engine.optimizer.rules import EPS, expiry_dt, is_expired, kitchen_due, partner_reasons, sell_end, tier_price


def _v(rule: str, lot_id, detail: str) -> dict:
    return {"rule": rule, "lot_id": lot_id, "detail": detail}


def validate_plan(plan: dict, ctx) -> list:
    inp, cfg, now = ctx.inputs, ctx.cfg, ctx.now
    out, kg_by_trip = [], defaultdict(float)

    for lo in plan["lots"]:
        lid = lo["lot_id"]
        lc = ctx.lots[lid]
        lot, product = lc.lot, lc.product
        units = [p["units"] for p in lo["portions"]]
        if sum(units) != lot.quantity or any(u < 0 for u in units):
            out.append(_v("H1_MASS_BALANCE", lid, f"จัดสรร {sum(units)} หน่วย แต่มี {lot.quantity}"))
        if sum(1 for p in lo["portions"] if p["method"] in ("SELL_REGULAR", "MARKDOWN")) > 1:
            out.append(_v("H3_MULTIPLE_PRICES", lid, "1 lot ต้องมีราคาเดียว"))
        for p in lo["portions"]:
            m, d = p["method"], p["details"]
            if m in ("SELL_REGULAR", "MARKDOWN"):
                if is_expired(lot, now, cfg):
                    out.append(_v("H3_EXPIRED_ON_SHELF", lid, "ขายของหมดอายุ"))
                if p["units"] > d["shelf_units"] or d["expected_sold"] > d["expected_sold_whole_lot"] + 0.01:
                    out.append(_v("H3_OVER_DEMAND", lid, f"ขาย {p['units']} / คาด {d['expected_sold']} จากชั้น "
                                                        f"{d['shelf_units']} (ทั้ง lot คาด {d['expected_sold_whole_lot']})"))
                if m == "MARKDOWN":
                    pct, price = d["discount_pct"], tier_price(lot.price, d["discount_pct"])
                    if not product.allow_markdown:
                        out.append(_v("H2_MARKDOWN_NOT_ALLOWED", lid, product.product_id))
                    if not 0 < pct < 100 or pct not in cfg.allowed_discounts:
                        out.append(_v("H3_BAD_DISCOUNT", lid, str(pct)))
                    if product.min_price is not None and price < product.min_price - EPS:
                        out.append(_v("H3_BELOW_MIN_PRICE", lid, f"{price} < {product.min_price}"))
            elif m in ("KITCHEN", "KITCHEN_INGREDIENT"):
                if is_expired(lot, now, cfg):
                    out.append(_v("H5_EXPIRED_TO_KITCHEN", lid, d["job_id"]))
                if m == "KITCHEN" and not product.allow_kitchen:
                    out.append(_v("H2_KITCHEN_NOT_ALLOWED", lid, product.product_id))
            elif m != "UNRESOLVED":
                pid = d["partner_id"]
                pc = ctx.partners[pid]
                eol = d.get("timing") == "END_OF_LIFE"
                base = lc.eol.get(pid) if eol else pc.pickup
                pickup = ctx.slots.get((pid, base.date())) if base else None
                if pickup is None or d["pickup_at"] != pickup.isoformat():
                    out.append(_v("H4_PICKUP_SLOT", lid, f"{pid} {d['pickup_at']} vs {pickup}"))
                    continue
                if eol and pickup < sell_end(lot, cfg):
                    out.append(_v("H4_EOL_BEFORE_SELL_END", lid, f"{pid} รับ {pickup} ก่อนหมดเวลาขาย"))
                for reason in partner_reasons(lot, product, pc.partner, pickup, pc.cap_kg, cfg, now):
                    out.append(_v(("H2_" if reason[:2] in ("P1", "P2") else "H4_") + reason, lid, pid))
                kg_by_trip[(pid, pickup.date())] += p["weight_kg"]
    for (pid, day), kg in kg_by_trip.items():
        pc = ctx.partners[pid]
        if kg > pc.cap_kg + 1e-3:
            out.append(_v("H4_PARTNER_CAPACITY", None, f"{pid}@{day}: {kg:.2f} > {pc.cap_kg:.2f} kg"))
        min_kg = trip_min_kg(ctx, pid, day)
        if kg < min_kg - 1e-2:
            out.append(_v("H4_BELOW_MIN_KG", None, f"{pid}@{day}: {kg:.2f} < {min_kg:g} kg"))

    out += _validate_kitchen(plan, ctx)
    return out


def _validate_kitchen(plan: dict, ctx) -> list:
    inp, cfg, out = ctx.inputs, ctx.cfg, []
    jobs = {j.job_id: j for j in ctx.jobs}
    hours, sold = defaultdict(float), defaultdict(lambda: defaultdict(float))
    anchor_units = defaultdict(int)
    for pj in plan["kitchen_jobs"]:
        j = jobs[pj["job_id"]]
        r = inp.recipes[j.recipe_id]
        lot = ctx.lots[j.anchor_lot_id].lot
        n, k = pj["batches"], pj["anchor_units"]
        if not r.active:
            out.append(_v("H5_RECIPE_INACTIVE", None, r.recipe_id))
        hours[(r.department_id, j.day)] += n * r.hours_per_batch
        sold[j.recipe_id][j.day] += pj["expected_sold_units"]
        if k != math.ceil(j.anchor_need * n / j.anchor_content - 1e-9) or k > lot.quantity:
            out.append(_v("H5_ANCHOR_UNITS", lot.lot_id, f"{pj['job_id']}: {k} หน่วย สำหรับ {n} batch"))
        due_by = datetime.fromisoformat(pj["due_by"])
        if expiry_dt(lot.expiration_date, cfg) < due_by:
            out.append(_v("H5_NOT_IN_TIME", lot.lot_id, f"{pj['job_id']} เสร็จหลัง lot หมดอายุ"))
        if due_by > kitchen_due(j.day, cfg) or datetime.fromisoformat(pj["start_at"]) < ctx.now:
            out.append(_v("H5_OUTSIDE_SHIFT", lot.lot_id, f"{pj['job_id']} เริ่ม {pj['start_at']} เสร็จ {pj['due_by']}"))
        if pj["expected_sold_units"] > pj["output_units"] + 0.011:
            out.append(_v("H5_SOLD_OVER_OUTPUT", lot.lot_id, pj["job_id"]))
        anchor_units[lot.lot_id] += k
    for key, hrs in hours.items():
        if hrs > ctx.hours[key].hours + 1e-6:
            out.append(_v("H5_KITCHEN_HOURS", None, f"{key[0]} {key[1]}: {hrs:.2f} > {ctx.hours[key].hours:.2f} ชม."))
    for rid, per_day in sold.items():
        for d in per_day:
            later = sum(v for d2, v in per_day.items() if d2 >= d)
            if later > ctx.recipe_days[(rid, d)].cap_units + 0.011:   # expected_sold_units ปัด 2 ตำแหน่ง
                out.append(_v("H5_OVER_MENU_DEMAND", None, f"{rid} ตั้งแต่ {d}: {later:.2f} > {ctx.recipe_days[(rid, d)].cap_units:.2f}"))

    # ---- H6: จำลองการตัดวัตถุดิบตอน complete (FEFO) แล้วเทียบกับแผน
    simulated = fefo_simulation(plan, ctx, anchor_units)
    planned = defaultdict(int)
    for lo in plan["lots"]:
        for p in lo["portions"]:
            if p["method"] == "KITCHEN_INGREDIENT":
                planned[lo["lot_id"]] += p["units"]
    for lid in set(planned) | {l for l in simulated["units"] if l in ctx.lots}:
        if planned.get(lid, 0) != simulated["units"].get(lid, 0):
            out.append(_v("H6_FEFO_MISMATCH", lid, f"แผน {planned.get(lid, 0)} หน่วย, DB จะตัด {simulated['units'].get(lid, 0)} หน่วย"))
    for short in simulated["short"]:
        out.append(_v("H6_STOCK_SHORT", None, short))
    return out


def fefo_simulation(plan: dict, ctx, anchor_units=None) -> dict:
    """ทำแบบเดียวกับ DB: แต่ละวัน วัตถุดิบตัวอื่นของทุกงานถูกตัดจาก lot ที่ยังไม่หมดอายุ เรียงหมดอายุก่อน"""
    inp = ctx.inputs
    if anchor_units is None:
        anchor_units = defaultdict(int)
        for pj in plan["kitchen_jobs"]:
            anchor_units[pj["anchor_lot_id"]] += pj["anchor_units"]
    jobs = {j.job_id: j for j in ctx.jobs}
    need = defaultdict(lambda: defaultdict(float))
    for pj in plan["kitchen_jobs"]:
        j = jobs[pj["job_id"]]
        for pid, q, _ in j.others:
            need[pid][j.day] += q * pj["batches"]
    consumed, short = defaultdict(float), []
    for pid, per_day in need.items():
        rows = ctx.fefo.get(pid, [])
        left = {fl.lot_id: (fl.quantity - anchor_units.get(fl.lot_id, 0)) * fl.content for fl in rows}
        for d in sorted(per_day):
            want = per_day[d]
            for fl in rows:
                if fl.expiration_date < d or want <= 1e-9:
                    continue
                take = min(want, left[fl.lot_id])
                left[fl.lot_id] -= take
                consumed[fl.lot_id] += take
                want -= take
            if want > 1e-6:
                short.append(f"{pid} {d}: ขาด {want:.0f}")
    content = {fl.lot_id: fl.content for rows in ctx.fefo.values() for fl in rows}
    units = {lid: math.ceil(c / content[lid] - 1e-9) for lid, c in consumed.items() if c > 1e-9}
    return {"content": dict(consumed), "units": units, "short": short}