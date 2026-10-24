"""Phase 4: Auto-approve: Manager Agent อนุมัติ plan ความเสี่ยงต่ำเองตามกติกาที่ผู้จัดการตั้ง

agent (AI/manager_agent/autoapprove.py) เลือก plan ที่เข้าเกณฑ์ แล้วเรียก POST /agent/auto-approve
server ตรวจกติกาเดิมซ้ำทุกข้อกับข้อมูลล่าสุด (ไม่เชื่อ agent) แล้วใช้ approve() เดิมของ Review queue
reviewed_by = ผู้จัดการเจ้าของกติกา (FK staff) และ approved_by_agent = true
ผู้จัดการย้อนได้ภายใน undo_minutes ถ้า task ยังไม่มีใครเริ่ม (PENDING)

กติกา (ต้องผ่านทุกข้อ ไม่มี LLM ตัดสิน)
  AA_ACTION     วิธีอยู่ใน actions (ไม่มีงานครัว / ฝังกลบ / ทิ้ง ให้เลือก: ใช้ชั่วโมงครัวหรือย้อนไม่ได้)
  AA_DISCOUNT   ลดราคาไม่เกิน max_discount_pct
  AA_PRICE      ราคาใหม่ไม่ต่ำกว่า min_allowed_price ของสินค้า
  AA_VALUE      action_quantity × ราคาขายปัจจุบันของ lot ไม่เกิน max_value_thb
  AA_NOT_BEST   ทางเลือกอื่นของ Optimizer ที่ทำได้ ไม่มีทางไหนกำไรคาดสูงกว่า
  AA_TEMPLATE   ข้อความของ plan เขียนโดย LLM ที่ผ่าน validation (ไม่ใช่ TEMPLATE)
  AA_EXPIRED    lot ยังไม่หมดอายุ
  AA_DEADLINE   เหลือเวลาก่อน review_deadline อย่างน้อย min_minutes_before_deadline
  AA_UNDONE     ผู้จัดการเคยย้อนการอนุมัติของ agent สำหรับ plan นี้
  AA_LOT        plan อื่นที่รออนุมัติของ lot เดียวกันไม่เข้าเกณฑ์ (อนุมัติทั้ง lot หรือไม่อนุมัติเลย)
  AA_LIMIT      เกินจำนวนต่อวัน (daily_limit นับตามวันจริงของเวลาไทย)
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from core.dates import BKK, now_bkk
from db.helpers import fetch_by_ids
from db.supabase import supabase
from schemas.enums import ReviewStatus, TaskStatus

TABLE = "agent_policies"
POLICY_ID = "AUTO_APPROVE"
ALLOWED_ACTIONS = ("MARKDOWN", "DONATE", "ANIMAL_FEED", "COMPOST", "ANAEROBIC_DIGESTION")
DEFAULTS = {"actions": ["MARKDOWN"], "max_discount_pct": 30, "max_value_thb": 2000,
            "min_minutes_before_deadline": 30, "daily_limit": 30, "undo_minutes": 15}
ACTION_TH = {"MARKDOWN": "ลดราคา", "DONATE": "บริจาค", "ANIMAL_FEED": "ส่งทำอาหารสัตว์", "COMPOST": "ส่งทำปุ๋ย",
             "ANAEROBIC_DIGESTION": "ส่งทำก๊าซชีวภาพ"}
REASON_TH = {
    "AA_ACTION": "วิธีนี้ไม่อยู่ในกติกา", "AA_DISCOUNT": "ลดราคาเกินเพดาน", "AA_PRICE": "ราคาใหม่ต่ำกว่าราคาขั้นต่ำ",
    "AA_VALUE": "มูลค่าเกินเพดาน", "AA_NOT_BEST": "มีทางเลือกอื่นที่กำไรคาดสูงกว่า",
    "AA_TEMPLATE": "ข้อความเป็น TEMPLATE (LLM ไม่ผ่าน validation)", "AA_EXPIRED": "lot หมดอายุแล้ว",
    "AA_DEADLINE": "ใกล้เวลาอนุมัติเกินไป", "AA_UNDONE": "ผู้จัดการเคยย้อนการอนุมัติของ AI",
    "AA_LOT": "plan อื่นของ lot เดียวกันไม่เข้าเกณฑ์", "AA_LIMIT": "เกินจำนวนต่อวัน", "AA_STATUS": "ไม่ได้รออนุมัติแล้ว",
}
EPS = 0.01


def _dt(v) -> Optional[datetime]:
    if not v:
        return None
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=BKK)


# ---------------------------------------------------------------- กติกา
def params_of(row: Optional[dict]) -> dict:
    return {**DEFAULTS, **((row or {}).get("params") or {})}


def load_policy() -> dict:
    res = supabase.table(TABLE).select("*").eq("policy_id", POLICY_ID).execute().data
    row = res[0] if res else {"policy_id": POLICY_ID, "enabled": False, "params": {}, "owner_staff_id": None,
                              "updated_at": None}
    return {**row, "params": params_of(row)}


def _day_start() -> str:
    """เริ่มวันตามนาฬิกาจริง (reviewed_at เป็นเวลาจริง ไม่ใช่ DEMO_DATE)"""
    now = datetime.now(BKK)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()


def today_stats(params: dict) -> dict:
    rows = (supabase.table("pending_tasks").select("review_id, lot_id")
              .eq("approved_by_agent", True).gte("reviewed_at", _day_start()).execute().data)
    return {"approved": len(rows), "lots": len({r["lot_id"] for r in rows}),
            "remaining": max(0, int(params["daily_limit"]) - len(rows))}


def get_policy() -> dict:
    p = load_policy()
    owner = None
    if p.get("owner_staff_id"):
        owner = fetch_by_ids("staff", "staff_id", [p["owner_staff_id"]], "staff_id, full_name, image_url").get(p["owner_staff_id"])
    return {**p, "owner": owner, "allowed_actions": list(ALLOWED_ACTIONS), "today": today_stats(p["params"])}


def put_policy(manager_id: str, enabled: bool, params: dict) -> dict:
    from services.pending_tasks import _check_manager
    _check_manager(manager_id)
    bad = [a for a in params.get("actions") or [] if a not in ALLOWED_ACTIONS]
    if bad:
        raise HTTPException(422, f"actions not allowed for auto-approve: {bad}")
    if enabled and not params.get("actions"):
        raise HTTPException(422, "Pick at least one action to turn auto-approve on")
    row = {"policy_id": POLICY_ID, "enabled": enabled, "params": {**DEFAULTS, **params}, "owner_staff_id": manager_id,
           "updated_at": datetime.now(timezone.utc).isoformat()}
    supabase.table(TABLE).upsert(row, on_conflict="policy_id").execute()
    return get_policy()


def evaluate(r: dict, params: dict, now: datetime) -> tuple[list[str], dict]:
    """-> (รหัสที่ไม่ผ่าน, ตัวเลขที่ใช้ตัดสิน) ของ plan 1 แถว
    r ต้องมี: decision (พร้อม alternatives), lot_price, min_allowed_price, lot_expired, model_used, review_deadline"""
    d = r.get("decision") or {}
    fails, facts = [], {}
    if r.get("review_status") != ReviewStatus.WAITING.value:
        fails.append("AA_STATUS")
    if r.get("agent_undone_at"):
        fails.append("AA_UNDONE")
    action = d.get("action_type")
    if action not in params["actions"] or action not in ALLOWED_ACTIONS:
        fails.append("AA_ACTION")
    if action == "MARKDOWN":
        disc = float(d.get("discount_pct") or 0)
        facts["discount_pct"] = disc
        if disc > float(params["max_discount_pct"]) + 1e-9:
            fails.append("AA_DISCOUNT")
        floor = r.get("min_allowed_price")
        if floor is not None and d.get("new_recommended_price") is not None \
                and float(d["new_recommended_price"]) < float(floor) - 1e-9:
            fails.append("AA_PRICE")
    value = round((d.get("action_quantity") or 0) * float(r.get("lot_price") or 0), 2)
    facts["value_thb"] = value
    if value > float(params["max_value_thb"]) + 1e-9:
        fails.append("AA_VALUE")
    mine = float(d.get("expected_profit_impact") or 0)
    facts["expected_profit_thb"] = mine
    feasible = [float(a["expected_profit_impact"]) for a in d.get("alternatives") or []
                if a.get("expected_profit_impact") is not None and a.get("feasible", True) is not False
                and not a.get("rejected_because") and a.get("scope") != "WHOLE_LOT"]
    facts["best_alternative_thb"] = max(feasible) if feasible else None
    if feasible and max(feasible) > mine + EPS:
        fails.append("AA_NOT_BEST")
    if not r.get("model_used") or str(r["model_used"]).upper() == "TEMPLATE":
        fails.append("AA_TEMPLATE")
    if r.get("lot_expired"):
        fails.append("AA_EXPIRED")
    dl = _dt(r.get("review_deadline"))
    if dl is not None:
        mins = int((dl - now).total_seconds() // 60)
        facts["minutes_left"] = mins
        if mins < int(params["min_minutes_before_deadline"]):
            fails.append("AA_DEADLINE")
    return fails, facts


def reason_text(d: dict, facts: dict, params: dict) -> str:
    action = d.get("action_type")
    head = ACTION_TH.get(action, action)
    if action == "MARKDOWN":
        head += f" {facts.get('discount_pct', 0):g}% (เพดาน {float(params['max_discount_pct']):g}%)"
    parts = [head]
    parts.append(f"มูลค่า {facts['value_thb']:,.2f} บาท (เพดาน {float(params['max_value_thb']):,.0f})")
    parts.append(f"กำไรคาด {facts['expected_profit_thb']:,.2f} บาท ไม่มีทางเลือกที่ดีกว่า")
    if facts.get("minutes_left") is not None:
        parts.append(f"เหลือเวลา {facts['minutes_left']} นาที")
    return " · ".join(parts)


def select(rows: list[dict], waiting_by_lot: dict[str, list[dict]], params: dict, remaining: int,
           now: datetime) -> tuple[list[dict], list[dict]]:
    """เลือกทั้ง lot: -> (lot ที่อนุมัติได้ [{lot_id, reviews:[(row, facts)]}], ที่ข้าม [{review_id, lot_id, reasons}])
    lot เรียงตามเวลาอนุมัติที่ใกล้ที่สุดก่อน แล้วตัดเมื่อเกิน remaining"""
    checked = {str(r["review_id"]): evaluate(r, params, now) for rows_ in waiting_by_lot.values() for r in rows_}
    for r in rows:
        checked.setdefault(str(r["review_id"]), evaluate(r, params, now))
    lots, skipped = [], []
    for lot_id in sorted({r["lot_id"] for r in rows}):
        members = waiting_by_lot.get(lot_id) or [r for r in rows if r["lot_id"] == lot_id]
        bad = [m for m in members if checked[str(m["review_id"])][0]]
        if bad:
            for m in members:
                own = checked[str(m["review_id"])][0]
                skipped.append({"review_id": str(m["review_id"]), "lot_id": lot_id, "reasons": own or ["AA_LOT"]})
            continue
        deadline = min((_dt(m.get("review_deadline")) or now + timedelta(days=30)) for m in members)
        lots.append({"lot_id": lot_id, "deadline": deadline,
                     "reviews": [(m, checked[str(m["review_id"])][1]) for m in members]})
    lots.sort(key=lambda x: (x["deadline"], x["lot_id"]))
    picked, used = [], 0
    for lot in lots:
        if used + len(lot["reviews"]) > remaining:
            skipped += [{"review_id": str(m["review_id"]), "lot_id": lot["lot_id"], "reasons": ["AA_LIMIT"]}
                        for m, _ in lot["reviews"]]
            continue
        used += len(lot["reviews"])
        picked.append(lot)
    return picked, skipped


# ---------------------------------------------------------------- โหลดข้อมูล plan
def _with_context(rows: list[dict]) -> list[dict]:
    from services.pending_tasks import _attach_context
    rows = _attach_context(rows, detail=True)
    lots = fetch_by_ids("inventory_lots", "lot_id", {r["lot_id"] for r in rows}, "lot_id, product_id, current_selling_price")
    products = fetch_by_ids("products", "product_id", {l["product_id"] for l in lots.values()},
                            "product_id, min_allowed_price")
    for r in rows:
        lot = lots.get(r["lot_id"]) or {}
        r["lot_price"] = lot.get("current_selling_price")
        r["min_allowed_price"] = (products.get(lot.get("product_id")) or {}).get("min_allowed_price")
    return rows


def auto_approve(review_ids: list, agent_run_id: Optional[str] = None) -> dict:
    """route ภายในของ agent: ตรวจกติกาซ้ำแล้วอนุมัติทีละ lot (lot หนึ่งล้ม lot อื่นยังอนุมัติได้)"""
    from services.pending_tasks import approve
    policy = load_policy()
    params = policy["params"]
    if not policy.get("enabled"):
        raise HTTPException(409, "Auto-approve is turned off")
    if not policy.get("owner_staff_id"):
        raise HTTPException(409, "Auto-approve has no owner manager")
    ids = list(dict.fromkeys(str(i) for i in review_ids))
    found = fetch_by_ids("pending_tasks", "review_id", ids)
    missing = [i for i in ids if i not in found]
    rows = [found[i] for i in ids if i in found]
    lot_ids = sorted({r["lot_id"] for r in rows})
    waiting = (supabase.table("pending_tasks").select("*").in_("lot_id", lot_ids)
                 .eq("review_status", ReviewStatus.WAITING.value).execute().data) if lot_ids else []
    ctx = {str(r["review_id"]): r for r in _with_context([*rows, *[w for w in waiting if str(w["review_id"]) not in found]])}
    rows = [ctx[str(r["review_id"])] for r in rows]
    by_lot: dict[str, list[dict]] = {}
    for w in waiting:
        by_lot.setdefault(w["lot_id"], []).append(ctx[str(w["review_id"])])
    # lot ต้องส่งมาครบทุก plan ที่รอ (agent เลือกทั้ง lot)
    stats = today_stats(params)
    picked, skipped = select(rows, by_lot, params, stats["remaining"], now_bkk())
    skipped += [{"review_id": i, "lot_id": None, "reasons": ["AA_STATUS"]} for i in missing]

    owner = fetch_by_ids("staff", "staff_id", [policy["owner_staff_id"]], "staff_id, full_name").get(policy["owner_staff_id"]) or {}
    approved, tasks, errors = [], [], []
    for lot in picked:
        reasons = "; ".join(reason_text(m["decision"] or {}, f, params) for m, f in lot["reviews"])
        note = f"อนุมัติอัตโนมัติตามกติกาของ {owner.get('full_name') or policy['owner_staff_id']}: {reasons}"[:1000]
        try:
            res = approve([m["review_id"] for m, _ in lot["reviews"]], policy["owner_staff_id"], note,
                          approved_by_agent=True, agent_run_id=agent_run_id)
        except HTTPException as e:
            errors.append({"lot_id": lot["lot_id"], "status": e.status_code, "detail": str(e.detail)[:300]})
            continue
        approved += res["reviews"]
        tasks += res["tasks"]
    return {"approved": len(approved), "lots": sorted({r["lot_id"] for r in approved}), "reviews": approved,
            "tasks": tasks, "skipped": skipped, "errors": errors, "undo_minutes": int(params["undo_minutes"]),
            "today": today_stats(params)}


def link_run(review_ids: list[str], agent_run_id: str) -> None:
    """POST /agent/runs: ผูก plan ที่ agent อนุมัติในรอบนี้กับ agent_run_id (agent เรียกอนุมัติก่อนบันทึกรอบ)"""
    if review_ids:
        (supabase.table("pending_tasks").update({"agent_run_id": agent_run_id})
           .in_("review_id", review_ids).eq("approved_by_agent", True).execute())


# ---------------------------------------------------------------- ย้อน (ผู้จัดการ)
def undo_until(row: dict, undo_minutes: int) -> Optional[str]:
    at = _dt(row.get("reviewed_at"))
    return (at + timedelta(minutes=undo_minutes)).isoformat() if row.get("approved_by_agent") and at else None


def attach_undo(rows: list[dict]) -> list[dict]:
    """แนบ undo_until ให้ plan ที่ agent อนุมัติ (dashboard นับถอยหลัง)"""
    if not any(r.get("approved_by_agent") for r in rows):
        return rows
    try:
        minutes = int(load_policy()["params"]["undo_minutes"])
    except Exception:  # noqa: BLE001  ยังไม่ได้รัน auto_approve.sql
        minutes = DEFAULTS["undo_minutes"]
    for r in rows:
        r["undo_until"] = undo_until(r, minutes)
    return rows


def undo(review_id: str, staff_id: str) -> dict:
    """ย้อนการอนุมัติของ agent ทั้งชุดของ lot นั้น: ลบ task (ยังไม่มีใครเริ่ม) แล้ว plan กลับเป็น WAITING"""
    from services.pending_tasks import _check_manager
    from services.tasks import delete_tasks
    _check_manager(staff_id)
    res = supabase.table("pending_tasks").select("*").eq("review_id", review_id).execute().data
    if not res:
        raise HTTPException(404, f"review_id '{review_id}' not found")
    row = res[0]
    if not row.get("approved_by_agent") or row["review_status"] != ReviewStatus.APPROVED.value:
        raise HTTPException(409, "This plan was not approved by the agent")
    minutes = int(load_policy()["params"]["undo_minutes"])
    if datetime.now(timezone.utc) > _dt(row["reviewed_at"]) + timedelta(minutes=minutes):
        raise HTTPException(409, f"Undo is only possible within {minutes} minutes of the agent's approval")
    group = (supabase.table("pending_tasks").select("*").eq("lot_id", row["lot_id"]).eq("approved_by_agent", True)
               .eq("reviewed_at", row["reviewed_at"]).execute().data)
    task_ids = [str(g["task_id"]) for g in group if g.get("task_id")]
    tasks = fetch_by_ids("ai_recommended_tasks", "task_id", task_ids, "task_id, task_status")
    started = [t for t in tasks.values() if t["task_status"] != TaskStatus.PENDING.value]
    if started:
        raise HTTPException(409, "Staff already started or finished the task, undo is not possible")
    ids = [str(g["review_id"]) for g in group]
    reverted = (supabase.table("pending_tasks")
                  .update({"review_status": ReviewStatus.WAITING.value, "task_id": None, "reviewed_by": None,
                           "reviewed_at": None, "review_note": None, "approved_by_agent": False,
                           "agent_undone_at": datetime.now(timezone.utc).isoformat()})
                  .in_("review_id", ids).eq("review_status", ReviewStatus.APPROVED.value).execute().data)
    delete_tasks(task_ids, [])          # กติกาไม่มีงานครัว จึงไม่มีชั่วโมงครัวต้องคืน
    return {"undone": len(reverted), "lot_id": row["lot_id"], "review_ids": ids, "deleted_task_ids": task_ids,
            "undone_by": staff_id}

