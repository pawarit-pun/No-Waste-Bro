"""ของปลอมสำหรับเทสต์ offline: server API จาก fixture mock_v4 + LLM ที่ตอบตามสคริปต์ + KB ปลอม"""
from __future__ import annotations

import json
import urllib.parse
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from manager_agent import config  # noqa: F401  (ใส่ OPTIMIZER_DIR ใน sys.path)

FIXTURE = config.OPTIMIZER_DIR / "ai_engine/tests/fixtures/mock_v4_2026-10-16.json"
REF = date(2026, 10, 16)
BKK = ZoneInfo("Asia/Bangkok")


def clock_at(hhmm: str):
    return lambda: datetime.fromisoformat(f"{REF}T{hhmm}:00+07:00")


class FakeServer:
    """transport ของ ApiClient: ตอบ GET ตามรูปแบบ response ของ server/schemas/responses.py จากข้อมูล fixture"""

    def __init__(self):
        fx = json.loads(Path(FIXTURE).read_text())
        self.inputs, self.products = fx["optimize_inputs"], fx["products"]
        prod = {p["product_id"]: p for p in self.products}
        self.items = []
        for a in self.inputs["at_risk_lots"]:
            lot, p = a["lot"], prod[a["lot"]["product_id"]]
            self.items.append({**lot, "days_left": (date.fromisoformat(lot["expiration_date"]) - REF).days,
                               "origin": "SUPPLIER", "waiting_plans": 0, "open_tasks": 0,
                               "product": {k: p.get(k) for k in ("product_id", "name", "category", "unit_of_measure",
                                                                  "regular_price")},
                               "latest_assessment": {"risk_level": a["risk_level"], "risk_score": a["risk_score"],
                                                     "days_to_expiry": a["days_to_expiry"],
                                                     "assessed_at": a["assessed_at"]}})
        first = self.items[0]
        self.tasks = [
            {"task_id": "11111111-1111-1111-1111-111111111111", "lot_id": first["lot_id"],
             "product_id": first["product_id"], "action_type": "LANDFILL", "action_quantity": first["current_quantity"],
             "task_status": "PENDING", "priority": 1, "original_price": 40.0, "due_by": f"{REF}T08:30:00+07:00",
             "product": first["product"], "assigned_staff": {"staff_id": "STF-003", "full_name": "สมชาย ใจดี"}},
            {"task_id": "22222222-2222-2222-2222-222222222222", "lot_id": "LOT-000020", "product_id": "PRD-X",
             "action_type": "MARKDOWN", "action_quantity": 10, "task_status": "COMPLETED", "priority": 2,
             "original_price": 50.0, "discount_pct": 20, "due_by": f"{REF}T12:00:00+07:00",
             "product": {"name": "กล้วยหอม"}, "assigned_staff": {"staff_id": "STF-004", "full_name": "สมหญิง ขยัน"}},
        ]
        self.calls: list[str] = []
        self.reviews: list[dict] = []
        self.runs: list[dict] = [{"status": "SUCCEEDED", "current_step": "LLM", "started_at": f"{REF}T08:00:00+07:00",
                                  "finished_at": f"{REF}T08:04:00+07:00"}]
        self.kitchen = [{"department_id": d, "capacity_date": REF.isoformat(), "available_hrs": 8.0, "booked_hrs": 2.0,
                         "remaining_hrs": 6.0, "workload_status": "AVAILABLE"} for d in ("BAKERY_DEPT", "KITCHEN_DELI")]
        self.notifications: list[dict] = []     # ที่ "บันทึก" แล้ว (dedupe)
        self.posted: list[dict] = []            # body ของ POST /agent/runs
        self.decisions: list[dict] = []
        self.daily_reports: list[dict] = []
        self.policy = None                      # Phase 4: GET /agent/policies/auto-approve (None = ยังไม่รัน SQL)
        self.auto_requests: list[dict] = []
        self.auto_server_refuses: list[str] = []
        self.kitchen_overview = {"departments": [{"department_id": "KITCHEN_DELI", "department_name": "ครัวเดลี่",
                                                  "days": [self.kitchen[1]]}], "jobs": []}

    def __call__(self, method, url, body, headers, timeout):
        parsed = urllib.parse.urlparse(url)
        route = parsed.path.split("/api/v1/")[-1]
        q = urllib.parse.parse_qs(parsed.query)
        # agent เขียนได้ที่เดียว: route ภายในของ Phase 2 ที่บันทึกแจ้งเตือน / ข้อเสนอ (ยังไม่ได้ทำอะไรกับข้อมูลร้าน)
        # Phase 3: รอบเช้าเริ่ม pipeline เองได้ (plan ยังต้องผ่านผู้จัดการ) นอกนั้นห้ามเขียน
        # Phase 4: Auto-approve อนุมัติผ่าน route ภายในที่ server ตรวจกติกาซ้ำ (เปิดเมื่อผู้จัดการตั้ง policy เท่านั้น)
        assert method == "GET" or (method == "POST" and route in ("agent/runs", "ai/pipeline-runs", "agent/auto-approve")), \
            f"agent ห้ามเขียน {method} {url}"
        self.calls.append(route if method == "GET" else f"{method} {route}")
        if method == "POST" and route == "ai/pipeline-runs":
            self.runs = [{"pipeline_run_id": "pr-new", "status": "QUEUED"}] + self.runs
            return 202, json.dumps(self.runs[0])
        if method == "POST" and route == "agent/auto-approve":
            req = json.loads(body)
            self.auto_requests.append(req)
            ids = set(req["review_ids"]) - set(self.auto_server_refuses)
            done = [dict(r, review_status="APPROVED", approved_by_agent=True) for r in self.reviews if r["review_id"] in ids]
            self.reviews = [r for r in self.reviews if r["review_id"] not in ids]
            self.policy["today"]["approved"] += len(done)
            return 200, json.dumps({"approved": len(done), "lots": sorted({r["lot_id"] for r in done}), "reviews": done,
                                    "tasks": [], "skipped": [], "errors": [], "undo_minutes": 15,
                                    "today": self.policy["today"]}, ensure_ascii=False)
        if method == "POST":
            batch = json.loads(body)
            self.posted.append(batch)
            self.notifications += batch["notifications"]
            return 201, json.dumps({"agent_run_id": "r1", "notifications": len(batch["notifications"]),
                                    "proposals": len(batch["proposals"])})
        if route == "agent/policies/auto-approve":
            if self.policy is None:
                return 404, json.dumps({"detail": "not found"})
            return 200, json.dumps(self.policy, ensure_ascii=False)
        if route == "agent/notifications":
            key = q.get("dedupe_key", [None])[0]
            return 200, json.dumps({"items": [n for n in self.notifications if n["dedupe_key"] == key]})
        if route == "kitchen-overview":
            return 200, json.dumps(self.kitchen_overview)
        if route == "daily-reports":
            return 200, json.dumps({"items": self.daily_reports})
        if route == "kitchen-capacity":
            return 200, json.dumps(self.kitchen)
        if route == "inventory-lots":
            out = {"reference_date": REF.isoformat(), "items": self.items}
        elif route == "tasks":
            st = q.get("status", ["PENDING", "IN_PROGRESS"])
            out = [t for t in self.tasks if t["task_status"] in st]
        elif route == "pending-tasks":
            out = {"reference_date": REF.isoformat(), "counts": {"waiting": 3, "approved": 0, "rejected": 0},
                   "items": self.reviews}
        elif route == "ai/optimize-runs":
            out = {"suggested_run_id": self.inputs["run_id"], "runs": []}
        elif route == "ai/optimize-inputs":
            out = self.inputs
        elif route == "products":
            out = self.products
        elif route == "optimization-decisions":
            out = {"run_id": self.inputs["run_id"], "decisions": self.decisions}
        elif route == "ai/pipeline-runs":
            out = self.runs
        else:
            return 404, json.dumps({"detail": "not found"})
        return 200, json.dumps(out, ensure_ascii=False, default=str)


