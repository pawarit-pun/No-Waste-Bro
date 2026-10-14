from collections import defaultdict
from datetime import date, datetime

from fastapi import HTTPException
from postgrest.exceptions import APIError

from core.dates import BKK
from db.helpers import fetch_by_ids
from db.supabase import supabase
from schemas.enums import ActionType, DecisionStatus
from schemas.task import TaskCreate
from services.decisions import STATUS_VIEW
from services.kitchen import book_hours, release_hours

# field ที่คัดลอกจาก decision ไปเป็น task (LLM แก้ไม่ได้)
DECISION_FIELDS = (
    "decision_id", "assessment_id", "lot_id", "action_type", "action_quantity",
    "discount_pct", "new_recommended_price", "target_recipe_id", "batch_count",
    "target_partner_id", "due_by", "expected_profit_impact",
)


def _booking_date(due_by: str) -> date:
    """วันที่จองครัว = วันที่ของ due_by ตามเวลาไทย"""
    dt = datetime.fromisoformat(due_by)
    if dt.tzinfo is None:
        return dt.date()
    return dt.astimezone(BKK).date()


def _load_decisions(tasks: list[TaskCreate]) -> dict[str, dict]:
    ids = [str(t.decision_id) for t in tasks]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Each decision_id can appear only once per request")

    decisions = fetch_by_ids(STATUS_VIEW, "decision_id", ids)
    for i, decision_id in enumerate(ids):
        d = decisions.get(decision_id)
        if d is None:
            raise HTTPException(422, f"tasks[{i}]: decision_id '{decision_id}' not found")
        if d["status"] != DecisionStatus.PENDING.value:
            raise HTTPException(409, f"tasks[{i}]: decision '{decision_id}' already has task '{d['task_id']}'")
    return decisions


def _build_rows(tasks: list[TaskCreate], decisions: dict[str, dict]) -> list[dict]:
    """ตัวเลขทั้งหมดมาจาก decision ส่วน product_id / original_price มาจาก lot"""
    lots = fetch_by_ids("inventory_lots", "lot_id", {d["lot_id"] for d in decisions.values()},
                        "lot_id, product_id, current_selling_price")
    rows = []
    for task in tasks:
        d = decisions[str(task.decision_id)]
        lot = lots[d["lot_id"]]
        row = {k: d[k] for k in DECISION_FIELDS if d.get(k) is not None}
        row.update(task.model_dump(mode="json", exclude_none=True))
        row["product_id"] = lot["product_id"]
        row["original_price"] = lot["current_selling_price"]
        rows.append(row)
    return rows


def _kitchen_hours_needed(decisions: list[dict]) -> dict[tuple[str, date], float]:
    """รวมชั่วโมงครัวที่ต้องจองแยกตาม (department_id, วันที่) คำนวณจากสูตร × batch_count ของ decision"""
    kitchen = [d for d in decisions if d["action_type"] == ActionType.KITCHEN_REPURPOSE.value]
    recipes = fetch_by_ids("recipes", "recipe_id", {d["target_recipe_id"] for d in kitchen},
                           "recipe_id, department_id, estimated_prep_time_mins, is_active")
    needed: dict[tuple[str, date], float] = defaultdict(float)
    for d in kitchen:
        recipe = recipes.get(d["target_recipe_id"])
        if recipe is None or not recipe["is_active"]:
            raise HTTPException(422, f"decision '{d['decision_id']}': recipe '{d['target_recipe_id']}' "
                                     "not found or inactive")
        if not recipe["department_id"] or not recipe["estimated_prep_time_mins"]:
            raise HTTPException(422, f"recipe '{d['target_recipe_id']}' has no department or prep time")
        hours = recipe["estimated_prep_time_mins"] * d["batch_count"] / 60
        needed[(recipe["department_id"], _booking_date(d["due_by"]))] += hours
    return {key: round(hrs, 2) for key, hrs in needed.items()}


def _release_all(bookings: list[dict]) -> None:
    for b in bookings:
        release_hours(b["department_id"], date.fromisoformat(b["date"]), b["hours"])


def create_tasks(tasks: list[TaskCreate]) -> dict:
    """เปลี่ยน decision เป็น task ถ้ามี task ครัวจะจองชั่วโมงครัวให้ก่อน
    ถ้าจองไม่ได้หรือ insert ไม่สำเร็จ จะคืนชั่วโมงที่จองไปแล้วทั้งหมด และไม่มี task ไหนถูกสร้าง"""
    decisions = _load_decisions(tasks)
    rows = _build_rows(tasks, decisions)
    hours_needed = _kitchen_hours_needed(list(decisions.values()))

    booked: list[dict] = []
    for (department_id, on), hours in hours_needed.items():
        if not book_hours(department_id, on, hours):
            _release_all(booked)
            raise HTTPException(409, f"Kitchen '{department_id}' does not have {hours} hours available on {on}")
        booked.append({"department_id": department_id, "date": on.isoformat(), "hours": hours})

    try:
        res = supabase.table("ai_recommended_tasks").insert(rows).execute()
    except APIError as e:
        _release_all(booked)
        if e.code == "23505":   # uq_task_decision: มีคนสร้าง task จาก decision เดียวกันไปก่อน
            raise HTTPException(409, "A task already exists for one of these decisions")
        raise HTTPException(400, f"Failed to create tasks: {e.message}")

    return {"created": len(res.data), "tasks": res.data, "kitchen_bookings": booked}
