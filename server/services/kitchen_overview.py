"""หน้า Kitchen ของ dashboard: ความจุครัว + งานครัว + plan ครัวที่รออนุมัติ + ความต้องการเมนู (อ่านอย่างเดียว)

ชั่วโมงของงานคิดด้วย kitchen_booking_of ตัวเดียวกับตอนจอง/คืนครัว จึงตรงกับ booked_hrs ของ kitchen_capacity_daily
"""
from datetime import timedelta

from fastapi import HTTPException

from core.dates import today_bkk
from db.helpers import fetch_by_ids
from db.supabase import supabase
from schemas.enums import ActionType, ReviewStatus, TaskStatus
from services.tasks import RECIPE_BOOKING_COLUMNS, kitchen_booking_of

KITCHEN = ActionType.KITCHEN_REPURPOSE.value
JOB_STATUSES = [TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value, TaskStatus.COMPLETED.value,
                TaskStatus.REJECTED.value]
RECIPE_COLUMNS = RECIPE_BOOKING_COLUMNS + ", name, output_product_id, output_quantity, shelf_life_days"


def _booking(record: dict, recipe: dict | None):
    """(ครัว, วันที่, ชั่วโมง) หรือ None ถ้าสูตรถูกปิด / ข้อมูลไม่ครบ (แสดงงานได้แต่ไม่นับชั่วโมง)"""
    try:
        return kitchen_booking_of(record, recipe)
    except HTTPException:
        return None


