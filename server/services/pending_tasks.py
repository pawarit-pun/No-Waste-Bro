"""Review queue: plan จาก LLM เข้าคิว pending_tasks (WAITING) แล้วรอผู้จัดการอนุมัติ/ปฏิเสธ
task ใน ai_recommended_tasks ถูกสร้างตอนอนุมัติเท่านั้น: ผู้จัดการกดเอง หรือ Manager Agent อนุมัติตามกติกา
Auto-approve ที่ผู้จัดการเปิดไว้ (services/auto_approve.py, approved_by_agent = true)"""
from datetime import date, datetime, time, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from postgrest.exceptions import APIError

from core.dates import BKK, today_bkk
from db.helpers import fetch_all, fetch_by_ids
from db.supabase import supabase
from schemas.enums import DecisionStatus, LotAIStatus, ReviewStatus, StaffRole
from schemas.pending_task import PendingTaskCreate
from schemas.task import TaskCreate
from services.auto_approve import attach_undo
from services.decisions import STATUS_VIEW
from services.tasks import delete_tasks, insert_tasks

TABLE = "pending_tasks"
STORE_CLOSE = time(22, 0)   # ร้านเปิด 08:00-22:00 (เดียวกับ sellable_hours ของ Risk Scanner)
WAITING = ReviewStatus.WAITING.value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- LLM ส่ง plan เข้าคิว ----------

def _deadline(decision: dict, lot: Optional[dict]) -> Optional[str]:
    """เวลาล่าสุดที่ staff ยังทำงานได้: due_by ของ decision หรือ 22:00 ของวันหมดอายุ lot (MARKDOWN ไม่มี due_by)"""
    if decision.get("due_by"):
        return decision["due_by"]
    if lot and lot.get("expiration_date"):
        return datetime.combine(date.fromisoformat(lot["expiration_date"]), STORE_CLOSE, tzinfo=BKK).isoformat()
    return None


def create_pending(items: list[PendingTaskCreate]) -> dict:
    """บันทึก plan ของ LLM เป็น WAITING (ทั้งหมดหรือไม่บันทึกเลย)"""
    ids = [str(t.decision_id) for t in items]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Each decision_id can appear only once per request")

    decisions = fetch_by_ids(STATUS_VIEW, "decision_id", ids)
    for i, decision_id in enumerate(ids):
        d = decisions.get(decision_id)
        if d is None:
            raise HTTPException(422, f"tasks[{i}]: decision_id '{decision_id}' not found")
        if d["status"] != DecisionStatus.PENDING.value:
            raise HTTPException(409, f"tasks[{i}]: decision '{decision_id}' is already {d['status']}")

    lots = fetch_by_ids("inventory_lots", "lot_id", {d["lot_id"] for d in decisions.values()},
                        "lot_id, expiration_date")
    rows = []
    for t in items:
        d = decisions[str(t.decision_id)]
        row = t.model_dump(mode="json", exclude_none=True)
        row.update(run_id=d["run_id"], assessment_id=d["assessment_id"], lot_id=d["lot_id"],
                   review_status=WAITING)
        deadline = _deadline(d, lots.get(d["lot_id"]))
        if deadline:
            row["review_deadline"] = deadline
        rows.append(row)

    try:
        res = supabase.table(TABLE).insert(rows).execute()
    except APIError as e:
        if e.code == "23505":   # decision_id ซ้ำ: มีคนส่ง plan ของ decision นี้ไปก่อน
            raise HTTPException(409, "A plan for one of these decisions is already in the review queue")
        raise HTTPException(400, f"Failed to queue plans: {e.message}")

    return {
        "created": len(res.data),
        "reviews": [{k: r[k] for k in ("review_id", "decision_id", "lot_id")} for r in res.data],
    }


# ---------- อ่านคิว (dashboard) ----------

DECISION_COLS = ("decision_id, action_type, action_quantity, discount_pct, new_recommended_price, "
                 "target_recipe_id, batch_count, target_partner_id, due_by, expected_profit_impact")


