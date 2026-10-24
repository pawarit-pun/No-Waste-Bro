"""Manager Agent: แชท (เรียก Lambda แบบรอผล) + แจ้งเตือน + ข้อเสนอที่ผู้จัดการกดยืนยัน

แชท: API Gateway ตัดที่ ~29 วินาที agent ตั้งงบเวลาไว้ 25 วินาที ฝั่งนี้รอได้ 27 วินาที
ข้อเสนอ: agent สร้างได้อย่างเดียว server ทำตามเมื่อผู้จัดการกดยืนยัน (execute_proposal) และตรวจกับข้อมูลล่าสุดก่อนทำ
"""
import json
import logging
from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import HTTPException

from configs.config import db_env
from core.dates import BKK, now_bkk, today_bkk
from db.supabase import supabase
from schemas.agent import AgentAskRequest, AgentRunBatch
from schemas.pipeline import PipelineStep
from services import auto_approve, pipeline
from services.agent_events import daily_now, lambda_client, watch_now  # noqa: F401  (ใช้ใน router)
from services.kitchen import book_hours
from services.pending_tasks import _check_manager

log = logging.getLogger(__name__)
RUNS, PROPOSALS, NOTIFICATIONS = "agent_runs", "agent_proposals", "agent_notifications"


def _require_function() -> str:
    if not db_env.agent_function_name:
        raise HTTPException(503, "Manager Agent is not configured (AGENT_FUNCTION_NAME is empty; "
                                 "run on AWS or set it in .env)")
    return db_env.agent_function_name


def _expires_at() -> str:
    """ข้อเสนอหมดอายุสิ้นวันของระบบ (DEMO_DATE หรือวันนี้)"""
    return datetime.combine(today_bkk(), time(23, 59, 59), BKK).isoformat()


# ---------------------------------------------------------------- แชท
def ask(body: AgentAskRequest) -> dict:
    name = _require_function()
    try:
        r = lambda_client().invoke(FunctionName=name, InvocationType="RequestResponse",
                                   Payload=json.dumps(body.model_dump(mode="json"), ensure_ascii=False).encode())
    except Exception as e:  # noqa: BLE001
        if "timeout" in type(e).__name__.lower():
            raise HTTPException(504, "Manager Agent took too long to answer, please ask again") from e
        raise HTTPException(502, f"Could not call the Manager Agent: {type(e).__name__}: {e}") from e
    raw = r["Payload"].read()
    payload = json.loads(raw) if raw else None
    if r.get("FunctionError") or not isinstance(payload, dict):
        msg = payload.get("errorMessage") if isinstance(payload, dict) else str(payload)[:300]
        raise HTTPException(502, f"Manager Agent failed: {msg}")
    if payload.get("error"):
        raise HTTPException(int(payload.get("status") or 400), payload["error"])
    _record_chat(body, payload)
    return payload


def _record_chat(body: AgentAskRequest, payload: dict) -> None:
    """บันทึกรอบแชทใน agent_runs และเปลี่ยนการ์ดข้อเสนอเป็นแถวจริงใน agent_proposals (มี proposal_id ให้กดยืนยัน)
    บันทึกไม่ได้ (เช่น ยังไม่ได้รัน agent_tables.sql) = แชทยังตอบได้ การ์ดข้อเสนอจะกดยืนยันไม่ได้"""
    try:
        run = supabase.table(RUNS).insert({
            "trigger": "CHAT", "input": body.model_dump(mode="json"), "answer": payload.get("answer"),
            "model_used": payload.get("model_used"), "tool_calls": payload.get("tool_calls") or [],
            "warnings": payload.get("warnings") or [], "usage": payload.get("usage") or {},
            "latency_ms": payload.get("latency_ms"),
        }).execute().data[0]
        for i, a in enumerate(payload.get("artifacts") or []):
            if a.get("type") != "proposal":
                continue
            row = supabase.table(PROPOSALS).insert({
                "kind": a["kind"], "params": a.get("params") or {}, "title": a["title"], "reason": a.get("reason"),
                "source": "CHAT", "agent_run_id": run["agent_run_id"], "expires_at": _expires_at(),
            }).execute().data[0]
            payload["artifacts"][i] = {"type": "proposal", "proposal": row}
    except Exception as e:  # noqa: BLE001
        log.warning("record chat failed: %s: %s", type(e).__name__, e)
        payload.setdefault("warnings", []).append(f"บันทึกประวัติแชท / ข้อเสนอไม่สำเร็จ: {type(e).__name__}")


def warm_up() -> bool:
    """ปลุก container (ไม่รอผล) ตอนผู้จัดการเปิดแผงแชท ลด cold start ของคำถามแรก"""
    if not db_env.agent_function_name:
        return False
    try:
        lambda_client().invoke(FunctionName=db_env.agent_function_name, InvocationType="Event",
                               Payload=b'{"warmup": true}')
        return True
    except Exception:  # noqa: BLE001  ปลุกไม่ได้ไม่ใช่ error ของผู้ใช้
        return False