def fake_sop(query, action_type=None):
    return [{"doc_id": "SOP-MD-01", "score": 0.8,
             "text": "ติดป้ายราคาลดทับป้ายเดิม ตรวจราคาใน POS ให้ตรงก่อนวางขาย"}]


class ScriptedLLM:
    """แต่ละรอบ converse คืนคำตอบถัดไปใน script (ต่อโมเดล) เก็บ messages ที่ได้รับไว้ตรวจ"""

    def __init__(self, scripts: dict[str, list]):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.seen: list[tuple[str, list]] = []

    def converse(self, model_id, system, messages, tools, timeout_s):
        self.seen.append((model_id, json.loads(json.dumps(messages, default=str))))
        queue = self.scripts.get(model_id) or []
        if not queue:
            raise RuntimeError(f"script ของ {model_id} หมด")
        step = queue.pop(0)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, str):
            return {"content": [{"text": step}], "stop_reason": "end_turn", "usage": {"inputTokens": 10, "outputTokens": 5}}
        uses = [{"toolUse": {"toolUseId": f"t{i}-{len(self.seen)}", "name": n, "input": a}}
                for i, (n, a) in enumerate(step)]
        return {"content": uses, "stop_reason": "tool_use", "usage": {"inputTokens": 10, "outputTokens": 5}}
