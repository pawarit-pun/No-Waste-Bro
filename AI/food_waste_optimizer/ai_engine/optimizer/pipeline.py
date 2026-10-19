"""PART 10 — ฟังก์ชันครอบ (wrapper) ที่คนอื่นเรียกใช้ได้ทันที

  run_optimizer(inputs, products_catalog=...)    คำนวณอย่างเดียว ไม่แตะเน็ต/DB -> plan, payload, allocations, lots_to_release
  optimize_and_post(client, dry_run=...)          อ่านข้อมูลจริงผ่าน server -> คำนวณ -> (dry_run=False) บันทึก decision + ปล่อย lot
  attach_decision_ids(result, response)           ผูก decision_id ที่ server คืนมาเข้ากับ allocations

ฝั่ง server เรียก run_optimizer ตรง ๆ ใน services/optimizer.py (route POST /api/v1/ai/optimize)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from ai_engine.optimizer.config import OptimizerConfig
from ai_engine.optimizer.context import build_context
from ai_engine.optimizer.decisions import build_decisions, validate_payload
from ai_engine.optimizer.io import ApiClient, load_from_api
from ai_engine.optimizer.models import Inputs
from ai_engine.optimizer.plan import build_plan, compute_baselines
from ai_engine.optimizer.solver import solve
from ai_engine.optimizer.validate import validate_plan


class PlanValidationError(RuntimeError):
    def __init__(self, violations: list, payload_errors: list):
        super().__init__(f"แผนไม่ผ่านการตรวจ: กฎเข้ม {len(violations)} ข้อ, payload {len(payload_errors)} ข้อ "
                         f"{(violations + payload_errors)[:3]}")
        self.violations, self.payload_errors = violations, payload_errors


def check_scan_date(data: Inputs) -> list:
    """H0: วันที่สแกน (= วันหมดอายุ - days_to_expiry ตอนประเมิน) ต้องเท่ากับ reference_date ของ server
    ไม่ตรง = DEMO_DATE ใน server/.env ไม่ใช่วันเดียวกับที่ Risk Scanner สแกน หรือรอบสแกนเก่าแล้ว
    -> วันหมดอายุ / shelf / ความต้องการเมนูผิดทั้งหมด จึงไม่คำนวณต่อ"""
    out = []
    for lot in data.lots:
        scanned = lot.expiration_date - timedelta(days=lot.days_to_expiry_assessed)
        if scanned != data.reference_date:
            out.append({"rule": "H0_SCAN_DATE_MISMATCH", "lot_id": lot.lot_id,
                        "detail": f"สแกนวันที่ {scanned} แต่ server ใช้วันที่ {data.reference_date}: ตั้ง DEMO_DATE={scanned} "
                                  f"ใน server/.env แล้วเปิด server ใหม่ หรือสแกนรอบใหม่ (run_scan.py --source api)"})
    return out


def lots_to_release(plan: dict) -> list:
    """lot ที่ขายราคาปกติได้หมดตามที่ forecaster คาด (ไม่มี decision และไม่ถูกใช้ในครัว) -> คืน IDLE ให้สแกนใหม่พรุ่งนี้"""
    return [lo["lot_id"] for lo in plan["lots"]
            if lo["portions"] and all(p["method"] == "SELL_REGULAR" for p in lo["portions"])]


def run_optimizer(inputs, *, products_catalog: Optional[list] = None, now: Optional[datetime] = None,
                  cfg: Optional[OptimizerConfig] = None, decided=(), with_baselines: bool = True,
                  strict: bool = True) -> dict:
    """inputs = JSON ของ GET /ai/optimize-inputs (หรือ Inputs), products_catalog = GET /products (flag การกำจัด)
    now = วันเวลาที่ใช้คิด (ไม่ส่ง = reference_date + เวลาไทยตอนนี้), decided = assessment_id ที่มี decision แล้ว
    strict=True: แผนหลุดกฎ หรือ payload ไม่ผ่านการตรวจแบบ server -> raise PlanValidationError"""
    cfg = cfg or OptimizerConfig()
    data = inputs if isinstance(inputs, Inputs) else Inputs.from_json(inputs, products_catalog)
    stale = check_scan_date(data)
    if stale and not cfg.allow_stale_scan:
        raise PlanValidationError(stale, [])
    ctx = build_context(data, now, cfg, frozenset(str(x) for x in decided))
    if not ctx.lots:
        plan = build_plan(ctx, solve(ctx))
        plan["warnings"].append("ไม่มี lot ที่ต้องตัดสินใจในรอบนี้ (ไม่มี HIGH / CRITICAL หรือมี decision / task แล้ว)")
        return {"plan": plan, "payload": {"optimizer_version": cfg.model_version, "decisions": []},
                "allocations": [], "lots_to_release": [], "violations": [], "payload_errors": []}
    sol = solve(ctx)
    plan = build_plan(ctx, sol, compute_baselines(ctx, sol) if with_baselines else None)
    violations = validate_plan(plan, ctx)
    built = build_decisions(plan, ctx)
    errors = validate_payload(built["payload"], ctx)
    plan["violations"], plan["payload_errors"] = violations, errors
    if strict and (violations or errors):
        raise PlanValidationError(violations, errors)
    return {"plan": plan, "payload": built["payload"], "allocations": built["allocations"],
            "lots_to_release": lots_to_release(plan) if cfg.release_no_action_lots else [],
            "violations": violations, "payload_errors": errors}


def attach_decision_ids(result: dict, response: Optional[dict]) -> None:
    """server คืน decision ตามลำดับที่ส่ง -> ใส่ decision_id ให้ allocations"""
    ids = [d["decision_id"] for d in (response or {}).get("decisions") or []]
    for a in result["allocations"]:
        for key, out in (("decision_index", "decision_id"), ("covered_by_decision_index", "covered_by_decision_id")):
            i = a.get(key)
            if i is not None and i < len(ids):
                a[out] = str(ids[i])


def optimize_and_post(client: Optional[ApiClient] = None, *, run_id: Optional[str] = None, days_ahead: int = 1,
                      cfg: Optional[OptimizerConfig] = None, now: Optional[datetime] = None,
                      dry_run: bool = True) -> dict:
    """ขั้นที่ 4-5 ของ AI Pipeline ผ่าน route ของ server
    dry_run=True  อ่านอย่างเดียว (GET) ไม่เขียนอะไร
    dry_run=False POST /optimization-decisions แล้ว PATCH lot ที่ไม่ต้องทำอะไรเป็น IDLE"""
    client = client or ApiClient()
    inputs, products, decided = load_from_api(client, run_id, days_ahead)
    result = run_optimizer(inputs, products_catalog=products, now=now, cfg=cfg, decided=decided)
    result.update(inputs=inputs, products=products, saved=None, released=None, dry_run=dry_run)
    if dry_run:
        return result
    if result["payload"]["decisions"]:
        result["saved"] = client.post_decisions(result["payload"])
        attach_decision_ids(result, result["saved"])
    if result["lots_to_release"]:
        result["released"] = client.set_lot_status(result["lots_to_release"], "IDLE")
    return result