# ---------------------------------------------------------------- ผลของเหตุการณ์ (route ภายใน)
def record_batch(batch: AgentRunBatch) -> dict:
    """บันทึก 1 รอบของ agent: run -> ข้อเสนอ -> แจ้งเตือน (แจ้งเตือนที่ dedupe_key ซ้ำถูกข้าม พร้อมข้อเสนอของมัน)"""
    keys = [n.dedupe_key for n in batch.notifications if n.dedupe_key]
    existing = set()
    if keys:
        existing = {r["dedupe_key"] for r in supabase.table(NOTIFICATIONS).select("dedupe_key")
                    .in_("dedupe_key", keys).execute().data}
    fresh = [n for n in batch.notifications if not n.dedupe_key or n.dedupe_key not in existing]
    used_refs = {n.proposal_ref for n in fresh if n.proposal_ref is not None}

    run = supabase.table(RUNS).insert(batch.run.model_dump(mode="json")).execute().data[0]
    proposal_ids: dict[int, str] = {}
    for i, p in enumerate(batch.proposals):
        if i not in used_refs:
            continue
        row = supabase.table(PROPOSALS).insert({**p.model_dump(mode="json"), "agent_run_id": run["agent_run_id"],
                                                "expires_at": _expires_at()}).execute().data[0]
        proposal_ids[i] = row["proposal_id"]
    report_id = None
    if batch.report is not None:
        row = {**batch.report.model_dump(mode="json"), "agent_run_id": run["agent_run_id"],
               "updated_at": datetime.now(BKK).isoformat()}
        report_id = (supabase.table("daily_reports").upsert(row, on_conflict="report_date,kind").execute()
                     .data[0]["report_id"])
    if batch.auto_approved:          # Phase 4: plan ที่ agent อนุมัติก่อนบันทึกรอบนี้
        try:
            auto_approve.link_run([str(i) for i in batch.auto_approved], run["agent_run_id"])
        except Exception as e:  # noqa: BLE001  ผูกไม่ได้ไม่ทำให้บันทึกรอบล้ม
            log.warning("link auto-approved plans: %s", e)
    saved = 0
    for n in fresh:
        data = n.model_dump(mode="json", exclude={"proposal_ref"})
        data.update(agent_run_id=run["agent_run_id"], proposal_id=proposal_ids.get(n.proposal_ref))
        res = supabase.table(NOTIFICATIONS).upsert(data, on_conflict="dedupe_key", ignore_duplicates=True).execute()
        saved += len(res.data or [])
    return {"agent_run_id": run["agent_run_id"], "notifications": saved, "proposals": len(proposal_ids),
            "skipped_duplicates": len(batch.notifications) - len(fresh), "report_id": report_id}


# ---------------------------------------------------------------- รายงานประจำวัน (Phase 3)
def list_daily_reports(days: int) -> dict:
    today = today_bkk()
    rows = (supabase.table("daily_reports").select("*")
              .gte("report_date", (today - timedelta(days=days)).isoformat()).lte("report_date", today.isoformat())
              .order("report_date", desc=True).order("kind").execute().data)
    rows.sort(key=lambda r: (r["report_date"], r["kind"] == "EVENING"), reverse=True)
    return {"reference_date": today, "items": rows}


# ---------------------------------------------------------------- แจ้งเตือน
def list_notifications(unread_only: bool, limit: int, dedupe_key: Optional[str]) -> dict:
    q = supabase.table(NOTIFICATIONS).select("*").order("created_at", desc=True).limit(limit)
    if unread_only:
        q = q.is_("read_at", "null")
    if dedupe_key:
        q = q.eq("dedupe_key", dedupe_key)
    rows = q.execute().data
    ids = [r["proposal_id"] for r in rows if r.get("proposal_id")]
    props = {}
    if ids:
        props = {p["proposal_id"]: _expire(p) for p in supabase.table(PROPOSALS).select("*").in_("proposal_id", ids)
                 .execute().data}
    for r in rows:
        r["proposal"] = props.get(r.get("proposal_id"))
    unread = (supabase.table(NOTIFICATIONS).select("notification_id", count="exact").is_("read_at", "null")
              .limit(1).execute().count or 0)
    return {"unread": unread, "items": rows}


def mark_read(notification_id: Optional[str] = None) -> dict:
    q = supabase.table(NOTIFICATIONS).update({"read_at": datetime.now(BKK).isoformat()}).is_("read_at", "null")
    if notification_id:
        q = q.eq("notification_id", notification_id)
    return {"updated": len(q.execute().data or [])}


