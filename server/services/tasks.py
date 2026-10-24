from collections import defaultdict
from datetime import date, datetime

from fastapi import HTTPException
from postgrest.exceptions import APIError

from core.dates import BKK
from db.helpers import fetch_by_ids
from db.supabase import supabase
from schemas.enums import ActionType, DecisionStatus, StaffRole, TaskStatus
from schemas.task import TaskCreate
from services.decisions import STATUS_VIEW
from services.agent_events import emit_event
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


def _load_decisions(tasks: list[TaskCreate], allowed_statuses: tuple[str, ...]) -> dict[str, dict]:
    ids = [str(t.decision_id) for t in tasks]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Each decision_id can appear only once per request")

    decisions = fetch_by_ids(STATUS_VIEW, "decision_id", ids)
    for i, decision_id in enumerate(ids):
        d = decisions.get(decision_id)
        if d is None:
            raise HTTPException(422, f"tasks[{i}]: decision_id '{decision_id}' not found")
        if d["status"] not in allowed_statuses:
            if d.get("task_id"):
                raise HTTPException(409, f"tasks[{i}]: decision '{decision_id}' already has task '{d['task_id']}'")
            raise HTTPException(409, f"tasks[{i}]: decision '{decision_id}' is {d['status']}")
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


OPEN_STATUSES = [TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value]


def _assign_staff(rows: list[dict]) -> None:
    """มอบหมาย task ให้ staff ที่รับผิดชอบหมวดสินค้า (ใส่ assigned_staff_id ในแถวก่อน insert)
    มีหลายคน → คนที่มีงานค้าง (PENDING + IN_PROGRESS) น้อยสุด ถ้าเท่ากันเลือกตาม staff_id
    ไม่มีใครดูแลหมวดนั้น → None (manager จัดการเอง)"""
    products = fetch_by_ids("products", "product_id", {r["product_id"] for r in rows}, "product_id, category")
    staff = (supabase.table("staff").select("staff_id, responsible_categories")
               .eq("role", StaffRole.STAFF.value).eq("is_active", True).execute()).data
    open_tasks = (supabase.table("ai_recommended_tasks").select("assigned_staff_id")
                    .in_("task_status", OPEN_STATUSES).not_.is_("assigned_staff_id", "null")
                    .execute()).data
    workload: dict[str, int] = defaultdict(int)
    for t in open_tasks:
        workload[t["assigned_staff_id"]] += 1

    for row in rows:
        category = products[row["product_id"]]["category"]
        candidates = [s["staff_id"] for s in staff if category in s["responsible_categories"]]
        if not candidates:
            row["assigned_staff_id"] = None
            continue
        chosen = min(candidates, key=lambda staff_id: (workload[staff_id], staff_id))
        row["assigned_staff_id"] = chosen
        workload[chosen] += 1   # นับงานที่เพิ่งมอบในคำขอนี้ด้วย ให้กระจายงานได้


def kitchen_booking_of(record: dict, recipe: dict | None) -> tuple[str, date, float]:
    """(ครัว, วันที่, ชั่วโมง) ของงานครัว 1 รายการ (decision หรือ task) ใช้ทั้งตอนจองและตอนคืน"""
    if recipe is None or not recipe["is_active"]:
        raise HTTPException(422, f"recipe '{record['target_recipe_id']}' not found or inactive")
    if not recipe["department_id"] or not recipe["estimated_prep_time_mins"]:
        raise HTTPException(422, f"recipe '{record['target_recipe_id']}' has no department or prep time")
    hours = recipe["estimated_prep_time_mins"] * record["batch_count"] / 60
    return recipe["department_id"], _booking_date(record["due_by"]), hours


RECIPE_BOOKING_COLUMNS = "recipe_id, department_id, estimated_prep_time_mins, is_active"


def _kitchen_hours_needed(decisions: list[dict]) -> dict[tuple[str, date], float]:
    """รวมชั่วโมงครัวที่ต้องจองแยกตาม (department_id, วันที่) คำนวณจากสูตร × batch_count ของ decision"""
    kitchen = [d for d in decisions if d["action_type"] == ActionType.KITCHEN_REPURPOSE.value]
    recipes = fetch_by_ids("recipes", "recipe_id", {d["target_recipe_id"] for d in kitchen}, RECIPE_BOOKING_COLUMNS)
    needed: dict[tuple[str, date], float] = defaultdict(float)
    for d in kitchen:
        department_id, on, hours = kitchen_booking_of(d, recipes.get(d["target_recipe_id"]))
        needed[(department_id, on)] += hours
    return {key: round(hrs, 2) for key, hrs in needed.items()}


def _release_all(bookings: list[dict]) -> None:
    for b in bookings:
        release_hours(b["department_id"], date.fromisoformat(b["date"]), b["hours"])


