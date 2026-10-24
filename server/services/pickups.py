"""ตารางรอบรับของของ partner (บริจาค / อาหารสัตว์ / ปุ๋ย / ก๊าซชีวภาพ / ฝังกลบ) + ของที่ต้องส่งมอบในแต่ละรอบ

รอบ = (partner, วัน) ตาม pickup_days (1 = จันทร์ .. 7 = อาทิตย์ แบบเดียวกับ Optimizer) และ pickup_time_start-end
ของในรอบ = task ที่อนุมัติแล้ว (target_partner_id + due_by วันนั้น) + plan ที่ยังรออนุมัติ (decision ของ partner นั้น)
kg จาก net_content (G / ML หาร 1000, KG / L ตามค่า) ค่าใช้จ่ายสูตรเดียวกับ Optimizer (trip_cost_mode = dedicated):
  ค่าเที่ยว = fixed + travel (DONATION คิดแค่ fixed), handling ต่อ kg (DONATION ไม่มี), รับซื้อต่อ kg
อ่านอย่างเดียว ไม่มีตารางใหม่
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Optional

from core.dates import BKK, now_bkk, today_bkk
from db.helpers import fetch_by_ids
from db.supabase import supabase

OPEN_TASK = ("PENDING", "IN_PROGRESS")


def _dt(v) -> Optional[datetime]:
    if not v:
        return None
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return (d if d.tzinfo else d.replace(tzinfo=BKK)).astimezone(BKK)


def _time(v) -> Optional[time]:
    return time.fromisoformat(str(v)) if v else None


def unit_kg(product: Optional[dict]) -> float:
    if not product or not product.get("net_content_value"):
        return 0.0
    return float(product["net_content_value"]) * (1.0 if product.get("net_content_unit") in ("KG", "L") else 0.001)


def _r(x: float, n: int = 2) -> float:
    return round(float(x or 0), n)


def _trip_costs(p: dict, kg: float) -> dict:
    donation = p["partner_type"] == "DONATION"
    trip = float(p.get("fixed_cost_per_trip") or 0) + (0.0 if donation else float(p.get("travel_cost_per_trip") or 0))
    handling = 0.0 if donation else float(p.get("handling_fee_per_kg") or 0) * kg
    buyback = float(p.get("buyback_price_per_kg") or 0) * kg
    return {"trip_cost_thb": _r(trip), "handling_thb": _r(handling), "buyback_thb": _r(buyback),
            "net_cost_thb": _r(trip + handling - buyback)}


def schedule(days_ahead: int) -> dict:
    today = today_bkk()
    end_day = today + timedelta(days=days_ahead)
    now = now_bkk()
    partners = (supabase.table("donation_partners").select("*").eq("is_active", True)
                  .order("partner_type").order("partner_id").execute().data)
    by_pid = {p["partner_id"]: p for p in partners}
    lo = datetime.combine(today, time(0), BKK).isoformat()
    hi = datetime.combine(end_day + timedelta(days=1), time(0), BKK).isoformat()

    # ---------- ของที่อนุมัติแล้ว (task) ----------
    tasks = [t for t in (supabase.table("ai_recommended_tasks").select("*").gte("due_by", lo).execute().data)
             if t.get("target_partner_id") and str(t.get("due_by")) < hi]
    # ---------- plan ที่รออนุมัติ ----------
    waiting = supabase.table("pending_tasks").select("*").eq("review_status", "WAITING").execute().data
    decisions = fetch_by_ids("optimization_decisions", "decision_id", {w["decision_id"] for w in waiting},
                             "decision_id, action_type, action_quantity, target_partner_id, due_by, expected_profit_impact")
    plans = []
    for w in waiting:
        d = decisions.get(str(w["decision_id"]))
        if d and d.get("target_partner_id") and d.get("due_by") and lo <= str(d["due_by"]) < hi:
            plans.append({**w, "decision": d})

    lots = fetch_by_ids("inventory_lots", "lot_id", {x["lot_id"] for x in [*tasks, *plans]},
                        "lot_id, product_id, location_aisle, location_shelf, expiration_date")
    products = fetch_by_ids("products", "product_id",
                            {t.get("product_id") for t in tasks} | {l["product_id"] for l in lots.values()},
                            "product_id, name, category, unit_of_measure, net_content_value, net_content_unit")
    staff = fetch_by_ids("staff", "staff_id", {t.get("assigned_staff_id") for t in tasks}, "staff_id, full_name")

    loads: dict[tuple[str, date], list[dict]] = defaultdict(list)
    for t in tasks:
        due = _dt(t["due_by"])
        prod = products.get(t.get("product_id"))
        loads[(t["target_partner_id"], due.date())].append({
            "source": "TASK", "task_id": t["task_id"], "review_id": None, "lot_id": t["lot_id"],
            "product_name": (prod or {}).get("name"), "unit_of_measure": (prod or {}).get("unit_of_measure"),
            "action_type": t["action_type"], "quantity": t["action_quantity"],
            "kg": _r(t["action_quantity"] * unit_kg(prod), 3), "status": t["task_status"],
            "staff_name": (staff.get(t.get("assigned_staff_id")) or {}).get("full_name"), "due_by": due.isoformat(),
            "location": " / ".join(x for x in [(lots.get(t["lot_id"]) or {}).get("location_aisle"),
                                               (lots.get(t["lot_id"]) or {}).get("location_shelf")] if x) or None,
        })
    for w in plans:
        d = w["decision"]
        due = _dt(d["due_by"])
        lot = lots.get(w["lot_id"]) or {}
        prod = products.get(lot.get("product_id"))
        loads[(d["target_partner_id"], due.date())].append({
            "source": "PLAN", "task_id": None, "review_id": w["review_id"], "lot_id": w["lot_id"],
            "product_name": (prod or {}).get("name"), "unit_of_measure": (prod or {}).get("unit_of_measure"),
            "action_type": d["action_type"], "quantity": d["action_quantity"],
            "kg": _r(d["action_quantity"] * unit_kg(prod), 3), "status": "WAITING_APPROVAL", "staff_name": None,
            "due_by": due.isoformat(),
            "location": " / ".join(x for x in [lot.get("location_aisle"), lot.get("location_shelf")] if x) or None,
        })

    # ---------- รอบตามตาราง + รอบนอกตาราง (ถ้ามี due_by วันที่ partner ไม่ได้มา) ----------
    keys = {(p["partner_id"], today + timedelta(days=i)) for p in partners for i in range(days_ahead + 1)
            if (today + timedelta(days=i)).isoweekday() in {int(x) for x in p.get("pickup_days") or []}}
    keys |= {k for k in loads if k[0] in by_pid}
    slots = []
    for pid, day in sorted(keys, key=lambda k: (k[1], _time(by_pid[k[0]].get("pickup_time_start")) or time(0), k[0])):
        p = by_pid[pid]
        start, end = _time(p.get("pickup_time_start")), _time(p.get("pickup_time_end"))
        ws = datetime.combine(day, start or time(0), BKK)
        we = datetime.combine(day, end or time(23, 59), BKK)
        state = "PAST" if now > we else "OPEN" if now >= ws else "UPCOMING"
        items = sorted(loads.get((pid, day), []), key=lambda x: (x["source"] != "TASK", x["lot_id"]))
        live = [x for x in items if x["status"] != "REJECTED"]
        kg_c = _r(sum(x["kg"] for x in live if x["source"] == "TASK"), 3)
        kg_w = _r(sum(x["kg"] for x in live if x["source"] == "PLAN"), 3)
        cap = float(p.get("max_capacity_kg_per_pickup") or 0) or None
        min_kg = float(p.get("min_kg_per_pickup") or 0)
        alerts = []
        if cap and kg_c + kg_w > cap + 1e-9:
            alerts.append("OVER_CAPACITY")
        if 0 < kg_c + kg_w < min_kg:
            alerts.append("BELOW_MIN")
        if state in ("OPEN", "PAST") and any(x["source"] == "TASK" and x["status"] in OPEN_TASK for x in items):
            alerts.append("NOT_READY")
        if any(x["source"] == "PLAN" for x in items):
            alerts.append("WAITING_APPROVAL")
        slots.append({
            "slot_id": f"{pid}@{day.isoformat()}", "partner_id": pid, "date": day,
            "window_start": ws, "window_end": we, "state": state,
            "on_schedule": day.isoweekday() in {int(x) for x in p.get("pickup_days") or []},
            "items": items, "kg_confirmed": kg_c, "kg_waiting": kg_w, "capacity_kg": cap, "min_kg": min_kg,
            "tasks_done": sum(1 for x in items if x["source"] == "TASK" and x["status"] == "COMPLETED"),
            "tasks_total": sum(1 for x in items if x["source"] == "TASK" and x["status"] != "REJECTED"),
            "alerts": alerts, "costs": _trip_costs(p, kg_c + kg_w) if live else None,
        })
    return {"reference_date": today, "now": now, "days_ahead": days_ahead,
            "partners": [{k: p.get(k) for k in ("partner_id", "name", "partner_type", "accepted_categories", "pickup_days",
                                                 "pickup_time_start", "pickup_time_end", "max_capacity_kg_per_pickup",
                                                 "min_kg_per_pickup", "contact_name", "contact_phone",
                                                 "min_days_before_expiry")} for p in partners],
            "slots": slots}
