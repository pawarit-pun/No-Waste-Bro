"""PART 8 — แปลง Plan เป็น 2 อย่าง
  payload      = body ของ POST /api/v1/optimization-decisions -> บันทึกลงตาราง optimization_decisions (ให้ RAG ใช้ต่อ)
                 field ตามตาราง: assessment_id, action_type, action_quantity, discount_pct, new_recommended_price,
                 target_recipe_id, batch_count, target_partner_id, due_by, expected_profit_impact, decision_score,
                 alternatives (jsonb) + optimizer_version
  allocations  = ตัวแปรรายละเอียดต่อส่วนของ lot (weight_kg, share_pct, รายได้, ค่าใช้จ่าย ...) **ไม่เขียนลงตาราง**
                 ส่งต่อให้ส่วนอื่นใช้ (dashboard / RAG / รายงาน) ผูกกับ decision ด้วย decision_index -> decision_id

กติกา
  - 1 lot มีราคาเดียว: MARKDOWN ได้ 1 decision ต่อ lot (action_quantity = จำนวนที่คาดว่าขายได้ที่ราคานั้น ปัดลง)
  - ขายราคาปกติ (SELL_REGULAR) ไม่ต้องมี decision
  - ของที่วางขายแล้วคาดว่าเหลือ (END_OF_LIFE) = decision ของ partner นั้น due_by = เวลารับหลังหมดเวลาขาย
    action_quantity = จำนวนที่คาดว่าเหลือ (ปัดขึ้น) staff กำจัดตามจำนวนที่เหลือจริงตอนนั้น
    ไม่มี partner รับ -> DISCARD (ทิ้งเองในร้าน) ให้ผู้จัดการดู
    ถ้าเที่ยวนั้นเป็นวันถัดไปและ deferred_trip_cost_share < 1 = แผนชั่วคราว (provisional) ไม่มี decision รอบนี้
    lot ถูกคืน IDLE (pipeline.lots_to_release) ให้รอบสแกนวันถัดไปตัดสินใจใหม่ เช่น บริจาคขณะยังเข้าเกณฑ์
  - ครัว: 1 งาน (สูตร, วัน, lot หลัก) = 1 decision (batch_count ของงานนั้น server ใช้จองชั่วโมงครัวตอน POST /tasks)
    lot อื่นที่ DB จะตัดเป็นวัตถุดิบแบบ FEFO ไม่มี decision ของตัวเอง แต่มีใน allocations (covered_by_decision_index)
  - partner อื่นที่ไม่ใช่ DONATION ใช้ action_type ตาม config.action_mode
    (extended = ANIMAL_FEED / COMPOST / ANAEROBIC_DIGESTION / LANDFILL, current = DISCARD + target_partner_id)
  - decision_score = สัดส่วนต้นทุนที่กู้คืนได้ (0-1) = 1 + expected_profit_impact / ต้นทุนสินค้า
  - alternatives = ทางเลือกอื่นของหน่วยเดียวกันพร้อมกำไร/ขาดทุน + ทางที่ถูกตัดพร้อมรหัสเหตุผล (ให้ RAG อธิบาย "ทำไมไม่...")
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from ai_engine.optimizer.config import ACTION_BY_METHOD, PARTNER_TYPES
from ai_engine.optimizer.demand import expected_sold

ACTIONS_NOW = {"MARKDOWN", "KITCHEN_REPURPOSE", "DONATE", "DISCARD"}
# ตรงกับ PARTNER_ACTIONS ใน server/schemas/enums.py: action -> (partner_type ที่รับได้, key ใน product.disposal)
PARTNER_ACTIONS = {
    "DONATE": ({"DONATION", "FOOD_BANK", "CHARITY", "COMMUNITY", "TEMPLE"}, "DONATION"),
    "ANIMAL_FEED": ({"ANIMAL_FEED"}, "ANIMAL_FEED"),
    "COMPOST": ({"COMPOSTING"}, "COMPOSTING"),
    "ANAEROBIC_DIGESTION": ({"ANAEROBIC_DIGESTION"}, "ANAEROBIC_DIGESTION"),
    "LANDFILL": ({"LANDFILL"}, "LANDFILL"),
}


def _score(profit: float, cogs: float) -> float:
    return round(min(1.0, max(0.0, 1.0 + profit / cogs)), 3) if cogs > 0 else 0.0


def _alternatives(ctx, lc, units: int, chosen: str, amap: dict, price_options=()) -> list:
    cogs = units * lc.lot.unit_cost
    alts = []
    best = None
    for pid in lc.partner_ok:
        pc = ctx.partners[pid]
        kg = units * lc.weight_kg
        if chosen == f"PARTNER:{pid}" or kg > pc.cap_kg or kg < pc.min_kg:
            continue
        profit = (pc.partner.buyback - pc.handling) * kg - pc.trip_cost - cogs
        if best is None or profit > best[0]:
            best = (profit, pc.partner)
    if best:
        alts.append({"action_type": amap[best[1].partner_type], "disposal_method": best[1].partner_type,
                     "partner_id": best[1].partner_id, "expected_profit_impact": round(best[0], 2),
                     "note": "เรียก partner มารับเฉพาะส่วนนี้ 1 เที่ยว"})
    if chosen in ("KITCHEN",) or chosen.startswith("MARKDOWN"):
        best_md = None
        for t in lc.tiers:
            if t["discount_pct"] == 0 or chosen == f"MARKDOWN:{t['discount_pct']}":
                continue
            sold = expected_sold(t["segments"], units)
            profit = sold * t["price"] - t["lost_sales_cost"] - cogs
            if best_md is None or profit > best_md[0]:
                best_md = (profit, t)
        if best_md:
            t = best_md[1]
            alts.append({"action_type": "MARKDOWN", "discount_pct": t["discount_pct"],
                         "new_recommended_price": t["price"], "expected_profit_impact": round(best_md[0], 2),
                         "note": f"คาดว่าขายได้ {sold:.1f} จาก {units} หน่วย (P10/P50/P90 ของ forecaster) ที่เหลือทิ้ง"})
    alts.sort(key=lambda a: -a["expected_profit_impact"])
    alts = alts[:3]
    picked = next((o for o in price_options if o["chosen"]), None)
    others = [o for o in price_options if not o["chosen"] and o["discount_pct"] > 0]
    if others and not chosen.startswith("MARKDOWN"):
        best = max(others, key=lambda o: o["lot_net_profit_thb"])
        alts.append({"action_type": "MARKDOWN", "scope": "WHOLE_LOT", "discount_pct": best["discount_pct"],
                     "new_recommended_price": best["price"], "expected_sold": best["expected_sold"],
                     "lot_net_profit_thb": best["lot_net_profit_thb"],
                     "chosen_lot_net_profit_thb": picked["lot_net_profit_thb"] if picked else None,
                     "note": "ลดราคาทั้ง lot เทียบกับแผนที่เลือก (ยอดขายเพิ่มตาม lift ของ forecaster)"})
    rejected = [{"option": key, "rejected_because": reasons[:2]} for key, reasons in lc.excluded.items()
                if not key.startswith("MARKDOWN:") or not any(r.startswith("K3_NOT_FORECAST") for r in reasons)]
    reference = {"action_type": "DISCARD", "disposal_method": "COST_WRITE_OFF_REFERENCE", "feasible": False,
                 "expected_profit_impact": round(-cogs, 2),
                 "note": "ค่าอ้างอิงเท่านั้น: ต้นทุนสินค้าที่เสียไปถ้าทิ้งหมด ยังไม่รวมค่ากำจัดที่ต้องจ่าย partner"}
    return alts + rejected[:5] + [reference]


def build_decisions(plan: dict, ctx) -> dict:
    cfg = ctx.cfg
    amap = ACTION_BY_METHOD[cfg.action_mode]
    decisions, allocations = [], []
    jobs = {j["job_id"]: j for j in plan["kitchen_jobs"]}
    job_decision = {}

    def add(lo, p, action_type, impact, cogs, alts, **extra):
        d = {"assessment_id": lo["assessment_id"], "action_type": action_type, "action_quantity": int(p["units"]),
             "expected_profit_impact": round(impact, 2), "decision_score": _score(impact, cogs), "alternatives": alts}
        d.update({k: v for k, v in extra.items() if v is not None})
        decisions.append(d)
        return len(decisions) - 1

    order = {"KITCHEN": 0, "MARKDOWN": 1, **{t: 2 for t in PARTNER_TYPES}, "UNRESOLVED": 3}
    for lo in plan["lots"]:
        lc = ctx.lots[lo["lot_id"]]
        for p in sorted(lo["portions"], key=lambda p: order.get(p["method"], 9)):
            m, det, idx, covered, action = p["method"], p["details"], None, None, None
            if p["units"] <= 0 and m != "KITCHEN":
                pass                                          # portion 0 หน่วย (ปัดเศษ) ไม่มี decision
            elif det.get("provisional"):
                pass                                          # กำจัดวันถัดไปแบบชั่วคราว: lot ถูกคืน IDLE ให้สแกน/ตัดสินใจใหม่
            elif m == "MARKDOWN":
                action = amap["MARKDOWN"]
                idx = add(lo, p, action, p["net_profit_thb"], p["cogs_thb"],
                          _alternatives(ctx, lc, p["units"], f"MARKDOWN:{det['discount_pct']}", amap),
                          discount_pct=det["discount_pct"], new_recommended_price=det["unit_price"])
            elif m == "KITCHEN":
                j = jobs[det["job_id"]]
                action = amap["KITCHEN"]
                idx = add(lo, p, action, j["net_profit_thb"], j["cogs_thb"],
                          _alternatives(ctx, lc, p["units"], "KITCHEN", amap, lo["explain"]["price_options"]),
                          target_recipe_id=j["recipe_id"], batch_count=j["batches"], due_by=j["due_by"])
                job_decision[j["job_id"]] = idx
            elif m in PARTNER_TYPES:
                action = amap[m]
                idx = add(lo, p, action, p["net_profit_thb"], p["cogs_thb"],
                          _alternatives(ctx, lc, p["units"], f"PARTNER:{det['partner_id']}", amap, lo["explain"]["price_options"]),
                          target_partner_id=det["partner_id"], due_by=det["pickup_at"] if cfg.partner_due_by else None)
                if det.get("timing") == "END_OF_LIFE":
                    decisions[idx]["alternatives"].insert(0, {
                        "timing": "END_OF_LIFE", "expected_units": det["expected_units"],
                        "note": "กำจัดของที่ขายไม่หมดหลังหมดเวลาขาย จำนวนจริง = ที่เหลือบนชั้นตอนนั้น"})
            elif m == "UNRESOLVED":
                action = amap["UNRESOLVED"]
                idx = add(lo, p, action, p["net_profit_thb"], p["cogs_thb"],
                          _alternatives(ctx, lc, p["units"], "UNRESOLVED", amap, lo["explain"]["price_options"]))
            allocations.append({
                "decision_index": idx, "covered_by_job": det.get("job_id") if m == "KITCHEN_INGREDIENT" else None,
                "lot_id": lo["lot_id"], "assessment_id": lo["assessment_id"], "product_id": lo["product_id"],
                "name": lo["name"], "method": m, "action_type": action, "units": p["units"],
                "share_pct": p["share_pct"], "weight_kg": p["weight_kg"], "revenue_thb": p["revenue_thb"],
                "cost_thb": p["cost_thb"], "cogs_thb": p["cogs_thb"], "net_profit_thb": p["net_profit_thb"],
                "details": det,
            })
    for a in allocations:                                   # วัตถุดิบที่ DB ตัดแบบ FEFO -> ผูกกับ decision ของงานครัว
        if a["covered_by_job"]:
            a["covered_by_decision_index"] = job_decision.get(a["covered_by_job"])
    return {"payload": {"optimizer_version": cfg.model_version, "decisions": decisions}, "allocations": allocations}


def validate_payload(payload: dict, ctx) -> list:
    """ตรวจแบบเดียวกับ server (schemas/decision.py + services/decisions.py) ก่อนยิงจริง คืนรายการ error (ว่าง = ผ่าน)"""
    inp, errs = ctx.inputs, []
    by_assessment = {lot.assessment_id: lot for lot in inp.lots}
    qty = defaultdict(int)
    for i, d in enumerate(payload["decisions"]):
        def bad(msg, i=i):
            errs.append(f"decisions[{i}]: {msg}")
        lot = by_assessment.get(d["assessment_id"])
        if lot is None:
            bad("assessment_id ไม่อยู่ในรอบนี้")
            continue
        product = inp.products[lot.product_id]
        at = d["action_type"]
        if ctx.cfg.action_mode == "current" and at not in ACTIONS_NOW:
            bad(f"action_type {at} ยังไม่มีใน enum ของ DB")
        if not isinstance(d["action_quantity"], int) or d["action_quantity"] <= 0:
            bad("action_quantity ต้องเป็นจำนวนเต็ม > 0")
        qty[lot.lot_id] += d["action_quantity"]
        if qty[lot.lot_id] > lot.quantity:
            bad(f"รวม action_quantity ของ {lot.lot_id} เกิน current_quantity ({lot.quantity})")
        is_md, is_k = at == "MARKDOWN", at == "KITCHEN_REPURPOSE"
        if is_md != ("discount_pct" in d):
            bad("discount_pct ใช้ได้และต้องมีเฉพาะ MARKDOWN")
        if not is_md and "new_recommended_price" in d:
            bad("new_recommended_price ใช้ได้เฉพาะ MARKDOWN")
        if not is_k and "batch_count" in d:
            bad("batch_count ใช้ได้เฉพาะ KITCHEN_REPURPOSE")
        if is_md:
            if not 0 < d["discount_pct"] < 100:
                bad("discount_pct ต้องอยู่ระหว่าง 0-100")
            if not product.allow_markdown:
                bad("สินค้าไม่อนุญาตลดราคา")
            if product.min_price is not None and d["new_recommended_price"] < product.min_price:
                bad(f"ราคาใหม่ {d['new_recommended_price']} ต่ำกว่า min_allowed_price {product.min_price}")
        if is_k:
            recipe = inp.recipes.get(d.get("target_recipe_id"))
            if recipe is None or not recipe.active:
                bad("สูตรไม่พบหรือไม่ active")
            elif lot.product_id not in {x.product_id for x in recipe.ingredients}:
                bad(f"{lot.product_id} ไม่ใช่วัตถุดิบของ {recipe.recipe_id}")
            if not d.get("batch_count") or not d.get("due_by"):
                bad("KITCHEN_REPURPOSE ต้องมี batch_count และ due_by")
            if not product.allow_kitchen:
                bad("สินค้าไม่อนุญาตเข้าครัว")
        if at in PARTNER_ACTIONS:
            partner_types, flag = PARTNER_ACTIONS[at]
            partner = inp.partners.get(d.get("target_partner_id"))
            if partner is None or not partner.active:
                bad("partner ไม่พบหรือไม่ active")
            else:
                if not product.disposal.get(flag):
                    bad(f"สินค้าไม่อนุญาต {at}")
                if partner.partner_type not in partner_types:
                    bad(f"partner เป็นประเภท {partner.partner_type} ใช้กับ {at} ไม่ได้")
                if product.category not in partner.categories:
                    bad(f"partner ไม่รับหมวด {product.category}")
                on = date.fromisoformat(str(d["due_by"])[:10]) if d.get("due_by") else inp.reference_date
                left = (lot.expiration_date - on).days         # อายุคงเหลือ ณ วันรับ (ตรงกับ rules P4)
                if partner.min_days and left < partner.min_days:
                    bad(f"lot เหลืออายุ {left} วัน partner ต้องการ >= {partner.min_days}")
    return errs