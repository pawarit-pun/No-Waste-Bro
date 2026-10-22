"""รายการ lot ปัจจุบันสำหรับหน้า Inventory ของ dashboard (อ่านอย่างเดียว)"""
from datetime import date

from core.dates import today_bkk
from db.helpers import fetch_all, fetch_by_ids
from schemas.enums import ActionType, ReviewStatus, TaskStatus

LOT_COLUMNS = ("lot_id, product_id, received_date, expiration_date, initial_quantity, current_quantity, "
               "unit_cost, location_aisle, location_shelf, ai_status, current_selling_price, "
               "last_price_changed_at, source_task_id, created_at")

# lot ที่เกิดจาก task (complete_task) → ที่มาของ lot
ORIGIN_BY_ACTION = {
    ActionType.MARKDOWN.value: "MARKDOWN_SPLIT",      # ส่วนที่แยกออกมาลดราคา
    ActionType.KITCHEN_REPURPOSE.value: "KITCHEN_OUTPUT",  # ผลผลิตจากครัว
}


def list_lots(include_empty: bool) -> dict:
    """lot ทั้งหมด (ค่าเริ่มต้นเฉพาะที่ยังมีของ) เรียงตามวันหมดอายุ พร้อมสินค้า ผลสแกนล่าสุด ที่มา และงานที่ค้าง"""
    today = today_bkk()
    filters = [] if include_empty else [("gt", "current_quantity", 0)]
    lots = fetch_all("inventory_lots", LOT_COLUMNS, filters=filters, order_by=("expiration_date", "lot_id"))
    if not lots:
        return {"reference_date": today.isoformat(), "items": []}
    lot_ids = [l["lot_id"] for l in lots]

    products = fetch_by_ids("products", "product_id", {l["product_id"] for l in lots},
                            "product_id, name, category, unit_of_measure, regular_price, image_url")
    source_tasks = fetch_by_ids("ai_recommended_tasks", "task_id", {l.get("source_task_id") for l in lots},
                                "task_id, action_type")

    # ผลสแกนล่าสุดของแต่ละ lot (เรียงเก่า → ใหม่ แล้วให้แถวหลังทับแถวก่อน)
    latest: dict[str, dict] = {}
    for a in fetch_all("lot_risk_assessments", "lot_id, risk_level, risk_score, days_to_expiry, assessed_at",
                       in_filter=("lot_id", lot_ids), order_by=("assessed_at", "assessment_id")):
        latest[a["lot_id"]] = a

    waiting: dict[str, int] = {}
    for r in fetch_all("pending_tasks", "lot_id", in_filter=("lot_id", lot_ids),
                       filters=[("eq", "review_status", ReviewStatus.WAITING.value)]):
        waiting[r["lot_id"]] = waiting.get(r["lot_id"], 0) + 1

    open_tasks: dict[str, int] = {}
    for t in fetch_all("ai_recommended_tasks", "lot_id", in_filter=("lot_id", lot_ids),
                       filters=[("in_", "task_status", [TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value])]):
        open_tasks[t["lot_id"]] = open_tasks.get(t["lot_id"], 0) + 1

    for l in lots:
        src = source_tasks.get(str(l.get("source_task_id")))
        l["product"] = products.get(l["product_id"])
        l["days_left"] = (date.fromisoformat(l["expiration_date"]) - today).days
        l["origin"] = "SUPPLIER" if not l.get("source_task_id") else ORIGIN_BY_ACTION.get(
            (src or {}).get("action_type"), "TASK_OUTPUT")
        l["latest_assessment"] = latest.get(l["lot_id"])
        l["waiting_plans"] = waiting.get(l["lot_id"], 0)
        l["open_tasks"] = open_tasks.get(l["lot_id"], 0)
    return {"reference_date": today.isoformat(), "items": lots}
