"""Phase 4: Auto-approve: agent อนุมัติ plan ความเสี่ยงต่ำเองตามกติกาที่ผู้จัดการตั้ง (GET /agent/policies/auto-approve)

เรียกจาก events.handle ก่อน playbook ของ PIPELINE_SUCCEEDED (ก่อน Morning brief) และ WATCH (ทุกชั่วโมง / ปุ่มตรวจ)
โค้ดตัดสินทั้งหมด ไม่มี LLM: กติกาเดียวกับ server/services/auto_approve.py (server ตรวจซ้ำก่อนอนุมัติจริง)
  AA_ACTION AA_DISCOUNT AA_PRICE AA_VALUE AA_NOT_BEST AA_TEMPLATE AA_EXPIRED AA_DEADLINE AA_UNDONE AA_LOT AA_LIMIT
ผล: POST /agent/auto-approve แล้วแจ้งเตือนผู้จัดการ "AI อนุมัติเอง N plan" พร้อมเวลาที่ย้อนได้
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .labels import ACTION_TH

BKK = ZoneInfo("Asia/Bangkok")
ALLOWED_ACTIONS = ("MARKDOWN", "DONATE", "ANIMAL_FEED", "COMPOST", "ANAEROBIC_DIGESTION")
EPS = 0.01
REASON_TH = {
    "AA_ACTION": "วิธีนี้ไม่อยู่ในกติกา", "AA_DISCOUNT": "ลดราคาเกินเพดาน", "AA_PRICE": "ราคาใหม่ต่ำกว่าราคาขั้นต่ำ",
    "AA_VALUE": "มูลค่าเกินเพดาน", "AA_NOT_BEST": "มีทางเลือกอื่นที่กำไรคาดสูงกว่า", "AA_TEMPLATE": "ข้อความเป็น TEMPLATE",
    "AA_EXPIRED": "lot หมดอายุแล้ว", "AA_DEADLINE": "ใกล้เวลาอนุมัติเกินไป", "AA_UNDONE": "ผู้จัดการเคยย้อน",
    "AA_LOT": "plan อื่นของ lot เดียวกันไม่เข้าเกณฑ์", "AA_LIMIT": "เกินจำนวนต่อวัน", "AA_STATUS": "ไม่ได้รออนุมัติแล้ว",
}


def _dt(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=BKK)


def evaluate(r: dict, params: dict, now: datetime) -> tuple[list[str], dict]:
    """-> (รหัสที่ไม่ผ่าน, ตัวเลขที่ใช้ตัดสิน) ของ plan 1 แถว (เหมือน server ทุกบรรทัด)"""
    d = r.get("decision") or {}
    fails, facts = [], {}
    if r.get("review_status", "WAITING") != "WAITING":
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


def select(reviews: list[dict], params: dict, remaining: int, now: datetime) -> tuple[list[dict], list[dict]]:
    """เลือกทั้ง lot -> (lot ที่ผ่าน [{lot_id, reviews:[(row, facts)]}], ที่ข้าม [{review_id, lot_id, reasons}])"""
    by_lot: dict[str, list[dict]] = {}
    for r in reviews:
        by_lot.setdefault(r["lot_id"], []).append(r)
    checked = {str(r["review_id"]): evaluate(r, params, now) for r in reviews}
    lots, skipped = [], []
    for lot_id in sorted(by_lot):
        members = by_lot[lot_id]
        if any(checked[str(m["review_id"])][0] for m in members):
            skipped += [{"review_id": str(m["review_id"]), "lot_id": lot_id,
                         "reasons": checked[str(m["review_id"])][0] or ["AA_LOT"]} for m in members]
            continue
        deadline = min((_dt(m.get("review_deadline")) or now + timedelta(days=30)) for m in members)
        lots.append({"lot_id": lot_id, "deadline": deadline, "reviews": [(m, checked[str(m["review_id"])][1]) for m in members]})
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


# ---------------------------------------------------------------- ข้อมูลจาก server
def candidates(ds) -> list[dict]:
    """plan ที่รออนุมัติ + alternatives ของ decision + ราคาขายปัจจุบันของ lot + ราคาขั้นต่ำของสินค้า"""
    reviews = [dict(r) for r in (ds.reviews() or {}).get("items") or [] if r.get("review_status", "WAITING") == "WAITING"]
    if not reviews:
        return []
    inv = {it["lot_id"]: it for it in ds.inventory().get("items") or []}
    products = {p["product_id"]: p for p in ds.products() or []}
    alts: dict[str, dict] = {}
    for run_id in sorted({str(r.get("run_id")) for r in reviews if r.get("run_id")}):
        for d in (ds.decisions(run_id) or {}).get("decisions") or []:
            alts[str(d["decision_id"])] = d
    for r in reviews:
        full = alts.get(str(r.get("decision_id"))) or {}
        r["decision"] = {**(r.get("decision") or {}), "alternatives": full.get("alternatives") or []}
        lot = inv.get(r["lot_id"]) or {}
        r["lot_price"] = lot.get("current_selling_price")
        pid = lot.get("product_id") or (r.get("product") or {}).get("product_id")
        r["min_allowed_price"] = (products.get(pid) or {}).get("min_allowed_price")
    return reviews


def _summary_reason(reviews: list[tuple[dict, dict]]) -> str:
    out = []
    for r, f in reviews[:3]:
        d = r.get("decision") or {}
        a = ACTION_TH.get(d.get("action_type"), d.get("action_type"))
        out.append(f"{r['lot_id']} {a}" + (f" {f['discount_pct']:g}%" if "discount_pct" in f else ""))
    return ", ".join(out) + (" ..." if len(reviews) > 3 else "")


def run(ds, p: dict) -> dict:
    """-> {"notices": [...], "auto": {...} | None, "warnings": [...]}"""
    from .events import Notice, _key            # import ตอนเรียก กัน import วน
    out: dict = {"notices": [], "auto": None, "warnings": []}
    try:
        policy = ds.client.request("GET", "agent/policies/auto-approve")
    except Exception as e:  # noqa: BLE001  ยังไม่ได้รัน auto_approve.sql หรือ server ยังไม่อัปเดต
        out["warnings"].append(f"auto-approve policy: {type(e).__name__}")
        return out
    if not policy or not policy.get("enabled") or not policy.get("owner_staff_id"):
        return out
    params = policy["params"]
    remaining = int((policy.get("today") or {}).get("remaining", params.get("daily_limit", 0)))
    reviews = candidates(ds)
    now = ds.now()
    picked, skipped = select(reviews, params, remaining, now)
    out["auto"] = {"considered": len(reviews), "picked_lots": [l["lot_id"] for l in picked],
                   "skipped": skipped, "approved": 0, "review_ids": [], "today": policy.get("today")}
    if not picked:
        return out
    ids = [str(m["review_id"]) for lot in picked for m, _ in lot["reviews"]]
    res = ds.client.request("POST", "agent/auto-approve", body={"review_ids": ids}) or {}
    approved = res.get("reviews") or []
    out["auto"].update(approved=res.get("approved", len(approved)), review_ids=[str(r["review_id"]) for r in approved],
                       lots=res.get("lots") or [], server_skipped=res.get("skipped") or [],
                       errors=res.get("errors") or [], today=res.get("today") or policy.get("today"))
    ds.invalidate("reviews", "inventory", "tasks")
    if not approved:
        return out
    lots = res.get("lots") or sorted({r["lot_id"] for r in approved})
    done = {str(r["review_id"]) for r in approved}
    ok = [(m, f) for lot in picked for m, f in lot["reviews"] if str(m["review_id"]) in done]
    undo = int(res.get("undo_minutes") or params.get("undo_minutes") or 15)
    owner = (policy.get("owner") or {}).get("full_name") or policy["owner_staff_id"]
    value = round(sum(f["value_thb"] for _, f in ok), 2)
    profit = round(sum(f["expected_profit_thb"] for _, f in ok), 2)
    facts = {"เหตุการณ์": "AI อนุมัติ plan ที่เข้าเกณฑ์ Auto-approve เอง", "เจ้าของกติกา": owner,
             "จำนวน plan": len(approved), "จำนวน lot": len(lots), "lot": lots[:10],
             "งาน": _summary_reason(ok), "มูลค่าสินค้ารวม (บาท)": value, "กำไรคาดรวม (บาท)": profit,
             "ย้อนได้ภายใน (นาที)": undo, "plan ที่ไม่เข้าเกณฑ์": len(skipped) or None,
             "อนุมัติวันนี้แล้ว": (res.get("today") or {}).get("approved")}
    tmpl = (f"AI อนุมัติเอง {len(approved)} plan ({len(lots)} lot: {', '.join(lots[:5])}{' ...' if len(lots) > 5 else ''}) "
            f"ตามกติกาของ {owner} ส่งงานให้พนักงานแล้ว ย้อนกลับได้ใน {undo} นาทีที่หน้า Review queue")
    out["notices"].append(Notice(_key("AUTO_APPROVE", *sorted(done)), "INFO", f"AI อนุมัติเอง {len(approved)} plan",
                                 facts, tmpl, "AUTO_APPROVE", lots[0] if len(lots) == 1 else None))
    return out