def _attach_context(rows: list[dict], detail: bool = False) -> list[dict]:
    """แนบ decision, lot, สินค้า, ความเสี่ยง, สูตร, partner และผู้จัดการที่ review"""
    decisions = fetch_by_ids("optimization_decisions", "decision_id", {r["decision_id"] for r in rows},
                             DECISION_COLS + (", decision_score, alternatives, optimizer_version" if detail else ""))
    lots = fetch_by_ids("inventory_lots", "lot_id", {r["lot_id"] for r in rows},
                        "lot_id, product_id, current_quantity, expiration_date, location_aisle, location_shelf")
    products = fetch_by_ids("products", "product_id", {l["product_id"] for l in lots.values()},
                            "product_id, name, category, unit_of_measure, image_url")
    assessments = fetch_by_ids("lot_risk_assessments", "assessment_id", {r["assessment_id"] for r in rows},
                               "assessment_id, days_to_expiry, quantity_at_assessment, "
                               "predicted_leftover_units, risk_score, risk_level")
    recipes = fetch_by_ids("recipes", "recipe_id", {d.get("target_recipe_id") for d in decisions.values()},
                           "recipe_id, name" + (", department_id, output_product_id, output_quantity, "
                                                "estimated_prep_time_mins, shelf_life_days" if detail else ""))
    partners = fetch_by_ids("donation_partners", "partner_id", {d.get("target_partner_id") for d in decisions.values()},
                            "partner_id, name, partner_type" + (", pickup_days, pickup_time_start, pickup_time_end, "
                                                               "contact_name, contact_phone" if detail else ""))
    reviewers = fetch_by_ids("staff", "staff_id", {r.get("reviewed_by") for r in rows},
                             "staff_id, full_name, image_url")
    if detail:
        departments = fetch_by_ids("kitchen_capacity", "department_id",
                                   {r.get("department_id") for r in recipes.values()},
                                   "department_id, department_name")
        for rc in recipes.values():
            rc["department_name"] = (departments.get(rc.get("department_id")) or {}).get("department_name")

    today = today_bkk()
    for r in rows:
        d = decisions.get(str(r["decision_id"]))
        lot = lots.get(r["lot_id"])
        r["decision"] = d
        r["lot"] = lot
        r["lot_expired"] = bool(lot) and date.fromisoformat(lot["expiration_date"]) < today
        r["product"] = products.get(lot["product_id"]) if lot else None
        r["assessment"] = assessments.get(str(r["assessment_id"]))
        r["recipe"] = recipes.get(d.get("target_recipe_id")) if d else None
        r["partner"] = partners.get(d.get("target_partner_id")) if d else None
        r["reviewer"] = reviewers.get(r.get("reviewed_by"))
    return rows


def _count(status: str, since: Optional[str]) -> int:
    query = supabase.table(TABLE).select("review_id", count="exact").eq("review_status", status)
    if since and status != WAITING:
        query = query.gte("reviewed_at", since)
    return query.limit(1).execute().count or 0


def list_pending(statuses: list[str], reviewed_from: Optional[datetime]) -> dict:
    """plan ตามสถานะ เรียงเก่าก่อน reviewed_from กรองเฉพาะ APPROVED / REJECTED (WAITING ยังไม่มีเวลา review)"""
    since = None
    if reviewed_from is not None:
        since = (reviewed_from if reviewed_from.tzinfo else reviewed_from.replace(tzinfo=BKK)).isoformat()

    rows: list[dict] = []
    if WAITING in statuses:
        rows += fetch_all(TABLE, filters=[("eq", "review_status", WAITING)], order_by=("created_at", "review_id"))
    reviewed = [s for s in statuses if s != WAITING]
    if reviewed:
        rows += fetch_all(TABLE, in_filter=("review_status", reviewed), order_by=("created_at", "review_id"),
                          filters=[("gte", "reviewed_at", since)] if since else [])
    rows.sort(key=lambda r: (r["created_at"], r["lot_id"], str(r["review_id"])))

    counts = {
        "waiting": _count(WAITING, None),
        "approved": _count(ReviewStatus.APPROVED.value, since),
        "rejected": _count(ReviewStatus.REJECTED.value, since),
    }
    return {"reference_date": today_bkk().isoformat(), "counts": counts, "items": attach_undo(_attach_context(rows))}


def get_pending(review_id: str) -> dict:
    res = supabase.table(TABLE).select("*").eq("review_id", review_id).execute().data
    if not res:
        raise HTTPException(404, f"review_id '{review_id}' not found")
    return attach_undo(_attach_context(res, detail=True))[0]


# ---------- ผู้จัดการอนุมัติ / ปฏิเสธ ----------

def _check_manager(manager_id: str) -> None:
    res = (supabase.table("staff").select("staff_id, role, is_active")
             .eq("staff_id", manager_id).execute()).data
    if not res:
        raise HTTPException(404, f"staff_id '{manager_id}' not found")
    if res[0]["role"] != StaffRole.MANAGER.value or not res[0]["is_active"]:
        raise HTTPException(403, f"'{manager_id}' is not an active MANAGER")


def _load_waiting(review_ids: list[UUID]) -> list[dict]:
    """plan ตามลำดับในคำขอ ทุกตัวต้องยังเป็น WAITING"""
    ids = [str(i) for i in review_ids]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Each review_id can appear only once per request")
    found = fetch_by_ids(TABLE, "review_id", ids)
    rows = []
    for review_id in ids:
        r = found.get(review_id)
        if r is None:
            raise HTTPException(404, f"review_id '{review_id}' not found")
        if r["review_status"] != WAITING:
            raise HTTPException(409, f"review '{review_id}' is already {r['review_status']}")
        rows.append(r)
    return rows