def kitchen_overview(days_ahead: int) -> dict:
    start = today_bkk()
    end = start + timedelta(days=days_ahead)
    supabase.rpc("ensure_kitchen_days", {"p_from": start.isoformat(), "p_to": end.isoformat()}).execute()

    departments = supabase.table("kitchen_capacity").select(
        "department_id, department_name, daily_processing_capacity_hrs").order("department_id").execute().data
    days = (supabase.table("kitchen_capacity_daily")
              .select("department_id, capacity_date, available_hrs, booked_hrs, remaining_hrs, workload_status")
              .gte("capacity_date", start.isoformat()).lte("capacity_date", end.isoformat())
              .order("capacity_date").execute().data)
    for d in departments:
        d["days"] = [x for x in days if x["department_id"] == d["department_id"]]
    names = {d["department_id"]: d["department_name"] for d in departments}

    # ---------- task ครัว (กรองตามวันที่จองครัว = วันของ due_by) ----------
    tasks = (supabase.table("ai_recommended_tasks")
               .select("task_id, lot_id, product_id, target_recipe_id, batch_count, action_quantity, due_by, "
                       "task_status, assigned_staff_id, priority, completed_at, actual_quantity_handled, rejection_reason")
               .eq("action_type", KITCHEN).in_("task_status", JOB_STATUSES).execute().data)
    # ---------- plan ครัวที่รออนุมัติ ----------
    waiting = (supabase.table("pending_tasks").select("review_id, decision_id, lot_id, priority, review_deadline")
                 .eq("review_status", ReviewStatus.WAITING.value).execute().data)
    decisions = fetch_by_ids("optimization_decisions", "decision_id", {w["decision_id"] for w in waiting},
                             "decision_id, action_type, target_recipe_id, batch_count, action_quantity, due_by")
    waiting = [dict(w, **{k: v for k, v in decisions[str(w["decision_id"])].items() if k != "decision_id"})
               for w in waiting if decisions.get(str(w["decision_id"]), {}).get("action_type") == KITCHEN]

    recipes = fetch_by_ids("recipes", "recipe_id",
                           {r.get("target_recipe_id") for r in tasks + waiting}, RECIPE_COLUMNS)
    lots = fetch_by_ids("inventory_lots", "lot_id", {r.get("lot_id") for r in tasks + waiting},
                        "lot_id, product_id, location_aisle, location_shelf, expiration_date")
    product_ids = {r.get("product_id") for r in tasks} | {l["product_id"] for l in lots.values()} \
        | {r["output_product_id"] for r in recipes.values()}
    products = fetch_by_ids("products", "product_id", product_ids, "product_id, name, unit_of_measure")
    staff = fetch_by_ids("staff", "staff_id", {t.get("assigned_staff_id") for t in tasks}, "staff_id, full_name, image_url")

    def job(r: dict, kind: str) -> dict | None:
        recipe = recipes.get(r.get("target_recipe_id"))
        booking = _booking(r, recipe)
        on = booking[1] if booking else None
        if on is not None and not (start <= on <= end):
            return None
        lot = lots.get(r.get("lot_id")) or {}
        ingredient = products.get(r.get("product_id") or lot.get("product_id")) or {}
        output = products.get((recipe or {}).get("output_product_id")) or {}
        dep = booking[0] if booking else (recipe or {}).get("department_id")
        return {
            "kind": kind, "id": str(r.get("task_id") or r.get("review_id")), "status": r.get("task_status") or "WAITING",
            "department_id": dep, "department_name": names.get(dep), "date": on.isoformat() if on else None,
            "hours": round(booking[2], 2) if booking else None, "due_by": r.get("due_by"),
            "recipe_id": r.get("target_recipe_id"), "recipe_name": (recipe or {}).get("name"),
            "batch_count": r.get("batch_count"),
            "expected_output": round(float(recipe["output_quantity"]) * r["batch_count"]) if recipe and r.get("batch_count") else None,
            "output_name": output.get("name"), "output_unit": output.get("unit_of_measure"),
            "lot_id": r.get("lot_id"), "ingredient_name": ingredient.get("name"),
            "ingredient_quantity": r.get("action_quantity"), "ingredient_unit": ingredient.get("unit_of_measure"),
            "location": " / ".join(x for x in (lot.get("location_aisle"), lot.get("location_shelf")) if x) or None,
            "priority": r.get("priority"),
            "staff": staff.get(r.get("assigned_staff_id")) if kind == "TASK" else None,
            "completed_at": r.get("completed_at"), "actual_quantity_handled": r.get("actual_quantity_handled"),
            "rejection_reason": r.get("rejection_reason"), "review_deadline": r.get("review_deadline"),
        }

    jobs = [j for j in (job(t, "TASK") for t in tasks) if j]
    jobs += [j for j in (job(w, "WAITING_APPROVAL") for w in waiting) if j]
    jobs.sort(key=lambda j: (j["date"] or "9999", j["due_by"] or "9999", j["recipe_id"] or ""))

    # ---------- ความต้องการเมนูของรอบพยากรณ์ล่าสุด ----------
    menu, run = [], None
    latest = supabase.table("forecast_runs").select("run_id, reference_date, created_at") \
        .order("created_at", desc=True).limit(1).execute().data
    if latest:
        run = latest[0]
        rows = supabase.table("recipe_demand_forecasts").select("*").eq("run_id", run["run_id"]).execute().data
        all_recipes = fetch_by_ids("recipes", "recipe_id", {r["recipe_id"] for r in rows}, RECIPE_COLUMNS)
        outs = fetch_by_ids("products", "product_id", {r["output_product_id"] for r in rows},
                            "product_id, name, unit_of_measure")
        for r in rows:
            rc = all_recipes.get(r["recipe_id"]) or {}
            menu.append({**{k: r[k] for k in ("recipe_id", "output_product_id", "window_from", "window_to",
                                              "gross_demand", "current_stock", "menu_qty", "low_qty", "high_qty",
                                              "expected_revenue")},
                         "recipe_name": rc.get("name"), "department_id": rc.get("department_id"),
                         "department_name": names.get(rc.get("department_id")),
                         "output_name": (outs.get(r["output_product_id"]) or {}).get("name"),
                         "output_unit": (outs.get(r["output_product_id"]) or {}).get("unit_of_measure"),
                         "batch_output": rc.get("output_quantity"), "prep_time_mins": rc.get("estimated_prep_time_mins")})
        menu.sort(key=lambda m: -float(m["expected_revenue"] or 0))

    return {"reference_date": start, "departments": departments, "jobs": jobs, "menu_demand": menu,
            "menu_demand_run": run}
