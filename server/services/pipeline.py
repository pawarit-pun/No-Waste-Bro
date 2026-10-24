"""สั่งรัน AI pipeline บน worker (Lambda แยก แบบไม่รอผล) และเก็บสถานะในตาราง pipeline_runs

server รอ pipeline จนจบไม่ได้: API Gateway ตัดที่ ~29 วินาที แต่ 3 ขั้นรวมกันใช้หลายนาที
จึงสร้างแถว QUEUED แล้ว invoke worker แบบ Event (ไม่รอผล) และตอบ 202 ทันที
worker อัปเดตสถานะกลับมาผ่าน PATCH /ai/pipeline-runs/{id}
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException

from configs.config import db_env
from db.supabase import supabase
from schemas.pipeline import FINAL_STATUSES, PipelineRunUpdate, PipelineStatus, PipelineStep
from services.agent_events import emit_event

TABLE = "pipeline_runs"
ACTIVE_STATUSES = (PipelineStatus.QUEUED.value, PipelineStatus.RUNNING.value)
# Lambda รันได้นานสุด 15 นาที รอบที่ค้างนานกว่านี้ = worker ตาย (timeout / crash) ไม่ได้อัปเดตสถานะ
STALE_AFTER = timedelta(minutes=20)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get(pipeline_run_id: UUID) -> Optional[dict]:
    rows = supabase.table(TABLE).select("*").eq("pipeline_run_id", str(pipeline_run_id)).execute().data
    return rows[0] if rows else None


def _update(pipeline_run_id: str, fields: dict) -> dict:
    return supabase.table(TABLE).update(fields).eq("pipeline_run_id", pipeline_run_id).execute().data[0]


def _invoke_worker(payload: dict) -> None:
    import boto3  # มีใน Lambda runtime อยู่แล้ว

    boto3.client("lambda").invoke(
        FunctionName=db_env.pipeline_function_name,
        InvocationType="Event",  # ไม่รอผล
        Payload=json.dumps(payload).encode(),
    )


def _close_stale_runs() -> None:
    """รอบที่ยัง QUEUED / RUNNING นานเกิน STALE_AFTER → FAILED ไม่งั้นจะสั่งรอบใหม่ไม่ได้ตลอดไป"""
    active = (supabase.table(TABLE).select("pipeline_run_id, status, requested_at")
                .in_("status", ACTIVE_STATUSES).execute()).data
    for run in active:
        if _now() - datetime.fromisoformat(run["requested_at"]) > STALE_AFTER:
            failed = _update(run["pipeline_run_id"], {
                "status": PipelineStatus.FAILED.value,
                "error": f"worker ไม่ได้อัปเดตสถานะภายใน {int(STALE_AFTER.total_seconds() // 60)} นาที "
                         "(timeout หรือ crash ดู CloudWatch Logs ของ PipelineWorkerFunction)",
                "finished_at": _now().isoformat(),
            })
            _emit_failed(failed)


def start_run(stop_after: PipelineStep) -> dict:
    if not db_env.pipeline_function_name:
        raise HTTPException(503, "Pipeline worker is not configured (PIPELINE_FUNCTION_NAME is empty). "
                                 "Deploy PipelineWorkerFunction, or run AI/pipeline/worker.py locally")

    _close_stale_runs()
    active = (supabase.table(TABLE).select("pipeline_run_id, status")
                .in_("status", ACTIVE_STATUSES).limit(1).execute()).data
    if active:
        raise HTTPException(409, f"Pipeline run '{active[0]['pipeline_run_id']}' is still {active[0]['status']}")

    run = supabase.table(TABLE).insert({"stop_after": stop_after.value}).execute().data[0]
    try:
        _invoke_worker({"pipeline_run_id": run["pipeline_run_id"], "stop_after": stop_after.value})
    except Exception as e:
        _update(run["pipeline_run_id"], {
            "status": PipelineStatus.FAILED.value,
            "error": f"invoke worker failed: {type(e).__name__}: {e}",
            "finished_at": _now().isoformat(),
        })
        raise HTTPException(502, f"Could not start the pipeline worker: {type(e).__name__}: {e}")
    return run


def list_runs(limit: int) -> list[dict]:
    return (supabase.table(TABLE).select("*")
              .order("requested_at", desc=True).limit(limit).execute()).data


def get_run(pipeline_run_id: UUID) -> dict:
    run = _get(pipeline_run_id)
    if run is None:
        raise HTTPException(404, f"pipeline_run_id '{pipeline_run_id}' not found")
    return run


def update_run(pipeline_run_id: UUID, body: PipelineRunUpdate) -> dict:
    run = get_run(pipeline_run_id)
    if run["status"] in (s.value for s in FINAL_STATUSES):
        raise HTTPException(409, f"Pipeline run '{pipeline_run_id}' already {run['status']}")

    fields = body.model_dump(mode="json", exclude_unset=True)
    if body.status == PipelineStatus.RUNNING and not run["started_at"] and "started_at" not in fields:
        fields["started_at"] = _now().isoformat()
    if body.status in FINAL_STATUSES and "finished_at" not in fields:
        fields["finished_at"] = _now().isoformat()
    if not fields:
        return run
    updated = _update(str(pipeline_run_id), fields)
    if body.status == PipelineStatus.FAILED:
        _emit_failed(updated)
    elif body.status == PipelineStatus.SUCCEEDED and updated.get("run_id"):
        # Manager Agent (ไม่รอผล): Morning brief ของรอบนี้ (สรุปแผน + ตรวจความผิดปกติ -> daily_reports + กระดิ่ง)
        emit_event("PIPELINE_SUCCEEDED", {k: updated.get(k) for k in ("pipeline_run_id", "run_id", "stop_after",
                                                                       "at_risk_lots", "decisions_created",
                                                                       "tasks_created")})
    return updated


def _emit_failed(run: dict) -> None:
    """Manager Agent (ไม่รอผล): แจ้งสาเหตุ + เสนอคืน lot ที่ค้าง หรือรันใหม่"""
    emit_event("PIPELINE_FAILED", {k: run.get(k) for k in ("pipeline_run_id", "run_id", "current_step", "error")})
