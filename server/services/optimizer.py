"""Optimizer ฝั่ง server (ไฟล์ใหม่): ใช้ใน POST /api/v1/ai/optimize

PART 1  load_engine()   โหลดตัว Optimizer จาก AI/food_waste_optimizer (ไม่คัดลอกโค้ดซ้ำ)
PART 2  read_inputs()   อ่านข้อมูลจริงจาก Supabase ด้วยโค้ดเดิมของ server
                         - get_optimize_inputs() ใน routers/ai.py (ตัวเดียวกับ GET /ai/optimize-inputs)
                         - flag การกำจัด (allow_animal_feed / composting / anaerobic_digestion / landfill) จากตาราง products
                         - assessment ที่มี decision แล้วในรอบนี้ (กันบันทึกซ้ำเมื่อเรียกซ้ำ)
PART 2b list_scan_runs() / pick_run()   ใช้ใน GET /api/v1/ai/optimize-runs และตอนไม่ส่ง run_id
                         เลือกรอบสแกนล่าสุดที่ (1) สแกนวันเดียวกับ reference_date (DEMO_DATE) และ
                         (2) ยังมี lot HIGH / CRITICAL สถานะ PROCESSING ที่ยังไม่มี decision
                         -> get เสร็จแล้ว post ลง optimization_decisions ได้ทันทีโดยไม่ต้องหา run_id เอง
PART 3  run_optimize()  คำนวณ แล้วถ้า dry_run=False
                         - บันทึกผ่าน create_decisions() ใน services/decisions.py (ตรวจกฎเดียวกับ POST /optimization-decisions)
                         - lot ที่ขายราคาปกติได้หมด -> IDLE ผ่าน update_lots_ai_status() (ตัวเดียวกับ PATCH /inventory-lots/ai-status)
"""
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from configs.config import db_env
from core.dates import now_bkk, today_bkk
from db.supabase import supabase
from routers.ai import get_optimize_inputs
from routers.inventory_lots import update_lots_ai_status
from schemas.decision import DecisionCreate
from schemas.enums import LotAIStatus
from schemas.inventory_lot import LotAIStatusUpdate
from services.decisions import create_decisions

AT_RISK_LEVELS = ("HIGH", "CRITICAL")            # เหมือน routers/ai.py: LOW / MEDIUM ไม่ส่งต่อ Optimizer
PROCESS_STATUSES = (LotAIStatus.PROCESSING.value,)  # เหมือน OptimizerConfig.process_ai_statuses
PAGE = 1000                                       # Supabase คืนได้ครั้งละ 1000 แถว
PRODUCT_FLAGS = ("product_id, allow_donation, allow_animal_feed, allow_composting, "
                 "allow_anaerobic_digestion, allow_landfill")


# ---------------------------------------------------------------- PART 1
def optimizer_path() -> Path:
    """OPTIMIZER_PATH ใน .env หรือ ../AI/food_waste_optimizer นับจากโฟลเดอร์ server"""
    if db_env.optimizer_path:
        return Path(db_env.optimizer_path).resolve()
    return Path(__file__).resolve().parents[2] / "AI" / "food_waste_optimizer"


def load_engine():
    path = str(optimizer_path())
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        import ai_engine.optimizer as engine
    except ImportError as e:
        raise HTTPException(503, f"โหลด Optimizer ไม่ได้: {e} | ตรวจว่าติดตั้ง numpy + scipy ใน venv ของ server "
                                 f"และโฟลเดอร์ Optimizer อยู่ที่ {path} (ตั้ง OPTIMIZER_PATH ใน .env ได้)")
    return engine


# ---------------------------------------------------------------- PART 2
def read_inputs(run_id: Optional[str], days_ahead: int) -> tuple[dict, list, set]:
    inputs = get_optimize_inputs(run_id=run_id, days_ahead=days_ahead)
    flags = supabase.table("products").select(PRODUCT_FLAGS).execute().data
    decided = set()
    if inputs["run_id"]:
        rows = (supabase.table("optimization_decisions").select("assessment_id")
                  .eq("run_id", inputs["run_id"]).execute()).data
        decided = {str(r["assessment_id"]) for r in rows}
    return inputs, flags, decided


# ---------------------------------------------------------------- PART 2b
def _all_rows(table: str, columns: str) -> list:
    rows, start = [], 0
    while True:
        chunk = supabase.table(table).select(columns).range(start, start + PAGE - 1).execute().data
        rows += chunk
        if len(chunk) < PAGE:
            return rows
        start += PAGE