# ---------------------------------------------------------------- ข้อเสนอ
def _expire(p: dict) -> dict:
    """ข้อเสนอที่เลยเวลา -> EXPIRED (ตรวจตอนอ่าน ไม่มี job แยก)"""
    if p["status"] == "PROPOSED" and p.get("expires_at") and datetime.fromisoformat(p["expires_at"]) < now_bkk():
        res = (supabase.table(PROPOSALS).update({"status": "EXPIRED"})
               .eq("proposal_id", p["proposal_id"]).eq("status", "PROPOSED").execute().data)
        return res[0] if res else {**p, "status": "EXPIRED"}
    return p


def get_proposal(proposal_id: str) -> dict:
    rows = supabase.table(PROPOSALS).select("*").eq("proposal_id", proposal_id).execute().data
    if not rows:
        raise HTTPException(404, f"proposal_id '{proposal_id}' not found")
    return _expire(rows[0])


def _decide(proposal_id: str, staff_id: str, status: str) -> dict:
    _check_manager(staff_id)
    p = get_proposal(proposal_id)
    if p["status"] != "PROPOSED":
        raise HTTPException(409, f"proposal is already {p['status']}")
    res = (supabase.table(PROPOSALS)
           .update({"status": status, "decided_by": staff_id, "decided_at": datetime.now(BKK).isoformat()})
           .eq("proposal_id", proposal_id).eq("status", "PROPOSED").execute().data)
    if not res:   # กดพร้อมกัน 2 ครั้ง
        raise HTTPException(409, "proposal was changed by another request, please refresh")
    return res[0]


def dismiss_proposal(proposal_id: str, staff_id: str) -> dict:
    return _decide(proposal_id, staff_id, "DISMISSED")


def execute_proposal(proposal_id: str, staff_id: str) -> dict:
    """ผู้จัดการกดยืนยัน: จองสถานะเป็น EXECUTED ก่อน (กันกดซ้ำ) แล้วทำ ไม่สำเร็จ -> FAILED + error"""
    p = _decide(proposal_id, staff_id, "EXECUTED")
    try:
        result = _run(p["kind"], p.get("params") or {})
    except HTTPException as e:
        supabase.table(PROPOSALS).update({"status": "FAILED", "result": {"error": e.detail}}) \
            .eq("proposal_id", proposal_id).execute()
        raise
    except Exception as e:  # noqa: BLE001
        supabase.table(PROPOSALS).update({"status": "FAILED", "result": {"error": f"{type(e).__name__}: {e}"}}) \
            .eq("proposal_id", proposal_id).execute()
        raise HTTPException(400, f"Failed to execute proposal: {type(e).__name__}: {e}") from e
    return supabase.table(PROPOSALS).update({"result": result}).eq("proposal_id", proposal_id).execute().data[0]


def _run(kind: str, params: dict) -> dict:
    if kind == "RUN_PIPELINE":
        run = pipeline.start_run(PipelineStep(params.get("stop_after") or "TASKS"))   # 409 ถ้ามีรอบรันอยู่
        return {"pipeline_run_id": run["pipeline_run_id"]}

    if kind == "RELEASE_LOTS":
        released, skipped = [], []
        for lot_id in params.get("lot_ids") or []:
            ok = supabase.rpc("release_lot_if_idle", {"p_lot_id": lot_id}).execute().data
            (released if ok else skipped).append(lot_id)
        if not released:
            raise HTTPException(409, "None of the lots can be released any more (they have work, a plan, or are IDLE)")
        return {"released": released, "skipped": skipped}

    if kind == "BLOCK_KITCHEN":
        dep, on = params.get("department_id"), date.fromisoformat(params.get("date") or today_bkk().isoformat())
        row = (supabase.table("kitchen_capacity_daily").select("remaining_hrs")
               .eq("department_id", dep).eq("capacity_date", on.isoformat()).execute().data)
        remaining = float(row[0]["remaining_hrs"] or 0) if row else 0.0
        hours = round(min(float(params.get("hours") or remaining), remaining), 2)
        if hours <= 0 or not book_hours(dep, on, hours):
            raise HTTPException(409, f"Kitchen '{dep}' has no hours left to block on {on}")
        result = {"department_id": dep, "date": on.isoformat(), "hours_blocked": hours}
        if params.get("then_run_pipeline"):
            try:
                result["pipeline_run_id"] = pipeline.start_run(PipelineStep.TASKS)["pipeline_run_id"]
            except HTTPException as e:   # ปิดครัวสำเร็จแล้ว แจ้งเฉพาะส่วนที่เริ่ม pipeline ไม่ได้
                result["pipeline_error"] = e.detail
        return result

    raise HTTPException(422, f"Unknown proposal kind '{kind}'")