def _revert_to_waiting(review_ids: list[str], agent: bool = False) -> None:
    if review_ids:
        extra = {"approved_by_agent": False} if agent else {}
        (supabase.table(TABLE)
           .update({"review_status": WAITING, "task_id": None, "reviewed_by": None,
                    "reviewed_at": None, "review_note": None, **extra})
           .in_("review_id", review_ids).execute())


def approve(review_ids: list[UUID], manager_id: str, note: Optional[str],
            approved_by_agent: bool = False, agent_run_id: Optional[str] = None) -> dict:
    """สร้าง task จริง (มอบหมาย staff + จองครัว) แล้วตั้ง plan เป็น APPROVED ทั้งหมดหรือไม่ทำเลย
    approved_by_agent: เรียกจาก Auto-approve (manager_id = ผู้จัดการเจ้าของกติกา)"""
    _check_manager(manager_id)
    reviews = _load_waiting(review_ids)
    items = [TaskCreate(decision_id=r["decision_id"], priority=r["priority"], ai_reasoning=r.get("ai_reasoning"),
                        staff_instructions=r.get("staff_instructions"), instruction_steps=r.get("instruction_steps"))
             for r in reviews]
    created = insert_tasks(items)   # ครัวเต็ม / decision มี task แล้ว → 409 และไม่มีอะไรถูกสร้าง
    task_by_decision = {str(t["decision_id"]): t["task_id"] for t in created["tasks"]}

    reviewed_at = _now_iso()
    fields = {"review_status": ReviewStatus.APPROVED.value, "reviewed_by": manager_id,
              "reviewed_at": reviewed_at, "review_note": note}
    if approved_by_agent:           # ใส่เฉพาะตอน agent อนุมัติ: DB ที่ยังไม่รัน auto_approve.sql ยังอนุมัติปกติได้
        fields["approved_by_agent"] = True
        if agent_run_id:
            fields["agent_run_id"] = agent_run_id
    done: list[dict] = []
    try:
        for r in reviews:
            res = (supabase.table(TABLE)
                     .update({**fields, "task_id": task_by_decision[str(r["decision_id"])]})
                     .eq("review_id", r["review_id"]).eq("review_status", WAITING)
                     .execute())
            if not res.data:
                raise HTTPException(409, f"review '{r['review_id']}' was changed by another request")
            done.append(res.data[0])
    except Exception as e:
        # ย้อนทั้งหมด: plan กลับเป็น WAITING ก่อน (ปลด task_id) แล้วลบ task + คืนชั่วโมงครัว
        _revert_to_waiting([str(x["review_id"]) for x in done], agent=approved_by_agent)
        delete_tasks(list(task_by_decision.values()), created["kitchen_bookings"])
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(400, f"Failed to approve: {e}")

    return {"approved": len(done), "reviews": done, "tasks": created["tasks"],
            "kitchen_bookings": created["kitchen_bookings"]}


def _reset_lots(rejected: list[dict]) -> list[str]:
    """lot ที่ทุก decision ในรอบนั้นถูกปฏิเสธ → กลับเป็น IDLE ให้ pipeline รอบหน้าวางแผนใหม่
    ข้าม lot ที่ยังมี decision ค้าง (PENDING / IN_REVIEW) หรือมี task แล้ว และแตะเฉพาะ lot ที่เป็น CHECKED"""
    candidates = []
    for lot_id, run_id in sorted({(r["lot_id"], str(r["run_id"])) for r in rejected}):
        others = (supabase.table(STATUS_VIEW).select("decision_id")
                    .eq("lot_id", lot_id).eq("run_id", run_id)
                    .neq("status", DecisionStatus.REJECTED.value).limit(1).execute()).data
        if not others:
            candidates.append(lot_id)
    if not candidates:
        return []
    res = (supabase.table("inventory_lots").update({"ai_status": LotAIStatus.IDLE.value})
             .in_("lot_id", candidates).eq("ai_status", LotAIStatus.CHECKED.value).execute())
    return sorted(r["lot_id"] for r in res.data)


def reject(review_ids: list[UUID], manager_id: str, note: str) -> dict:
    """ตั้ง plan เป็น REJECTED พร้อมเหตุผล ทั้งหมดหรือไม่ทำเลย (ไม่มี task ถูกสร้าง)"""
    _check_manager(manager_id)
    reviews = _load_waiting(review_ids)
    ids = [str(r["review_id"]) for r in reviews]
    res = (supabase.table(TABLE)
             .update({"review_status": ReviewStatus.REJECTED.value, "reviewed_by": manager_id,
                      "reviewed_at": _now_iso(), "review_note": note})
             .in_("review_id", ids).eq("review_status", WAITING)
             .execute())
    if len(res.data) != len(ids):
        _revert_to_waiting([str(r["review_id"]) for r in res.data])
        raise HTTPException(409, "Some plans were changed by another request, nothing was rejected")

    return {"rejected": len(res.data), "reviews": res.data, "lots_reset": _reset_lots(res.data)}
