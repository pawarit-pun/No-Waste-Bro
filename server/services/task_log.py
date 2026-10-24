"""Task log: task ที่อนุมัติแล้วทุกสถานะ + ประวัติสถานะ (task_events) ให้ผู้จัดการดูว่างานเดินไปถึงไหน

task_events บันทึกด้วย trigger บน ai_recommended_tasks (scripts/task_events.sql) ไม่ต้องแก้ Flutter app
ถ้ายังไม่ได้รัน SQL: ยังใช้ได้ แต่ timeline มีแค่เวลาสร้าง (created_at) และเวลาเสร็จ (completed_at)
เวลา created_at / event เป็นเวลาจริง ส่วน due_by เป็นวันของระบบ (DEMO_DATE) จึงเทียบเลยกำหนดกับ now_bkk()
"""
from datetime import datetime
from typing import Optional

from core.dates import BKK, now_bkk, today_bkk
from db.helpers import fetch_by_ids
from db.supabase import supabase
from schemas.enums import TaskStatus
from services.tasks import _attach_context

OPEN = (TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value)
STATUSES = tuple(s.value for s in TaskStatus)


def _dt(v) -> Optional[datetime]:
    if not v:
        return None
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=BKK)


def _minutes(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
    return int((b - a).total_seconds() // 60) if a and b and b >= a else None


def _events(task_ids: list[str]) -> tuple[dict[str, list[dict]], bool]:
    """-> ({task_id: [event เรียงเวลา]}, ตาราง task_events มีไหม)"""
    if not task_ids:
        return {}, True
    try:
        rows = (supabase.table("task_events").select("*").in_("task_id", task_ids)
                  .order("created_at").order("event_id").execute().data)
    except Exception:  # noqa: BLE001  ยังไม่ได้รัน scripts/task_events.sql
        return {}, False
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(str(r["task_id"]), []).append(r)
    return out, True


def _fallback_events(t: dict) -> list[dict]:
    ev = [{"event_type": "CREATED", "to_status": "PENDING", "staff_id": t.get("assigned_staff_id"),
           "created_at": t["created_at"], "backfilled": True}]
    if t.get("completed_at") and t["task_status"] == TaskStatus.COMPLETED.value:
        ev.append({"event_type": "COMPLETED", "to_status": "COMPLETED", "staff_id": t.get("assigned_staff_id"),
                   "quantity": t.get("actual_quantity_handled"), "created_at": t["completed_at"], "backfilled": True})
    return ev


def list_log(created_from: Optional[datetime], statuses: list[str], action_type: Optional[str],
             staff_id: Optional[str]) -> dict:
    """task ที่สร้างตั้งแต่ created_from (ค่าเริ่มต้น เที่ยงคืนวันนี้ตามเวลาจริง) + งานที่ยังไม่จบทั้งหมด ใหม่ก่อน"""
    since = created_from or datetime.now(BKK).replace(hour=0, minute=0, second=0, microsecond=0)
    if since.tzinfo is None:
        since = since.replace(tzinfo=BKK)
    recent = (supabase.table("ai_recommended_tasks").select("*").gte("created_at", since.isoformat())
                .execute().data)
    still_open = supabase.table("ai_recommended_tasks").select("*").in_("task_status", list(OPEN)).execute().data
    by_id = {str(t["task_id"]): t for t in [*recent, *still_open]}
    tasks = list(by_id.values())
    if action_type:
        tasks = [t for t in tasks if t["action_type"] == action_type]
    if staff_id:
        tasks = [t for t in tasks if t.get("assigned_staff_id") == staff_id]

    now = now_bkk()
    for t in tasks:
        due = _dt(t.get("due_by"))
        t["is_overdue"] = t["task_status"] in OPEN and due is not None and due < now
        t["minutes_late"] = _minutes(due, now) if t["is_overdue"] else None
    # นับก่อนกรองสถานะ: แถบสถานะของหน้าแสดงจำนวนของทุกสถานะเสมอ
    counts = {s.lower(): sum(1 for t in tasks if t["task_status"] == s) for s in STATUSES}
    counts["overdue"] = sum(1 for t in tasks if t["is_overdue"])
    counts["total"] = len(tasks)
    if statuses:
        want = set(statuses)
        tasks = [t for t in tasks if t["task_status"] in want or ("OVERDUE" in want and t["is_overdue"])]
    tasks.sort(key=lambda t: str(t["created_at"]), reverse=True)

    tasks = _attach_context(tasks)
    ids = [str(t["task_id"]) for t in tasks]
    events, has_events = _events(ids)
    reviews = {str(r["task_id"]): r for r in
               (supabase.table("pending_tasks").select("*").in_("task_id", ids).execute().data if ids else [])}
    reviewers = fetch_by_ids("staff", "staff_id", {r.get("reviewed_by") for r in reviews.values()},
                             "staff_id, full_name, image_url")
    for t in tasks:
        tid = str(t["task_id"])
        ev = events.get(tid) or _fallback_events(t)
        t["events"] = ev
        r = reviews.get(tid)
        t["review"] = None if r is None else {
            "review_id": r["review_id"], "reviewed_at": r.get("reviewed_at"), "review_note": r.get("review_note"),
            "approved_by_agent": bool(r.get("approved_by_agent")), "reviewer": reviewers.get(r.get("reviewed_by")),
        }
        created = _dt(t["created_at"])
        started = next((_dt(e["created_at"]) for e in ev if e["event_type"] == "STARTED"), None)
        finished = next((_dt(e["created_at"]) for e in reversed(ev) if e["event_type"] in ("COMPLETED", "REJECTED")), None)
        if finished is None and t["task_status"] == TaskStatus.COMPLETED.value:
            finished = _dt(t.get("completed_at"))
        t["started_at"] = started.isoformat() if started else None
        t["finished_at"] = finished.isoformat() if finished else None
        t["wait_minutes"] = _minutes(created, started)
        t["work_minutes"] = _minutes(started, finished)
        t["last_event"] = ev[-1] if ev else None
    return {"reference_date": today_bkk(), "since": since, "events_available": has_events, "counts": counts,
            "items": tasks}