def insert_tasks(tasks: list[TaskCreate],
                 allowed_statuses: tuple[str, ...] = (DecisionStatus.IN_REVIEW.value,)) -> dict:
    """เปลี่ยน decision เป็น task ถ้ามี task ครัวจะจองชั่วโมงครัวให้ก่อน
    ถ้าจองไม่ได้หรือ insert ไม่สำเร็จ จะคืนชั่วโมงที่จองไปแล้วทั้งหมด และไม่มี task ไหนถูกสร้าง
    เรียกจากการอนุมัติใน Review queue เท่านั้น (decision ต้องเป็น IN_REVIEW) ไม่มี route ให้ LLM สร้าง task ตรงๆ แล้ว"""
    decisions = _load_decisions(tasks, allowed_statuses)
    rows = _build_rows(tasks, decisions)
    _assign_staff(rows)   # ต้องอยู่ก่อน insert เพื่อให้ event Realtime แรกมี assigned_staff_id แล้ว
    hours_needed = _kitchen_hours_needed(list(decisions.values()))

    booked: list[dict] = []
    for (department_id, on), hours in hours_needed.items():
        if not book_hours(department_id, on, hours):
            _release_all(booked)
            # Manager Agent (ไม่รอผล): แจ้งผู้จัดการว่าครัวไหนเต็ม + ผลจำลองถ้าไม่มีครัวนั้น
            emit_event("KITCHEN_FULL", {
                "department_id": department_id, "date": on.isoformat(), "hours_needed": hours,
                "lot_ids": sorted({str(d["lot_id"]) for d in decisions.values()
                                   if d["action_type"] == ActionType.KITCHEN_REPURPOSE.value}),
                "decision_ids": sorted(str(k) for k in decisions),
            })
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


def delete_tasks(task_ids: list[str], bookings: list[dict]) -> None:
    """ย้อน insert_tasks: ลบ task ที่เพิ่งสร้างแล้วคืนชั่วโมงครัว (ใช้ตอนอนุมัติไม่สำเร็จครึ่งทาง)"""
    if task_ids:
        supabase.table("ai_recommended_tasks").delete().in_("task_id", task_ids).execute()
    _release_all(bookings)


# ---------- อ่าน task (คิวงานของ staff / ภาพรวมของ manager) ----------

def _attach_context(tasks: list[dict], detail: bool = False) -> list[dict]:
    """แนบข้อมูลสินค้า, lot, คนที่ได้รับมอบหมาย, ชื่อสูตร (และ assessment / รายละเอียดสูตร / partner ถ้า detail=True)"""
    lot_cols = "lot_id, current_quantity, expiration_date, location_aisle, location_shelf"
    if detail:
        lot_cols += ", product_id, current_selling_price, ai_status"
    lots = fetch_by_ids("inventory_lots", "lot_id", {t.get("lot_id") for t in tasks}, lot_cols)
    products = fetch_by_ids("products", "product_id", {t.get("product_id") for t in tasks},
                            "product_id, name, category, unit_of_measure, image_url"
                            + (", regular_price, min_allowed_price" if detail else ""))
    staff = fetch_by_ids("staff", "staff_id", {t.get("assigned_staff_id") for t in tasks},
                         "staff_id, full_name, image_url")
    recipes = fetch_by_ids("recipes", "recipe_id", {t.get("target_recipe_id") for t in tasks},
                           "recipe_id, name" + (", department_id, output_product_id, output_quantity, "
                                                "estimated_prep_time_mins, shelf_life_days" if detail else ""))
    if detail:
        assessments = fetch_by_ids("lot_risk_assessments", "assessment_id", {t.get("assessment_id") for t in tasks},
                                   "assessment_id, days_to_expiry, quantity_at_assessment, "
                                   "predicted_leftover_units, risk_score, risk_level")
        departments = fetch_by_ids("kitchen_capacity", "department_id",
                                   {r.get("department_id") for r in recipes.values()},
                                   "department_id, department_name")
        for r in recipes.values():
            r["department_name"] = (departments.get(r.get("department_id")) or {}).get("department_name")
        partners = fetch_by_ids("donation_partners", "partner_id", {t.get("target_partner_id") for t in tasks},
                                "partner_id, name, partner_type, pickup_days, pickup_time_start, "
                                "pickup_time_end, contact_name, contact_phone")

    for t in tasks:
        t["lot"] = lots.get(t.get("lot_id"))
        t["product"] = products.get(t.get("product_id"))
        t["assigned_staff"] = staff.get(t.get("assigned_staff_id"))
        t["recipe"] = recipes.get(t.get("target_recipe_id"))
        if detail:
            t["assessment"] = assessments.get(str(t.get("assessment_id")))
            t["partner"] = partners.get(t.get("target_partner_id"))
    return tasks


def list_tasks(staff_id: str | None, statuses: list[str]) -> list[dict]:
    """task เรียงตาม priority → due_by (ว่างไว้ท้าย) → created_at"""
    if staff_id is not None:
        exists = supabase.table("staff").select("staff_id").eq("staff_id", staff_id).execute().data
        if not exists:
            raise HTTPException(404, f"staff_id '{staff_id}' not found")

    query = supabase.table("ai_recommended_tasks").select("*").in_("task_status", statuses)
    if staff_id is not None:
        query = query.eq("assigned_staff_id", staff_id)
    tasks = (query.order("priority")
                  .order("due_by", nullsfirst=False)
                  .order("created_at")
                  .execute()).data
    return _attach_context(tasks)


def get_task(task_id: str) -> dict:
    res = supabase.table("ai_recommended_tasks").select("*").eq("task_id", task_id).execute().data
    if not res:
        raise HTTPException(404, f"task_id '{task_id}' not found")
    return _attach_context(res, detail=True)[0]
