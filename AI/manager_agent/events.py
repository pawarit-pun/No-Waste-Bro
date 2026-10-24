"""Phase 2: agent รับเหตุการณ์จาก server และตรวจร้านตามเวลา -> แจ้งเตือน + ข้อเสนอให้ผู้จัดการกดยืนยัน

โหมดนี้ไม่มีคนเฝ้า: โค้ดเป็นคนตัดสินว่าจะเก็บข้อมูลอะไรและเสนออะไร (ขั้นตอนตายตัวต่อเหตุการณ์)
LLM เขียนข้อความแจ้งเตือนอย่างเดียว (notify.compose: guard + ข้อความสำเร็จรูป)

  EVENT    TASK_REJECTED    พนักงานปฏิเสธ task         -> แจ้ง + เสนอ RUN_PIPELINE (หรือ BLOCK_KITCHEN ถ้าเหตุผลเป็นเรื่องครัว)
  EVENT    KITCHEN_FULL     อนุมัติแล้วจองครัวไม่ได้      -> แจ้ง + ผล what-if ถ้าไม่มีครัวนั้น
  EVENT    PIPELINE_FAILED  pipeline ล้ม                -> แจ้ง + เสนอ RELEASE_LOTS (lot ค้าง) หรือ RUN_PIPELINE
  SCHEDULE WATCH            ทุก 1 ชม. / ปุ่มตรวจตอนนี้   -> task เลยกำหนด, plan ใกล้/เลยเวลาอนุมัติ, lot ค้าง PROCESSING
  Phase 3 (daily.py): MORNING_RUN / PIPELINE_SUCCEEDED / MORNING_BRIEF / EVENING_SUMMARY -> + รายงานใน daily_reports
  Phase 4 (autoapprove.py): ก่อน PIPELINE_SUCCEEDED และ WATCH ถ้าผู้จัดการเปิด Auto-approve
                     agent อนุมัติ plan ที่เข้าเกณฑ์เอง (โค้ดตัดสิน ไม่ใช่ LLM) + แจ้งเตือนพร้อมเวลาที่ย้อนได้

ผลทั้งหมดส่งเข้า server ครั้งเดียว: POST /agent/runs {run, proposals, notifications}
แจ้งเตือนมี dedupe_key: เหตุการณ์เดิม (หรือตรวจรอบถัดไปเจอเรื่องเดิม) ไม่แจ้งซ้ำ
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, time as dtime, timedelta
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from . import autoapprove, daily, notify
from .labels import ACTION_TH
from .proposals import ProposalError, build as build_proposal
from .whatif import WhatIfError, run_what_if

OPEN = ("PENDING", "IN_PROGRESS")
KITCHEN_WORDS = ("ครัว", "เครื่อง", "เตา", "ไฟดับ", "เสีย", "kitchen", "oven", "broken")
WATCH_HOURS = (dtime(7, 0), dtime(22, 30))     # ตรวจตามเวลาเฉพาะช่วงที่ร้านมีคน (ร้านเปิด 08:00-22:00)
REVIEW_DUE_MIN = 60                            # plan ที่ต้องอนุมัติภายใน 60 นาที = เตือน
STUCK_MIN = 30                                 # lot PROCESSING ไม่ขยับเกิน 30 นาที และไม่มี pipeline รันอยู่ = ค้าง
GROUP_OVER = 3                                 # เรื่องเดียวกันเกิน 3 รายการ รวมเป็นแจ้งเตือนเดียว
MAX_LLM_NOTICES = 5                            # รอบหนึ่งให้ LLM เขียนได้ไม่เกิน 5 ข้อความ ที่เหลือใช้ข้อความสำเร็จรูป
AUTO_APPROVE_EVENTS = ("PIPELINE_SUCCEEDED", "WATCH")


def _dt(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


BKK = ZoneInfo("Asia/Bangkok")


def _hhmm(v) -> str:
    d = _dt(v)
    return d.astimezone(BKK).strftime("%H:%M") if d else "-"


def _key(*parts) -> str:
    raw = ":".join(str(p) for p in parts)
    return raw if len(raw) <= 120 else raw[:80] + ":" + hashlib.sha1(raw.encode()).hexdigest()[:12]


class Notice:
    def __init__(self, dedupe_key: str, severity: str, title: str, facts: dict, template: str, event_type: str,
                 lot_id: Optional[str] = None, task_id: Optional[str] = None, proposal: Optional[dict] = None):
        self.dedupe_key, self.severity, self.title, self.facts, self.template = dedupe_key, severity, title, facts, template
        self.event_type, self.lot_id, self.task_id, self.proposal = event_type, lot_id, task_id, proposal


class Sink:
    """ส่งผลเข้า server (route ภายใน) ใช้ ApiClient ของ DataSource"""

    def __init__(self, client):
        self.client = client

    def exists(self, dedupe_key: str) -> bool:
        r = self.client.request("GET", "agent/notifications", {"dedupe_key": dedupe_key, "limit": 1})
        return bool((r or {}).get("items"))

    def post(self, batch: dict) -> dict:
        return self.client.request("POST", "agent/runs", body=batch)


# ---------------------------------------------------------------- helpers
def _lot(ds, lot_id) -> Optional[dict]:
    return next((it for it in ds.inventory().get("items") or [] if it["lot_id"] == str(lot_id or "").upper()), None)


def _try_proposal(ds, kind, params, reason, notes: list) -> Optional[dict]:
    try:
        return build_proposal(ds, kind, params, reason)
    except ProposalError as e:
        notes.append(str(e))
        return None


def _proposal_hint(p: Optional[dict]) -> str:
    return f" ข้อเสนอ: {p['title']} กด \"ยืนยัน\" บนการ์ดได้" if p else ""


def _pending_decision_lots(ds, run_id=None) -> set:
    try:
        ds_ = ds.decisions(run_id)
    except Exception:  # noqa: BLE001
        return set()
    return {d["lot_id"] for d in (ds_ or {}).get("decisions") or [] if d.get("status") in ("PENDING", "IN_REVIEW")}


# ---------------------------------------------------------------- เหตุการณ์
def task_rejected(ds, p: dict) -> list[Notice]:
    lot = _lot(ds, p.get("lot_id"))
    product = (lot or {}).get("product") or {}
    action = ACTION_TH.get(p.get("action_type"), p.get("action_type"))
    reason = str(p.get("reason") or "-")[:200]
    notes: list[str] = []
    proposal = None
    if lot and lot.get("ai_status") == "IDLE" and lot.get("current_quantity", 0) > 0:
        kitchen_issue = p.get("action_type") == "KITCHEN_REPURPOSE" and p.get("department_id") \
            and any(w in reason.lower() for w in KITCHEN_WORDS)
        if kitchen_issue:
            proposal = _try_proposal(ds, "BLOCK_KITCHEN", {"department_id": p["department_id"], "then_run_pipeline": True},
                                     f"พนักงานแจ้งว่า \"{reason}\" ปิดครัวนี้วันนี้ก่อนวางแผนใหม่ จะได้ไม่ส่งงานเข้าครัวอีก", notes)
        if proposal is None:
            proposal = _try_proposal(ds, "RUN_PIPELINE", {"stop_after": "TASKS"},
                                     f"{p.get('lot_id')} กลับเป็น IDLE หลังงานถูกปฏิเสธ ต้องวางแผนใหม่", notes)
    elif lot:
        notes.append(f"{lot['lot_id']} ยังมีงานอื่นค้างอยู่ จึงยังไม่วางแผนใหม่")
    days_left = (lot or {}).get("days_left")
    facts = {"เหตุการณ์": "พนักงานปฏิเสธ task", "lot": p.get("lot_id"), "สินค้า": product.get("name"),
             "งาน": action, "จำนวนในงาน": p.get("action_quantity"), "เหตุผลที่ปฏิเสธ": reason,
             "พนักงาน": p.get("staff_name") or p.get("staff_id"),
             "ของเหลือใน lot": (lot or {}).get("current_quantity"), "เหลืออายุ (วัน)": days_left,
             "หมายเหตุ": notes or None, "proposal": proposal["title"] if proposal else None}
    template = (f"{facts['พนักงาน']} ปฏิเสธงาน{action}ของ {p.get('lot_id')} ({product.get('name') or '-'}) "
                f"เหตุผล: \"{reason}\"" + _proposal_hint(proposal))
    sev = "CRITICAL" if days_left is not None and days_left <= 0 else "WARNING"
    return [Notice(_key("REJECTED", p.get("task_id")), sev, f"งานถูกปฏิเสธ · {p.get('lot_id')}", facts, template,
                   "TASK_REJECTED", p.get("lot_id"), p.get("task_id"), proposal)]


def kitchen_full(ds, p: dict) -> list[Notice]:
    dep, on = str(p.get("department_id") or ""), str(p.get("date") or "")[:10]
    row = next((k for k in ds.kitchen() or [] if k["department_id"] == dep and str(k["capacity_date"])[:10] == on), None)
    lots = sorted(set(p.get("lot_ids") or []))
    facts: dict[str, Any] = {"เหตุการณ์": "อนุมัติ plan ไม่สำเร็จเพราะครัวเต็ม", "ครัว": dep, "วันที่": on,
                             "ชั่วโมงที่ต้องใช้": p.get("hours_needed"),
                             "ชั่วโมงที่เหลือ": (row or {}).get("remaining_hrs"), "lot งานครัวในคำขออนุมัตินี้": lots,
                             "สิ่งที่ทำได้": "ปฏิเสธ plan ครัวบางรายการในคิว review แล้วอนุมัติที่เหลือ"}
    if on == ds.reference_date().isoformat():
        try:
            w = run_what_if(ds, {"kitchen_hours": {"department_id": dep, "hours": 0}})
            facts["ถ้าไม่ใช้ครัวนี้วันนี้ (จำลอง)"] = {"กำไรสุทธิเปลี่ยน (บาท)": w["net_profit_change_thb"],
                                                      "lot ที่แผนเปลี่ยน": w["changed_lots_total"]}
        except (WhatIfError, Exception) as e:  # noqa: BLE001  ผลจำลองเป็นข้อมูลเสริม
            facts["หมายเหตุ"] = f"จำลองไม่ได้: {str(e)[:120]}"
    template = (f"อนุมัติ plan ไม่สำเร็จ: ครัว {dep} วันที่ {on} ต้องใช้ {p.get('hours_needed')} ชั่วโมง "
                f"แต่เหลือ {facts['ชั่วโมงที่เหลือ']} ชั่วโมง ไม่มีอะไรถูกสร้าง ปฏิเสธ plan ครัวบางรายการแล้วอนุมัติที่เหลือได้")
    refs = sorted(p.get("review_ids") or p.get("decision_ids") or [])     # server ส่ง decision_ids ของคำขออนุมัตินั้น
    return [Notice(_key("KITCHEN_FULL", dep, on, *refs), "WARNING",
                   f"ครัวเต็ม · {dep}", facts, template, "KITCHEN_FULL", lots[0] if len(lots) == 1 else None)]


def pipeline_failed(ds, p: dict) -> list[Notice]:
    pending = _pending_decision_lots(ds, p.get("run_id"))
    stuck = sorted(it["lot_id"] for it in ds.inventory().get("items") or []
                   if it.get("ai_status") == "PROCESSING" and not it.get("open_tasks") and not it.get("waiting_plans")
                   and it["lot_id"] not in pending)
    notes: list[str] = []
    proposal = None
    if stuck:
        proposal = _try_proposal(ds, "RELEASE_LOTS", {"lot_ids": stuck},
                                 "lot เหล่านี้ค้าง PROCESSING หลัง pipeline ล้ม คืนเป็น IDLE ให้รอบหน้าสแกนใหม่", notes)
    if proposal is None:
        proposal = _try_proposal(ds, "RUN_PIPELINE", {"stop_after": "TASKS"}, "pipeline รอบก่อนล้ม ลองรันใหม่", notes)
    error = str(p.get("error") or "-")[:300]
    facts = {"เหตุการณ์": "pipeline ล้ม", "ขั้นที่ล้ม": p.get("current_step"), "สาเหตุ": error,
             "lot ที่ค้าง": stuck, "หมายเหตุ": notes or None, "proposal": proposal["title"] if proposal else None}
    template = f"pipeline ล้มที่ขั้น {p.get('current_step') or '-'}: {error}" + _proposal_hint(proposal)
    return [Notice(_key("PIPELINE_FAILED", p.get("pipeline_run_id")), "CRITICAL", "Pipeline ล้ม", facts, template,
                   "PIPELINE_FAILED", proposal=proposal)]


# ---------------------------------------------------------------- ตรวจตามเวลา
def _group(items: list[Notice], key_prefix: str, title: str, severity: str, template: str, facts: dict) -> list[Notice]:
    if len(items) <= GROUP_OVER:
        return items
    keys = sorted(n.dedupe_key for n in items)
    return [Notice(_key(key_prefix, *keys), severity, title, {**facts, "จำนวน": len(items),
                   "รายการ": [n.facts for n in items[:8]]}, template, "WATCH")]


def in_watch_hours(ds, p: dict) -> bool:
    return bool(p.get("force")) or WATCH_HOURS[0] <= ds.now().time() <= WATCH_HOURS[1]


def watch(ds, p: dict) -> list[Notice]:
    now = ds.now()
    if not in_watch_hours(ds, p):
        return []
    out: list[Notice] = []

    # 1) task เลยกำหนด
    overdue = []
    for t in ds.tasks(OPEN):
        due = _dt(t.get("due_by"))
        if not due or due >= now:
            continue
        late = int((now - due).total_seconds() // 60)
        staff = (t.get("assigned_staff") or {}).get("full_name") or "ยังไม่มีผู้รับผิดชอบ"
        action = ACTION_TH.get(t["action_type"], t["action_type"])
        facts = {"เหตุการณ์": "task เลยกำหนด", "lot": t.get("lot_id"), "สินค้า": (t.get("product") or {}).get("name"),
                 "งาน": action, "จำนวน": t.get("action_quantity"), "สถานะ": t["task_status"], "พนักงาน": staff,
                 "กำหนดเสร็จ": _hhmm(t.get("due_by")), "เลยมาแล้ว (นาที)": late}
        overdue.append(Notice(_key("OVERDUE", t["task_id"]), "CRITICAL" if late >= 60 else "WARNING",
                              f"งานเลยกำหนด · {t.get('lot_id')}", facts,
                              f"งาน{action}ของ {t.get('lot_id')} ({staff}) เลยกำหนด {_hhmm(t.get('due_by'))} มา {late} นาที "
                              f"สถานะ {t['task_status']}", "WATCH", t.get("lot_id"), str(t["task_id"])))
    out += _group(overdue, "OVERDUE_GROUP", f"งานเลยกำหนด {len(overdue)} งาน", "CRITICAL",
                  f"มีงานเลยกำหนด {len(overdue)} งาน ดูรายการในหน้า Tasks", {"เหตุการณ์": "task เลยกำหนดหลายงาน"})

    # 2) plan ใกล้ / เลยเวลาอนุมัติ
    due_soon, expired = [], []
    for r in (ds.reviews() or {}).get("items") or []:
        dl = _dt(r.get("review_deadline"))
        if not dl:
            continue
        mins = int((dl - now).total_seconds() // 60)
        action = ACTION_TH.get((r.get("decision") or {}).get("action_type"), "")
        facts = {"lot": r.get("lot_id"), "สินค้า": (r.get("product") or {}).get("name"), "งาน": action,
                 "ต้องอนุมัติก่อน": _hhmm(r.get("review_deadline")), "priority": r.get("priority")}
        if mins < 0:
            expired.append(Notice(_key("REVIEW_EXPIRED", r["review_id"]), "CRITICAL", f"plan เลยเวลาอนุมัติ · {r.get('lot_id')}",
                                  {"เหตุการณ์": "plan เลยเวลาที่พนักงานยังทำทัน", **facts, "เลยมาแล้ว (นาที)": -mins},
                                  f"plan {action}ของ {r.get('lot_id')} เลยเวลา {facts['ต้องอนุมัติก่อน']} แล้ว "
                                  "ควรปฏิเสธเพื่อให้ lot ถูกวางแผนใหม่", "WATCH", r.get("lot_id")))
        elif mins <= REVIEW_DUE_MIN:
            due_soon.append(Notice(_key("REVIEW_DUE", r["review_id"]), "WARNING", f"plan ใกล้หมดเวลาอนุมัติ · {r.get('lot_id')}",
                                   {"เหตุการณ์": "plan รออนุมัติใกล้หมดเวลา", **facts, "เหลือ (นาที)": mins},
                                   f"plan {action}ของ {r.get('lot_id')} ต้องอนุมัติก่อน {facts['ต้องอนุมัติก่อน']} "
                                   f"(อีก {mins} นาที)", "WATCH", r.get("lot_id")))
    out += _group(expired, "REVIEW_EXPIRED_GROUP", f"plan เลยเวลาอนุมัติ {len(expired)} รายการ", "CRITICAL",
                  f"plan ในคิว review เลยเวลาอนุมัติ {len(expired)} รายการ ควรปฏิเสธเพื่อให้วางแผนใหม่",
                  {"เหตุการณ์": "plan เลยเวลาอนุมัติหลายรายการ"})
    out += _group(due_soon, "REVIEW_DUE_GROUP", f"plan ใกล้หมดเวลาอนุมัติ {len(due_soon)} รายการ", "WARNING",
                  f"plan ในคิว review ต้องอนุมัติภายใน {REVIEW_DUE_MIN} นาที {len(due_soon)} รายการ",
                  {"เหตุการณ์": "plan ใกล้หมดเวลาอนุมัติหลายรายการ"})

    # 3) lot ค้าง PROCESSING (ไม่มี pipeline รันอยู่ ไม่มีงาน ไม่มี decision รอ)
    runs = ds.pipeline_runs(1) or []
    active = bool(runs and runs[0].get("status") in ("QUEUED", "RUNNING"))
    if not active:
        pending = _pending_decision_lots(ds)
        stuck = []
        for it in ds.inventory().get("items") or []:
            upd = _dt(it.get("updated_at"))
            if (it.get("ai_status") == "PROCESSING" and not it.get("open_tasks") and not it.get("waiting_plans")
                    and it["lot_id"] not in pending and (upd is None or (now - upd) >= timedelta(minutes=STUCK_MIN))):
                stuck.append(it["lot_id"])
        if stuck:
            notes: list[str] = []
            proposal = _try_proposal(ds, "RELEASE_LOTS", {"lot_ids": stuck},
                                     f"lot ค้าง PROCESSING เกิน {STUCK_MIN} นาทีโดยไม่มี pipeline รันอยู่", notes)
            facts = {"เหตุการณ์": "lot ค้างสถานะ PROCESSING", "lot": sorted(stuck), "จำนวน": len(stuck),
                     "หมายเหตุ": notes or None, "proposal": proposal["title"] if proposal else None}
            out.append(Notice(_key("STUCK", *sorted(stuck)), "WARNING", f"lot ค้าง {len(stuck)} lot", facts,
                              f"{len(stuck)} lot ค้างสถานะ PROCESSING ({', '.join(sorted(stuck)[:5])}) จะไม่ถูกสแกนใหม่"
                              + _proposal_hint(proposal), "WATCH", proposal=proposal))
    return out


PLAYBOOKS: dict[str, Callable] = {"TASK_REJECTED": task_rejected, "KITCHEN_FULL": kitchen_full,
                                  "PIPELINE_FAILED": pipeline_failed, "WATCH": watch,
                                  # Phase 3 (daily.py): คืน {"notices", "report"?}
                                  "MORNING_RUN": daily.morning_run, "PIPELINE_SUCCEEDED": daily.morning_brief,
                                  "MORNING_BRIEF": daily.morning_brief, "EVENING_SUMMARY": daily.evening_summary}


# ---------------------------------------------------------------- run
def handle(event: dict, ds, llm, sink: Sink, clock=time.monotonic) -> dict:
    started = clock()
    trigger = "SCHEDULE" if event.get("trigger") == "SCHEDULE" else "EVENT"
    event_type = str(event.get("event_type") or "WATCH").upper()
    payload = event.get("payload") or {}
    warnings: list[str] = []
    usage: dict = {}
    playbook = PLAYBOOKS.get(event_type)
    if playbook is None:
        return {"error": f"ไม่รู้จัก event_type {event_type}", "status": 400}

    auto, auto_notices = None, []
    if event_type in AUTO_APPROVE_EVENTS and (event_type != "WATCH" or in_watch_hours(ds, payload)):
        try:                               # Phase 4: อนุมัติก่อน แล้ว brief / ตรวจเห็นคิวที่เหลือจริง
            aa = autoapprove.run(ds, payload)
            auto, auto_notices = aa["auto"], aa["notices"]
            warnings += aa["warnings"]
        except Exception as e:  # noqa: BLE001  อนุมัติไม่ได้ ผู้จัดการยังอนุมัติเองได้ตามปกติ
            warnings.append(f"auto-approve: {type(e).__name__}: {str(e)[:160]}")
            ds.invalidate("reviews", "inventory", "tasks")

    out = playbook(ds, payload)
    extra: dict = {}
    report = None
    if isinstance(out, dict):              # Phase 3: รายงานประจำวัน / รอบเช้า
        notices, report = out.get("notices") or [], out.get("report")
        extra = {k: v for k, v in out.items() if k not in ("notices", "report")}
    else:
        notices = out
    report_notice = notices[report["notice"]] if report and report.get("notice") is not None else None
    notices = auto_notices + list(notices)
    fresh = []
    for n in notices:
        try:
            if sink.exists(n.dedupe_key):
                continue
        except Exception as e:  # noqa: BLE001  เช็คไม่ได้ -> ส่งไป server กันซ้ำด้วย unique อีกชั้น
            warnings.append(f"dedupe check: {type(e).__name__}")
        fresh.append(n)

    proposals, notifications, models = [], [], set()
    for i, n in enumerate(fresh):
        facts = {k: v for k, v in n.facts.items() if v not in (None, [], "")}
        if i < MAX_LLM_NOTICES:
            c = notify.compose(llm, facts, n.template)
        else:
            c = {"message": n.template, "model_used": "TEMPLATE", "warnings": [], "usage": {}}
        warnings += c["warnings"]
        models.add(c["model_used"])
        for k, v in c["usage"].items():
            usage[k] = usage.get(k, 0) + v
        ref = None
        if n.proposal:
            ref = len(proposals)
            proposals.append({**n.proposal, "source": trigger})
        notifications.append({"severity": n.severity, "title": n.title, "message": c["message"], "event_type": n.event_type,
                              "lot_id": n.lot_id, "task_id": n.task_id, "dedupe_key": n.dedupe_key, "proposal_ref": ref,
                              "model_used": c["model_used"]})

    if report is not None:
        # ข้อความของรายงาน = ข้อความแจ้งเตือนของมัน (แจ้งเตือนซ้ำถูกข้าม แต่รายงานยังอัปเดตทุกครั้ง)
        written = next((x for x, n in zip(notifications, fresh) if n is report_notice), None)
        if written is None and report_notice is not None:
            c = notify.compose(llm, {k: v for k, v in report_notice.facts.items() if v not in (None, [], "")},
                               report_notice.template)
            warnings += c["warnings"]
            models.add(c["model_used"])
            written = {"message": c["message"], "model_used": c["model_used"]}
        report = {k: v for k, v in report.items() if k != "notice"}
        report["message"] = (written or {}).get("message")
        report["model_used"] = (written or {}).get("model_used") or (sorted(models)[0] if models else None)

    summary = (f"{event_type}: แจ้งเตือนใหม่ {len(notifications)} รายการ ข้อเสนอ {len(proposals)} รายการ"
               + (f" (ซ้ำ {len(notices) - len(fresh)} ข้าม)" if len(notices) > len(fresh) else "")
               + (f" รายงาน {report['kind']}" if report else "")
               + (" เริ่ม pipeline รอบเช้าแล้ว" if extra.get("started") else "")
               + (f" AI อนุมัติเอง {auto['approved']} plan" if auto and auto.get("approved") else ""))
    batch = {"run": {"trigger": trigger, "event_type": event_type, "input": event, "answer": summary,
                     "model_used": ",".join(sorted(models)) or None, "tool_calls": getattr(ds, "fetch_log", []),
                     "warnings": warnings, "usage": usage, "latency_ms": int((clock() - started) * 1000)},
             "proposals": proposals,
             "auto_approved": (auto or {}).get("review_ids") or [],
             "notifications": [{k: v for k, v in n.items() if k != "model_used"} for n in notifications]}
    if report is not None:
        batch["report"] = report
    saved = sink.post(batch)
    return {"summary": summary, "notifications": len(notifications), "proposals": len(proposals),
            "saved": saved, "warnings": warnings, "auto_approve": auto, **extra}
