from fastapi import HTTPException
from postgrest.exceptions import APIError

from core.dates import today_bkk
from db.supabase import supabase
from schemas.enums import ActionType, TaskStatus
from services.agent_events import emit_event
from services.kitchen import release_hours
from services.tasks import RECIPE_BOOKING_COLUMNS, get_task, kitchen_booking_of

# error code จากฟังก์ชัน complete_task ใน DB → HTTP status
DB_ERROR_STATUS = {"NW404": 404, "NW403": 403, "NW409": 409, "NW422": 422,
                   "P0001": 422,   # trigger กันราคาต่ำกว่า min_allowed_price
                   "23514": 422}   # CHECK constraint


def _load(task_id: str, staff_id: str) -> dict:
    """ตรวจว่า task และ staff มีอยู่จริง และ staff เป็นคนที่ได้รับมอบหมาย"""
    task = supabase.table("ai_recommended_tasks").select("*").eq("task_id", task_id).execute().data
    if not task:
        raise HTTPException(404, f"task_id '{task_id}' not found")
    if not supabase.table("staff").select("staff_id").eq("staff_id", staff_id).execute().data:
        raise HTTPException(404, f"staff_id '{staff_id}' not found")
    task = task[0]
    if task["assigned_staff_id"] != staff_id:
        raise HTTPException(403, f"task is assigned to '{task['assigned_staff_id']}', not '{staff_id}'")
    return task


def _transition(task: dict, allowed_from: list[TaskStatus], changes: dict) -> None:
    """เปลี่ยนสถานะเฉพาะเมื่อสถานะปัจจุบันยังเป็นค่าที่อนุญาต (กันกดซ้ำ / กดพร้อมกัน)"""
    allowed = [s.value for s in allowed_from]
    if task["task_status"] not in allowed:
        raise HTTPException(409, f"task is {task['task_status']}, expected {' or '.join(allowed)}")
    res = (supabase.table("ai_recommended_tasks").update(changes)
             .eq("task_id", task["task_id"]).in_("task_status", allowed).execute())
    if not res.data:
        raise HTTPException(409, "task status changed by another request, please refresh")


def accept_task(task_id: str, staff_id: str) -> dict:
    task = _load(task_id, staff_id)
    _transition(task, [TaskStatus.PENDING], {"task_status": TaskStatus.IN_PROGRESS.value})
    return get_task(task_id)


def reject_task(task_id: str, staff_id: str, reason: str) -> dict:
    task = _load(task_id, staff_id)
    _transition(task, [TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
                {"task_status": TaskStatus.REJECTED.value, "rejection_reason": reason})

    # งานครัว: คืนชั่วโมงที่จองไว้ตอนสร้าง task (คำนวณด้วยกติกาเดียวกับตอนจอง)
    department_id = None
    if task["action_type"] == ActionType.KITCHEN_REPURPOSE.value:
        recipe = (supabase.table("recipes").select(RECIPE_BOOKING_COLUMNS)
                    .eq("recipe_id", task["target_recipe_id"]).execute().data)
        department_id, on, hours = kitchen_booking_of(task, recipe[0] if recipe else None)
        release_hours(department_id, on, round(hours, 2))
    # lot ที่ยังมีของและไม่มีงานค้างแล้ว -> IDLE ให้ pipeline รอบหน้าวางแผนใหม่ (ฟังก์ชันจาก scripts/lot_lifecycle.sql)
    released = supabase.rpc("release_lot_if_idle", {"p_lot_id": task["lot_id"]}).execute().data
    detail = get_task(task_id)
    # Manager Agent (ไม่รอผล): แจ้งผู้จัดการ + เสนอวางแผนใหม่ ส่งไม่ได้ก็ไม่กระทบการปฏิเสธ
    emit_event("TASK_REJECTED", {
        "task_id": task_id, "lot_id": task["lot_id"], "action_type": task["action_type"],
        "action_quantity": task["action_quantity"], "reason": reason, "staff_id": staff_id,
        "staff_name": (detail.get("assigned_staff") or {}).get("full_name"), "department_id": department_id,
        "lot_released": bool(released),
    })
    return detail


def complete_task(task_id: str, staff_id: str, actual_quantity: int) -> dict:
    _load(task_id, staff_id)   # ให้ 404 / 403 ชัดเจนก่อนเรียก DB
    try:
        res = supabase.rpc("complete_task", {
            "p_task_id": task_id,
            "p_staff_id": staff_id,
            "p_actual_qty": actual_quantity,
            "p_today": today_bkk().isoformat(),
        }).execute()
    except APIError as e:
        raise HTTPException(DB_ERROR_STATUS.get(e.code, 400), e.message)
    return {"task": get_task(task_id), "effects": res.data}
