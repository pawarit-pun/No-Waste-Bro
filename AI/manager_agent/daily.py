"""Phase 3: agent ดูแลรายวัน (โค้ดคำนวณตัวเลขและความผิดปกติทั้งหมด LLM เขียนข้อความสรุปอย่างเดียว)

  MORNING_RUN        07:30  เริ่ม pipeline รอบเช้าเอง (AUTO_MORNING_RUN) ถ้ามี lot IDLE และไม่มีรอบรันอยู่
                            ปิดไว้ = แจ้งเตือน + ข้อเสนอ RUN_PIPELINE ให้ผู้จัดการกด
  PIPELINE_SUCCEEDED        pipeline เสร็จ -> Morning brief ของรอบนั้น
  MORNING_BRIEF             ปุ่ม "Morning brief now" -> Morning brief ของ pipeline รอบล่าสุดที่สำเร็จ
  EVENING_SUMMARY    21:30  สรุปงานที่ทำจริงทั้งวัน เทียบกับ Morning brief

ผลเป็น {"notices": [...], "report": {...}} ให้ events.handle บันทึก (POST /agent/runs: run + แจ้งเตือน + daily_reports)
ตัวเลขกำไรเป็นค่าที่ Optimizer คาด (ยังไม่มีข้อมูล POS) ข้อความต้องบอกว่า "คาด"
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .config import settings
from .labels import ACTION_TH
from .proposals import ProposalError, build as build_proposal

BKK = ZoneInfo("Asia/Bangkok")
RESCUE = ("MARKDOWN", "KITCHEN_REPURPOSE", "DONATE")             # ของยังถูกกิน / ขายได้
RECYCLE = ("ANIMAL_FEED", "COMPOST", "ANAEROBIC_DIGESTION")       # ไม่ถึงคน แต่ไม่ฝังกลบ
DISPOSAL = ("LANDFILL", "DISCARD")                                # ของเสียจริง
ACTION_ORDER = RESCUE + RECYCLE + DISPOSAL
DISPOSAL_SPIKE = 1.5            # ฝังกลบ + ทิ้ง มากกว่าค่าเฉลี่ย 7 รายงานก่อนหน้าเกิน 1.5 เท่า = ผิดปกติ
REVIEW_URGENT_MIN = 60
OPEN = ("PENDING", "IN_PROGRESS")


def _dt(v) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None


def _day(v) -> Optional[str]:
    d = _dt(v)
    return d.astimezone(BKK).date().isoformat() if d else None


def unit_kg(products: dict, product_id) -> float:
    """น้ำหนักต่อหน่วย (kg) จาก net_content กติกาเดียวกับ Optimizer (ML / L ใช้ความหนาแน่น 1 kg/L)"""
    p = products.get(product_id) or {}
    v, u = p.get("net_content_value"), p.get("net_content_unit")
    if not v:
        return 0.0
    return float(v) * (1.0 if u in ("KG", "L") else 0.001)


def _r(x, n=2):
    return round(float(x or 0), n)


def _notice(dedupe_key, severity, title, facts, template, event_type, proposal=None):
    from .events import Notice                       # import ตอนเรียก กัน import วน (events ใช้ daily)
    return Notice(dedupe_key, severity, title, facts, template, event_type, proposal=proposal)


# ---------------------------------------------------------------- รอบเช้า
def morning_run(ds, p: dict) -> dict:
    today = ds.reference_date().isoformat()
    runs = ds.pipeline_runs(1) or []
    active = runs[0] if runs and runs[0].get("status") in ("QUEUED", "RUNNING") else None
    idle = [it["lot_id"] for it in ds.inventory().get("items") or []
            if it.get("ai_status") == "IDLE" and (it.get("current_quantity") or 0) > 0]
    if not settings.AUTO_MORNING_RUN:
        notes: list[str] = []
        try:
            proposal = build_proposal(ds, "RUN_PIPELINE", {"stop_after": "TASKS"}, "รอบเช้า: สแกนและวางแผนของวันนี้")
        except ProposalError as e:
            proposal, notes = None, [str(e)]
        facts = {"เหตุการณ์": "รอบเช้า (ปิดการเริ่ม pipeline อัตโนมัติ)", "lot IDLE": len(idle), "หมายเหตุ": notes or None,
                 "proposal": proposal["title"] if proposal else None}
        tmpl = f"รอบเช้า: มี lot รอสแกน {len(idle)} lot" + (f" ข้อเสนอ: {proposal['title']} กด \"ยืนยัน\" บนการ์ดได้" if proposal else "")
        return {"notices": [_notice(f"MORNING_RUN:{today}", "INFO", "รอบเช้า", facts, tmpl, "MORNING_RUN", proposal)],
                "started": False}
    reason = None
    if active:
        reason = f"pipeline รอบก่อนยัง {active['status']} อยู่"
    elif not idle:
        reason = "ไม่มี lot IDLE ให้สแกน (วางแผนไปแล้วหรือมีงานอยู่)"
    if reason:
        facts = {"เหตุการณ์": "รอบเช้าไม่ได้เริ่ม pipeline", "สาเหตุ": reason}
        return {"notices": [_notice(f"MORNING_RUN:{today}", "INFO", "รอบเช้าไม่ได้เริ่ม", facts,
                                    f"รอบเช้าไม่ได้เริ่ม pipeline: {reason}", "MORNING_RUN")], "started": False}
    run = ds.client.request("POST", "ai/pipeline-runs", body={"stop_after": "TASKS"})   # plan เข้าคิว review เท่านั้น
    return {"notices": [], "started": True, "pipeline_run_id": (run or {}).get("pipeline_run_id"), "idle_lots": len(idle)}


# ---------------------------------------------------------------- Morning brief
def _latest_succeeded(ds) -> Optional[dict]:
    return next((r for r in ds.pipeline_runs(10) or [] if r.get("status") == "SUCCEEDED" and r.get("run_id")), None)


def morning_metrics(ds, run: dict) -> tuple[dict, list[dict]]:
    """-> (metrics, anomalies) ของรอบ pipeline ที่สำเร็จ"""
    now = ds.now()
    today = ds.reference_date().isoformat()
    scan_run = str(run["run_id"])
    inputs = ds.use_scan_run(scan_run)
    products = {p["product_id"]: p for p in ds.products() or []}
    lot_product = {a["lot_id"]: (a.get("lot") or {}).get("product_id") for a in inputs.get("at_risk_lots") or []}

    at_risk = defaultdict(int)
    for a in inputs.get("at_risk_lots") or []:
        at_risk[a["risk_level"]] += 1
    decisions = (ds.decisions(scan_run) or {}).get("decisions") or []
    per = {}
    for d in decisions:
        a = per.setdefault(d["action_type"], {"action_type": d["action_type"], "label": ACTION_TH.get(d["action_type"]),
                                              "decisions": 0, "units": 0, "kg": 0.0, "expected_profit_thb": 0.0})
        a["decisions"] += 1
        a["units"] += d["action_quantity"]
        a["kg"] += d["action_quantity"] * unit_kg(products, (d.get("lot") or {}).get("product_id") or lot_product.get(d["lot_id"]))
        a["expected_profit_thb"] += float(d.get("expected_profit_impact") or 0)
    actions = [dict(v, kg=_r(v["kg"]), expected_profit_thb=_r(v["expected_profit_thb"]))
               for k in ACTION_ORDER for v in [per.get(k)] if v]
    group = lambda keys: _r(sum(a["kg"] for a in actions if a["action_type"] in keys))  # noqa: E731

    plan = {}
    try:
        r = ds.plan("base")
        base = r["plan"].get("baselines") or {}
        plan = {"plan_net_profit_thb": _r(r["plan"]["summary"].get("net_profit_thb")),
                "baseline_regular_then_landfill_thb": _r((base.get("regular_price_then_landfill") or {}).get("net_profit_thb")),
                "improvement_vs_baseline_thb": _r(base.get("improvement_vs_regular_then_landfill_thb"))}
    except Exception as e:  # noqa: BLE001  dry-run ไม่ได้ก็สรุปจาก decision ได้
        plan = {"plan_error": f"{type(e).__name__}"}

    kitchen = []
    try:
        ko = ds.kitchen_overview()
        for dep in ko.get("departments") or []:
            day = next((x for x in dep.get("days") or [] if str(x["capacity_date"])[:10] == today), None)
            if not day:
                continue
            waiting = sum(j.get("hours") or 0 for j in ko.get("jobs") or []
                          if j.get("kind") == "WAITING_APPROVAL" and j.get("department_id") == dep["department_id"]
                          and j.get("date") == today)
            kitchen.append({"department_id": dep["department_id"], "name": dep.get("department_name"),
                            "available_hrs": _r(day["available_hrs"]), "booked_hrs": _r(day["booked_hrs"]),
                            "remaining_hrs": _r(day.get("remaining_hrs")), "waiting_hrs": _r(waiting)})
    except Exception:  # noqa: BLE001
        pass

    auto = None
    try:                                   # Phase 4: plan ที่ AI อนุมัติเองวันนี้ (ก่อน brief นี้)
        pol = ds.client.request("GET", "agent/policies/auto-approve") or {}
        if pol.get("enabled") or (pol.get("today") or {}).get("approved"):
            auto = {"enabled": bool(pol.get("enabled")), **(pol.get("today") or {})}
    except Exception:  # noqa: BLE001  ยังไม่ได้รัน auto_approve.sql
        pass

    reviews = (ds.reviews() or {}).get("items") or []
    urgent = [r_ for r_ in reviews if (_dt(r_.get("review_deadline")) or now + timedelta(days=1)) - now
              <= timedelta(minutes=REVIEW_URGENT_MIN)]
    metrics = {"pipeline_run_id": str(run.get("pipeline_run_id")), "scan_run_id": scan_run,
               "computed_at": now.isoformat(timespec="minutes"),
               "at_risk": dict(at_risk), "decisions": len(decisions), "actions": actions,
               "rescued_kg": group(RESCUE), "recycled_kg": group(RECYCLE), "planned_disposal_kg": group(DISPOSAL),
               "expected_net_profit_thb": _r(sum(a["expected_profit_thb"] for a in actions)), **plan,
               "plans_waiting": len(reviews), "plans_due_within_60min": len(urgent), "kitchen": kitchen,
               "auto_approved": auto}

    # ---------- ความผิดปกติ ----------
    anomalies = []
    decided = {d["lot_id"] for d in decisions}
    stuck = sorted(it["lot_id"] for it in ds.inventory().get("items") or []
                   if it["lot_id"] in lot_product and it["lot_id"] not in decided and it.get("ai_status") == "PROCESSING")
    if stuck:
        anomalies.append({"code": "STUCK_LOTS", "severity": "WARNING", "lot_ids": stuck,
                          "text": f"lot เสี่ยง {len(stuck)} lot ไม่มี decision และค้าง PROCESSING"})
    prev = [r_["metrics"].get("planned_disposal_kg") for r_ in ds.daily_reports(8)
            if r_.get("kind") == "MORNING" and str(r_.get("report_date")) < today
            and (r_.get("metrics") or {}).get("planned_disposal_kg") is not None][:7]
    if prev:
        avg = sum(prev) / len(prev)
        metrics["disposal_kg_avg_prev"] = _r(avg)
        if avg > 0 and metrics["planned_disposal_kg"] > DISPOSAL_SPIKE * avg:
            anomalies.append({"code": "DISPOSAL_HIGH", "severity": "WARNING",
                              "text": f"วางแผนฝังกลบ/ทิ้ง {metrics['planned_disposal_kg']} kg สูงกว่าค่าเฉลี่ย "
                                      f"{len(prev)} วันก่อนหน้า ({_r(avg)} kg) เกิน {DISPOSAL_SPIKE} เท่า"})
    for k in kitchen:
        if k["waiting_hrs"] > k["remaining_hrs"]:
            anomalies.append({"code": "KITCHEN_OVER", "severity": "WARNING",
                              "text": f"plan ครัวที่รออนุมัติของ{k['name'] or k['department_id']} ต้องใช้ {k['waiting_hrs']} ชม. "
                                      f"แต่ครัวเหลือ {k['remaining_hrs']} ชม. อนุมัติทั้งหมดไม่ได้"})
    if plan.get("improvement_vs_baseline_thb") is not None and plan["improvement_vs_baseline_thb"] < 0:
        anomalies.append({"code": "WORSE_THAN_BASELINE", "severity": "WARNING",
                          "text": f"แผนแย่กว่าขายราคาปกติแล้วฝังกลบ {abs(plan['improvement_vs_baseline_thb'])} บาท (คาด)"})
    if urgent:
        anomalies.append({"code": "REVIEW_URGENT", "severity": "CRITICAL" if len(urgent) > 3 else "WARNING",
                          "lot_ids": sorted({r_["lot_id"] for r_ in urgent}),
                          "text": f"plan {len(urgent)} รายการต้องอนุมัติภายใน {REVIEW_URGENT_MIN} นาที"})
    return metrics, anomalies


def morning_brief(ds, p: dict) -> dict:
    today = ds.reference_date().isoformat()
    run = p if p.get("run_id") else _latest_succeeded(ds)
    if not run:
        facts = {"เหตุการณ์": "ทำ Morning brief ไม่ได้", "สาเหตุ": "ยังไม่มี pipeline รอบที่สำเร็จ"}
        return {"notices": [_notice(f"BRIEF_NONE:{today}", "INFO", "ยังไม่มีแผนของวันนี้", facts,
                                    "ยังไม่มี pipeline รอบที่สำเร็จ กด Run agent now ในหน้า Run demo ก่อน", "MORNING_BRIEF")]}
    metrics, anomalies = morning_metrics(ds, run)
    acts = ", ".join(f"{a['label']} {a['units']} หน่วย" for a in metrics["actions"]) or "ไม่มี decision"
    facts = {"รายงาน": "สรุปแผนวันนี้ (Morning brief)", "lot เสี่ยง": metrics["at_risk"], "decision": metrics["decisions"],
             "แผนต่อวิธี": [{k: a[k] for k in ("label", "units", "kg")} for a in metrics["actions"]],
             "ขายต่อ / ครัว / บริจาค (kg)": metrics["rescued_kg"], "อาหารสัตว์ / ปุ๋ย / ก๊าซชีวภาพ (kg)": metrics["recycled_kg"],
             "ฝังกลบ / ทิ้ง (kg)": metrics["planned_disposal_kg"],
             "ดีกว่าขายปกติแล้วฝังกลบ (บาท, คาด)": metrics.get("improvement_vs_baseline_thb"),
             "plan รออนุมัติ": metrics["plans_waiting"],
             "AI อนุมัติเองวันนี้ (plan)": (metrics.get("auto_approved") or {}).get("approved"),
             "ความผิดปกติ": [a["text"] for a in anomalies] or None}
    tmpl = (f"แผนวันนี้: lot เสี่ยง {sum(metrics['at_risk'].values())} lot, {acts} "
            f"ฝังกลบ/ทิ้ง {metrics['planned_disposal_kg']} kg รออนุมัติ {metrics['plans_waiting']} รายการ"
            + (f" AI อนุมัติเองแล้ว {metrics['auto_approved']['approved']} plan"
               if (metrics.get("auto_approved") or {}).get("approved") else "")
            + (f" พบความผิดปกติ {len(anomalies)} เรื่อง" if anomalies else ""))
    sev = "CRITICAL" if any(a["severity"] == "CRITICAL" for a in anomalies) else "WARNING" if anomalies else "INFO"
    notice = _notice(f"MORNING:{today}:{metrics['pipeline_run_id']}", sev, "สรุปแผนวันนี้", facts, tmpl, "MORNING_BRIEF")
    return {"notices": [notice], "report": {"report_date": today, "kind": "MORNING", "metrics": metrics,
                                            "anomalies": anomalies, "notice": 0}}


# ---------------------------------------------------------------- Evening summary
def evening_summary(ds, p: dict) -> dict:
    today = ds.reference_date().isoformat()
    now = ds.now()
    products = {x["product_id"]: x for x in ds.products() or []}
    tasks = [t for t in ds.tasks(OPEN + ("COMPLETED", "REJECTED"))
             if _day(t.get("due_by")) == today or _day(t.get("completed_at")) == today
             or (not t.get("due_by") and t["task_status"] in OPEN)]
    per = {}
    for t in tasks:
        a = per.setdefault(t["action_type"], {"action_type": t["action_type"], "label": ACTION_TH.get(t["action_type"]),
                                              "tasks": 0, "completed": 0, "rejected": 0, "open": 0, "overdue": 0,
                                              "units_planned": 0, "units_handled": 0, "kg_handled": 0.0,
                                              "expected_profit_completed_thb": 0.0})
        a["tasks"] += 1
        a["units_planned"] += t.get("action_quantity") or 0
        st = t["task_status"]
        if st == "COMPLETED":
            n = t.get("actual_quantity_handled")
            n = t.get("action_quantity") or 0 if n is None else n
            a["completed"] += 1
            a["units_handled"] += n
            a["kg_handled"] += n * unit_kg(products, t.get("product_id"))
            a["expected_profit_completed_thb"] += float(t.get("expected_profit_impact") or 0)
        elif st == "REJECTED":
            a["rejected"] += 1
        else:
            a["open"] += 1
            due = _dt(t.get("due_by"))
            if due and due < now:
                a["overdue"] += 1
    actions = [dict(v, kg_handled=_r(v["kg_handled"]), expected_profit_completed_thb=_r(v["expected_profit_completed_thb"]))
               for k in ACTION_ORDER for v in [per.get(k)] if v]
    tot = lambda k: sum(a[k] for a in actions)  # noqa: E731
    group = lambda keys: _r(sum(a["kg_handled"] for a in actions if a["action_type"] in keys))  # noqa: E731
    morning = next((r for r in ds.daily_reports(2) if r.get("kind") == "MORNING" and str(r.get("report_date")) == today), None)
    metrics = {"computed_at": now.isoformat(timespec="minutes"),
               "tasks": {"total": len(tasks), "completed": tot("completed"), "rejected": tot("rejected"),
                         "open": tot("open"), "overdue": tot("overdue")},
               "actions": actions, "rescued_kg": group(RESCUE), "recycled_kg": group(RECYCLE),
               "disposal_kg": group(DISPOSAL),
               "expected_profit_completed_thb": _r(tot("expected_profit_completed_thb")),
               "plans_waiting": len((ds.reviews() or {}).get("items") or []),
               "morning_planned_units": {a["action_type"]: a["units"] for a in (morning or {}).get("metrics", {}).get("actions", [])}
               if morning else None}
    anomalies = []
    if metrics["tasks"]["overdue"]:
        anomalies.append({"code": "OVERDUE_AT_CLOSE", "severity": "WARNING",
                          "text": f"ปิดวันแล้วยังมีงานเลยกำหนด {metrics['tasks']['overdue']} งาน"})
    if metrics["plans_waiting"]:
        anomalies.append({"code": "PLANS_NOT_REVIEWED", "severity": "WARNING",
                          "text": f"มี plan ที่ยังไม่ได้อนุมัติหรือปฏิเสธ {metrics['plans_waiting']} รายการ"})
    if metrics["tasks"]["rejected"]:
        anomalies.append({"code": "REJECTED_TODAY", "severity": "INFO",
                          "text": f"งานถูกปฏิเสธวันนี้ {metrics['tasks']['rejected']} งาน"})
    facts = {"รายงาน": "สรุปปิดวัน (Evening summary)", "task": metrics["tasks"],
             "ทำจริงต่อวิธี": [{k: a[k] for k in ("label", "completed", "units_handled", "kg_handled")} for a in actions],
             "ขายต่อ / ครัว / บริจาค (kg)": metrics["rescued_kg"], "อาหารสัตว์ / ปุ๋ย / ก๊าซชีวภาพ (kg)": metrics["recycled_kg"],
             "ฝังกลบ / ทิ้ง (kg)": metrics["disposal_kg"],
             "กำไรที่ Optimizer คาดของงานที่เสร็จ (บาท)": metrics["expected_profit_completed_thb"],
             "สิ่งที่ค้าง": [a["text"] for a in anomalies] or None}
    tmpl = (f"ปิดวัน: งานเสร็จ {metrics['tasks']['completed']} จาก {metrics['tasks']['total']} งาน "
            f"ขายต่อ/ครัว/บริจาค {metrics['rescued_kg']} kg ฝังกลบ/ทิ้ง {metrics['disposal_kg']} kg"
            + (f" ค้าง {metrics['tasks']['open']} งาน" if metrics["tasks"]["open"] else ""))
    sev = "WARNING" if any(a["severity"] == "WARNING" for a in anomalies) else "INFO"
    notice = _notice(f"EVENING:{today}", sev, "สรุปปิดวัน", facts, tmpl, "EVENING_SUMMARY")
    return {"notices": [notice], "report": {"report_date": today, "kind": "EVENING", "metrics": metrics,
                                            "anomalies": anomalies, "notice": 0}}
