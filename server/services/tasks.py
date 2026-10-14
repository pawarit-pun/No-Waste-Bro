from collections import defaultdict
from datetime import date, datetime

from fastapi import HTTPException
from postgrest.exceptions import APIError

from core.dates import BKK
from db.supabase import supabase
from schemas.enums import ActionType
from schemas.task import TaskCreate
from services.kitchen import book_hours, release_hours


def _booking_date(due_by: datetime) -> date:
    """วันที่จองครัว = วันที่ของ due_by ตามเวลาไทย (ถ้าไม่มี timezone ถือว่าเป็นเวลาไทย)"""
    if due_by.tzinfo is None:
        return due_by.date()
    return due_by.astimezone(BKK).date()


def _fetch_by_ids(table: str, key: str, ids: set[str], columns: str = "*") -> dict[str, dict]:
    if not ids:
        return {}
    res = supabase.table(table).select(columns).in_(key, list(ids)).execute()
    return {row[key]: row for row in res.data}


def _build_rows(tasks: list[TaskCreate]) -> list[dict]:
    """แปลง request เป็นแถวที่จะ insert โดยเติม product_id / original_price จาก lot"""
    lots = _fetch_by_ids("inventory_lots", "lot_id", {t.lot_id for t in tasks},
                         "lot_id, product_id, current_selling_price")
    rows = []
    for i, task in enumerate(tasks):
        lot = lots.get(task.lot_id)
        if lot is None:
            raise HTTPException(422, f"tasks[{i}]: lot_id '{task.lot_id}' not found")
        if task.product_id and task.product_id != lot["product_id"]:
            raise HTTPException(422, f"tasks[{i}]: product_id '{task.product_id}' does not match lot "
                                     f"'{task.lot_id}' (product {lot['product_id']})")
        row = task.model_dump(mode="json", exclude_none=True)
        row["product_id"] = lot["product_id"]
        row.setdefault("original_price", lot["current_selling_price"])
        rows.append(row)
    return rows


def _kitchen_hours_needed(tasks: list[TaskCreate]) -> dict[tuple[str, date], float]:
    """รวมชั่วโมงครัวที่ต้องจองแยกตาม (department_id, วันที่) คำนวณจากสูตร ไม่ใช้ค่าจาก LLM"""
    kitchen_tasks = [(i, t) for i, t in enumerate(tasks) if t.action_type == ActionType.KITCHEN_REPURPOSE]
    recipes = _fetch_by_ids("recipes", "recipe_id", {t.target_recipe_id for _, t in kitchen_tasks},
                            "recipe_id, department_id, estimated_prep_time_mins, is_active")
    needed: dict[tuple[str, date], float] = defaultdict(float)
    for i, task in kitchen_tasks:
        recipe = recipes.get(task.target_recipe_id)
        if recipe is None or not recipe["is_active"]:
            raise HTTPException(422, f"tasks[{i}]: recipe '{task.target_recipe_id}' not found or inactive")
        if not recipe["department_id"] or not recipe["estimated_prep_time_mins"]:
            raise HTTPException(422, f"tasks[{i}]: recipe '{task.target_recipe_id}' has no department or prep time")
        hours = recipe["estimated_prep_time_mins"] * task.batch_count / 60
        needed[(recipe["department_id"], _booking_date(task.due_by))] += hours
    return {key: round(hrs, 2) for key, hrs in needed.items()}


def _release_all(bookings: list[dict]) -> None:
    for b in bookings:
        release_hours(b["department_id"], date.fromisoformat(b["date"]), b["hours"])


def create_tasks(tasks: list[TaskCreate]) -> dict:
    """สร้าง task หลายรายการ ถ้ามี task ครัวจะจองชั่วโมงครัวให้ก่อน
    ถ้าจองไม่ได้หรือ insert ไม่สำเร็จ จะคืนชั่วโมงที่จองไปแล้วทั้งหมด และไม่มี task ไหนถูกสร้าง"""
    rows = _build_rows(tasks)
    hours_needed = _kitchen_hours_needed(tasks)

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
        raise HTTPException(400, f"Failed to create tasks: {e.message}")

    return {"created": len(res.data), "tasks": res.data, "kitchen_bookings": booked}
