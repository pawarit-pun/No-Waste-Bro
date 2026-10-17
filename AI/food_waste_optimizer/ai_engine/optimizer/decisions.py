"""PART 8 — แปลง Plan เป็น payload ของ POST /api/v1/optimization-decisions (ตรงกับ table optimization_decisions)

field ที่ส่ง: assessment_id, action_type, action_quantity, discount_pct, new_recommended_price,
              target_recipe_id, batch_count, target_partner_id, due_by, expected_profit_impact,
              decision_score, alternatives(jsonb)   (+ optimizer_version ระดับ batch)

กติกาการแปลง
  • 1 lot มี markdown ได้ 1 ระดับ -> MARKDOWN decision เดียว (จำนวน = หน่วยที่คาดว่าขายได้ที่ราคานั้น)
  • ส่งครัว: 1 งาน (สูตร×วัน) = 1 decision ผูกกับ "lot หลัก" (anchor) ถือ batch_count ทั้งหมด
    เพราะ server จองชั่วโมงครัวตาม batch_count ของทุก task — ถ้าแตกเป็นหลาย lot จะจองซ้ำ (ดู README ปัญหาที่ 4)
  • partner ที่ไม่ใช่ DONATION: ใช้ action_type ตาม config.action_mode (ดู config.ACTION_BY_METHOD)
  • ส่วนที่ขายราคาปกติ (SELL_REGULAR) ไม่ส่ง เพราะไม่ต้องมี action
  • decision_score = สัดส่วนต้นทุนที่ "กู้คืนได้" เทียบกับทิ้งทั้งหมด (0–1) ไว้เรียงลำดับ/แสดง dashboard
  • alternatives[0] = รายละเอียดทางที่เลือก (role=chosen) ที่เหลือคือทางอื่นพร้อมกำไร/ขาดทุน (role=alternative)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from ai_engine.optimizer.config import ACTION_BY_METHOD

SKIP_METHODS = ("SELL_REGULAR", "KITCHEN")


def _score(profit: float, cogs: float) -> float:
    return round(min(1.0, max(0.0, 1.0 + profit / cogs)), 3) if cogs > 0 else 0.0


def _alternatives(ctx, lc, units: int, chosen_key: str, amap: dict, with_markdown: bool = True) -> list:
    """ทางอื่นสำหรับ "หน่วยเดียวกันนี้" (ประเมินแยก ไม่แบ่งค่าเที่ยวกับ lot อื่น) เรียงกำไรมากไปน้อย"""
    cogs = units * lc.lot.unit_cost
    alts = [{"role": "alternative", "action_type": "DISCARD", "disposal_method": "SELF_DISCARD",
             "expected_profit_impact": round(-cogs, 2), "note": "ทิ้งเอง (ไม่รวมค่าขนย้าย/กำจัด)"}]
    best = None
    for pid in lc.partner_ok:
        pc = ctx.partners[pid]
        kg = units * lc.weight_kg
        if kg > pc.cap_kg or kg < pc.partner.min_kg or chosen_key == f"PARTNER:{pid}":
            continue
        profit = (pc.partner.buyback - pc.handling) * kg - (0.0 if pc.sunk else pc.trip_cost) - cogs
        if best is None or profit > best[0]:
            best = (profit, pc)
    if best:
        p = best[1].partner
        alts.append({"role": "alternative", "action_type": amap[p.partner_type], "disposal_method": p.partner_type,
                     "partner_id": p.partner_id, "expected_profit_impact": round(best[0], 2),
                     "note": "ส่งเฉพาะหน่วยนี้เที่ยวเดียว (ไม่แบ่งค่าเที่ยว)"})
    best_md = None
    for t in (lc.tiers if with_markdown else []):
        if t["discount_pct"] == 0 or chosen_key == f"MARKDOWN:{t['discount_pct']}":
            continue
        profit = min(units, t["cap"]) * t["price"] - cogs
        if best_md is None or profit > best_md[0]:
            best_md = (profit, t)
    if best_md:
        t = best_md[1]
        alts.append({"role": "alternative", "action_type": "MARKDOWN", "discount_pct": t["discount_pct"],
                     "new_recommended_price": t["price"], "expected_profit_impact": round(best_md[0], 2),
                     "note": f"ขายได้ไม่เกิน {t['cap']} หน่วย ส่วนเหลือทิ้ง"})
    return sorted(alts, key=lambda a: -a["expected_profit_impact"])[:3]


def build_decisions(plan: dict, ctx) -> dict:
    cfg = ctx.cfg
    amap = ACTION_BY_METHOD[cfg.action_mode]
    decisions: list = []

    def finish(lo, action_type, units, profit, cogs, chosen, alts, **extra) -> None:
        d = {"assessment_id": lo["assessment_id"], "action_type": action_type, "action_quantity": int(units),
             "expected_profit_impact": round(profit, 2), "decision_score": _score(profit, cogs),
             "alternatives": [{"role": "chosen", **chosen}] + alts}
        d.update({k: v for k, v in extra.items() if v is not None})
        decisions.append(d)

    for lo in plan["lots"]:
        lc = ctx.lots[lo["lot_id"]]
        for p in lo["portions"]:
            m, det = p["method"], p["details"]
            if m in SKIP_METHODS:
                continue
            chosen = {"disposal_method": m, "share_pct": p["share_pct"], "weight_kg": p["weight_kg"],
                      "revenue_thb": p["revenue_thb"], "cost_thb": p["cost_thb"], "cogs_thb": p["cogs_thb"],
                      "net_profit_thb": p["net_profit_thb"], "details": det}
            if m == "MARKDOWN":
                key = f"MARKDOWN:{det['discount_pct']}"
                finish(lo, amap["MARKDOWN"], p["units"], p["net_profit_thb"], p["cogs_thb"], chosen,
                       _alternatives(ctx, lc, p["units"], key, amap),
                       discount_pct=det["discount_pct"], new_recommended_price=det["unit_price"])
            elif m == "UNRESOLVED":
                finish(lo, amap["UNRESOLVED"], p["units"], p["net_profit_thb"], p["cogs_thb"], chosen,
                       _alternatives(ctx, lc, p["units"], "", amap, with_markdown=False))
            else:  # partner
                pid = det["partner_id"]
                finish(lo, amap[m], p["units"], p["net_profit_thb"], p["cogs_thb"], chosen,
                       _alternatives(ctx, lc, p["units"], f"PARTNER:{pid}", amap, with_markdown=False),
                       target_partner_id=pid, due_by=det["pickup_at"] if cfg.partner_due_by else None)

    lots_by_id = {lo["lot_id"]: lo for lo in plan["lots"]}
    for j in plan["kitchen_jobs"]:
        lo = lots_by_id[j["anchor_lot_id"]]
        lc = ctx.lots[j["anchor_lot_id"]]
        units = j["primary_lots"][j["anchor_lot_id"]]
        chosen = {"disposal_method": "KITCHEN", "job_id": j["job_id"], "recipe_name": j["name"],
                  "department_id": j["department_id"], "batches": j["batches"], "hours": j["hours"],
                  "output_units": j["output_units"], "revenue_thb": j["revenue_thb"],
                  "utility_cost_thb": j["utility_cost_thb"], "cost_primary_thb": j["cost_primary_thb"],
                  "net_profit_thb": j["net_profit_thb"], "primary_lots": j["primary_lots"],
                  "secondary_lots": j["secondary_lots"],
                  "note": "งานนี้ใช้วัตถุดิบจากหลาย lot ได้ ส่ง 1 decision ที่ lot หลักเพื่อไม่ให้จองชั่วโมงครัวซ้ำ"}
        finish(lo, amap["KITCHEN"], units, j["net_profit_thb"], j["cost_primary_thb"], chosen,
               _alternatives(ctx, lc, units, "KITCHEN", amap),
               target_recipe_id=j["recipe_id"], batch_count=j["batches"], due_by=j["due_by"])
    return {"optimizer_version": cfg.model_version, "decisions": decisions}


def validate_payload(payload: dict, ctx) -> list:
    """จำลองการตรวจของ server (services/decisions.py + schemas/decision.py) ก่อนยิงจริง
    คืนรายการข้อความ error (ว่าง = server ควรรับได้)"""
    inp, errs = ctx.inputs, []
    by_assessment = {lot.assessment_id: lot for lot in inp.lots}
    qty: dict = defaultdict(int)
    for i, d in enumerate(payload["decisions"]):
        def bad(msg, i=i):
            errs.append(f"decisions[{i}]: {msg}")
        lot = by_assessment.get(d["assessment_id"])
        if lot is None:
            bad("assessment_id ไม่อยู่ในรอบนี้")
            continue
        product = inp.products[lot.product_id]
        at = d["action_type"]
        qty[lot.lot_id] += d["action_quantity"]
        if qty[lot.lot_id] > lot.quantity:
            bad(f"รวม action_quantity ของ {lot.lot_id} เกิน current_quantity ({lot.quantity})")
        if d["action_quantity"] <= 0:
            bad("action_quantity ต้อง > 0")
        is_md = at == "MARKDOWN"
        if is_md != ("discount_pct" in d):
            bad("discount_pct บังคับเฉพาะ MARKDOWN")
        if not is_md and "new_recommended_price" in d:
            bad("new_recommended_price ใช้ได้เฉพาะ MARKDOWN")
        if at == "KITCHEN_REPURPOSE":
            recipe = inp.recipes.get(d.get("target_recipe_id"))
            if recipe is None or not recipe.active:
                bad("สูตรไม่พบ/ไม่ active")
            elif lot.product_id not in {x.product_id for x in recipe.ingredients}:
                bad(f"{lot.product_id} ไม่ใช่วัตถุดิบของ {recipe.recipe_id}")
            if not (d.get("batch_count") or 0) > 0 or not d.get("due_by"):
                bad("KITCHEN_REPURPOSE ต้องมี batch_count > 0 และ due_by")
            if not product.allow_kitchen:
                bad("สินค้าไม่อนุญาต kitchen repurposing")
        elif "batch_count" in d:
            bad("batch_count ใช้ได้เฉพาะ KITCHEN_REPURPOSE")
        if is_md:
            if not product.allow_markdown:
                bad("สินค้าไม่อนุญาต markdown")
            if product.min_price is not None and d["new_recommended_price"] < product.min_price - 1e-9:
                bad(f"ราคาใหม่ {d['new_recommended_price']} ต่ำกว่า min_allowed_price {product.min_price}")
        if at == "DONATE":
            partner = inp.partners.get(d.get("target_partner_id"))
            if partner is None or not partner.active:
                bad("partner ไม่พบ/ไม่ active")
            else:
                if not product.disposal.get("DONATION"):
                    bad("สินค้าไม่อนุญาต donation")
                if product.category not in partner.categories:
                    bad(f"partner ไม่รับหมวด {product.category}")
                left = (lot.expiration_date - inp.reference_date).days
                if left < partner.min_days:
                    bad(f"lot เหลืออายุ {left} วัน partner ต้องการ ≥ {partner.min_days}")
        if at not in ("MARKDOWN", "KITCHEN_REPURPOSE", "DONATE", "DISCARD") and ctx.cfg.action_mode == "current":
            bad(f"action_type {at} ยังไม่มีใน enum ปัจจุบัน")
    return errs