def list_scan_runs() -> dict:
    """ทุกรอบสแกนใน lot_risk_assessments: สแกนวันไหน, กี่ lot, HIGH/CRITICAL กี่ lot, มี decision แล้วกี่ lot, เหลือรอกี่ lot

    วันที่สแกน = วันหมดอายุของ lot - days_to_expiry ตอนประเมิน (กติกาเดียวกับ H0 ของ Optimizer)
    suggested_run_id = รอบล่าสุดที่สแกนวันเดียวกับ reference_date และยังมี lot รอตัดสินใจ (null = ไม่มี)
    """
    today = today_bkk()
    rows = _all_rows("lot_risk_assessments",
                     "assessment_id, run_id, lot_id, assessed_at, risk_level, days_to_expiry, "
                     "lot:inventory_lots(expiration_date, ai_status)")
    decided = {str(r["assessment_id"]) for r in _all_rows("optimization_decisions", "assessment_id")}

    runs: dict = {}
    for r in rows:
        rid = str(r["run_id"])
        run = runs.setdefault(rid, {"run_id": rid, "assessed_at": r["assessed_at"], "scan_dates": Counter(),
                                    "levels": Counter(), "lots": 0, "at_risk": 0, "decided": 0, "pending": 0})
        run["assessed_at"] = max(run["assessed_at"], r["assessed_at"])
        run["lots"] += 1
        run["levels"][r["risk_level"]] += 1
        lot = r.get("lot") or {}
        if lot.get("expiration_date") and r.get("days_to_expiry") is not None:
            run["scan_dates"][date.fromisoformat(str(lot["expiration_date"])[:10])
                              - timedelta(days=int(r["days_to_expiry"]))] += 1
        if r["risk_level"] not in AT_RISK_LEVELS:
            continue
        run["at_risk"] += 1
        if str(r["assessment_id"]) in decided:
            run["decided"] += 1
        elif lot.get("ai_status") in PROCESS_STATUSES:
            run["pending"] += 1

    out = []
    for run in sorted(runs.values(), key=lambda x: x["assessed_at"], reverse=True):
        scan_date = run.pop("scan_dates").most_common(1)[0][0] if run["scan_dates"] else None
        out.append({**run, "levels": dict(run["levels"]), "scan_date": scan_date,
                    "matches_reference_date": scan_date == today,
                    "ready": scan_date == today and run["pending"] > 0})
    suggested = next((r["run_id"] for r in out if r["ready"]), None)
    return {"reference_date": today, "suggested_run_id": suggested, "runs": out}


def pick_run(run_id: Optional[str]) -> Optional[str]:
    """run_id ที่ส่งมา > รอบที่พร้อมตัดสินใจ (suggested) > None (= รอบล่าสุดตามเดิมของ GET /ai/optimize-inputs)"""
    if run_id:
        return run_id
    return list_scan_runs()["suggested_run_id"]


# ---------------------------------------------------------------- PART 3
def run_optimize(run_id: Optional[str] = None, days_ahead: int = 1, dry_run: bool = True,
                 release_no_action_lots: bool = True, include_plan: bool = False) -> dict:
    engine = load_engine()
    inputs, flags, decided = read_inputs(pick_run(run_id), days_ahead)
    cfg = engine.OptimizerConfig(release_no_action_lots=release_no_action_lots)
    try:
        result = engine.run_optimizer(inputs, products_catalog=flags, now=now_bkk(), cfg=cfg, decided=decided)
    except engine.PlanValidationError as e:
        raise HTTPException(422, {"message": "แผนไม่ผ่านการตรวจกฎ ไม่ได้บันทึกอะไร",
                                  "violations": e.violations, "payload_errors": e.payload_errors})

    saved = None
    if not dry_run:
        if result["payload"]["decisions"]:
            decisions = [DecisionCreate(**d) for d in result["payload"]["decisions"]]
            saved = create_decisions(decisions, result["payload"]["optimizer_version"])
            engine.attach_decision_ids(result, saved)
        if result["lots_to_release"]:
            update_lots_ai_status(LotAIStatusUpdate(lot_ids=result["lots_to_release"], ai_status=LotAIStatus.IDLE))

    plan = result["plan"]
    return {
        "run_id": plan["run_id"], "reference_date": plan["reference_date"], "simulated_now": plan["simulated_now"],
        "dry_run": dry_run, "summary": plan["summary"], "baselines": plan.get("baselines", {}),
        "decisions": result["payload"]["decisions"], "saved": saved, "allocations": result["allocations"],
        "lots_released": result["lots_to_release"], "skipped_lots": plan.get("skipped_lots", {}),
        "warnings": plan["warnings"], "plan": plan if include_plan else None,
    }