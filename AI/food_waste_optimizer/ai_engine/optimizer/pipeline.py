"""PART 10 — ฟังก์ชันครอบ (wrapper) ที่คนอื่นเรียกใช้ได้ทันที

  run_optimizer(inputs)            ข้อมูลเข้า (JSON ของ optimize-inputs) -> {"plan", "payload", ...}   ไม่แตะเน็ต
  optimize_and_post(...)           ดึงข้อมูล (API/Supabase) -> optimize -> POST /optimization-decisions
  run_full_pipeline(...)           ขั้น 1-5 ของ AI Pipeline ด้วย mock forecaster (scan -> risk -> optimize -> decisions)

ทุกฟังก์ชันที่เขียนข้อมูลจริงมี dry_run=True เป็นค่าเริ่มต้น (ไม่ยิง PATCH/POST) ต้องสั่ง dry_run=False เอง
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from ai_engine.clock import now_for
from ai_engine.optimizer.config import OptimizerConfig
from ai_engine.optimizer.context import build_context
from ai_engine.optimizer.decisions import build_decisions, validate_payload
from ai_engine.optimizer.io import ApiClient, load_inputs_from_api, load_inputs_from_supabase
from ai_engine.optimizer.models import Inputs
from ai_engine.optimizer.plan import build_plan, compute_baselines
from ai_engine.optimizer.solver import solve
from ai_engine.optimizer.validate import validate_plan


class PlanValidationError(RuntimeError):
    def __init__(self, violations: list, payload_errors: list):
        super().__init__(f"แผนไม่ผ่านการตรวจ: {len(violations)} กฎเข้ม, {len(payload_errors)} ข้อ payload")
        self.violations, self.payload_errors = violations, payload_errors


def run_optimizer(inputs, demand: Optional[dict] = None, now: Optional[datetime] = None,
                  cfg: Optional[OptimizerConfig] = None, booked_kg: Optional[Callable] = None,
                  with_baselines: bool = True, strict: bool = True) -> dict:
    """จุดเรียกหลัก: inputs = dict จาก GET /ai/optimize-inputs (หรือ Inputs)
    demand = {"curves": {...}, "menu_daily_demand": {...}} จาก forecaster (ไม่ส่ง = ใช้โมเดลสำรอง)
    booked_kg(partner_id, pickup_date) -> kg ที่จองไปแล้วของรอบรับนั้น (ไม่ส่ง = 0)
    strict=True: ถ้าแผนหลุดกฎเข้ม/payload ไม่ผ่านการตรวจแบบ server จะ raise PlanValidationError"""
    data = inputs if isinstance(inputs, Inputs) else Inputs.from_json(inputs)
    cfg = cfg or OptimizerConfig()
    ctx = build_context(data, demand, now, cfg, booked_kg)
    if not ctx.lots:
        empty = {"run_id": data.run_id, "reference_date": data.reference_date.isoformat(),
                 "simulated_now": ctx.now.isoformat(), "model_version": cfg.model_version,
                 "solver": {"name": "HiGHS", "status": "not_run", "gap": None, "time_ms": 0},
                 "lots": [], "trips": [], "kitchen_jobs": [], "kitchen_usage": [], "baselines": {},
                 "summary": {"lots": 0, "units": 0, "split_pct_by_method": {}, "units_by_method": {},
                             "kg_by_method": {}, "gross_revenue_thb": 0.0, "route_costs_thb": 0.0, "cogs_thb": 0.0,
                             "net_recovery_thb": 0.0, "net_profit_thb": 0.0, "unresolved_units": 0,
                             "reconciliation_gap_thb": 0.0, "reconciliation_ok": True},
                 "warnings": ctx.warnings + ["ไม่มี lot เสี่ยง (MEDIUM ขึ้นไป) ในรอบนี้ — ไม่มีอะไรให้ตัดสินใจ"],
                 "violations": [], "payload_errors": []}
        return {"plan": empty, "payload": {"optimizer_version": cfg.model_version, "decisions": []},
                "violations": [], "payload_errors": []}
    sol = solve(ctx)
    plan = build_plan(ctx, sol, baselines=compute_baselines(ctx, sol) if with_baselines else None)
    violations = validate_plan(plan, ctx)
    payload = build_decisions(plan, ctx)
    payload_errors = validate_payload(payload, ctx)
    plan["violations"], plan["payload_errors"] = violations, payload_errors
    if strict and (violations or payload_errors):
        raise PlanValidationError(violations, payload_errors)
    return {"plan": plan, "payload": payload, "violations": violations, "payload_errors": payload_errors}


def optimize_and_post(client: Optional[ApiClient] = None, *, source: str = "api", run_id: Optional[str] = None,
                      days_ahead: int = 1, demand: Optional[dict] = None, cfg: Optional[OptimizerConfig] = None,
                      now: Optional[datetime] = None, dry_run: bool = True, booked_kg: Optional[Callable] = None) -> dict:
    """ขั้นที่ 4-5: ดึง optimize-inputs -> optimize -> POST /optimization-decisions
    source="api" ใช้ GET /ai/optimize-inputs, source="supabase" อ่านตารางตรง"""
    if source == "supabase":
        inputs = load_inputs_from_supabase(run_id, days_ahead)
    else:
        inputs = load_inputs_from_api(client, run_id, days_ahead)
    result = run_optimizer(inputs, demand, now, cfg, booked_kg)
    result["posted"] = None
    if not dry_run and result["payload"]["decisions"]:
        result["posted"] = (client or ApiClient()).post_decisions(result["payload"])
    return result


def run_full_pipeline(client: Optional[ApiClient] = None, *, dry_run: bool = True, days_ahead: int = 1,
                      cfg: Optional[OptimizerConfig] = None, now: Optional[datetime] = None) -> dict:
    """ขั้น 1-5 ด้วย mock forecaster
    dry_run=True : อ่านอย่างเดียว (GET scan-inputs + GET optimize-inputs) แล้วประกอบ at_risk_lots ในเครื่อง ไม่เขียน DB
    dry_run=False: PATCH lot -> PROCESSING, POST /risk-assessments, GET optimize-inputs(run_id), POST /optimization-decisions"""
    import uuid
    from ai_engine.forecaster.mock_forecaster import mock_forecast, to_at_risk_rows, to_post_payload

    client = client or ApiClient()
    scan = client.get_scan_inputs()
    lots = scan.get("inventory_lots") or []
    if not lots:
        return {"message": "ไม่มี lot ที่ ai_status = IDLE", "plan": None, "payload": {"decisions": []}}
    reference = None
    if now is None:
        probe = client.get_optimize_inputs(None, days_ahead)
        reference = probe["reference_date"]
        now = now_for(datetime.fromisoformat(reference).date())
    forecast = mock_forecast(lots, now)
    if dry_run:
        inputs = client.get_optimize_inputs(None, days_ahead) if reference is None else probe
        run_id = str(uuid.uuid4())
        inputs["run_id"] = run_id
        inputs["at_risk_lots"] = to_at_risk_rows(lots, forecast, run_id, None, now)
        inputs = _enrich(inputs)
    else:
        client.set_lot_status([l["lot_id"] for l in lots], "PROCESSING")
        saved = client.post_risk_assessments(to_post_payload(forecast))
        run_id = saved["run_id"]
        inputs = _enrich(client.get_optimize_inputs(run_id, days_ahead))
    result = run_optimizer(inputs, forecast["demand"], now, cfg)
    result["posted"] = None
    if not dry_run and result["payload"]["decisions"]:
        result["posted"] = client.post_decisions(result["payload"])
    return result


def _enrich(inputs: dict) -> dict:
    from ai_engine.optimizer.io import enrich_products_with_flags
    return enrich_products_with_flags(inputs)
