"""เทสต์ offline ของ Phase 2 (เหตุการณ์ / ตรวจตามเวลา / ข้อเสนอ) รันจากโฟลเดอร์ AI:

    python -m unittest manager_agent.tests.test_events -v
"""
import json
import unittest

from manager_agent import events, notify
from manager_agent.config import settings
from manager_agent.data import DataSource
from manager_agent.proposals import ProposalError, build
from manager_agent.tests.fakes import REF, FakeServer, ScriptedLLM, clock_at
from manager_agent.tools import TOOLS

from ai_engine.optimizer import ApiClient  # noqa: E402

NOVA, QWEN = settings.PRIMARY_MODEL, settings.FALLBACK_MODEL


def setup(hhmm="10:00", statuses=None):
    srv = FakeServer()
    for it in srv.items:
        it["ai_status"] = "CHECKED"
        it["updated_at"] = f"{REF}T08:05:00+07:00"
    for lot_id, st in (statuses or {}).items():
        next(i for i in srv.items if i["lot_id"] == lot_id)["ai_status"] = st
    ds = DataSource(ApiClient("http://fake/api/v1", transport=srv), clock=clock_at(hhmm))
    return ds, srv


def run(event, ds, srv, llm=None):
    return events.handle(event, ds, llm or ScriptedLLM({}), events.Sink(ds.client))


class Proposals(unittest.TestCase):
    def test_run_pipeline_needs_idle_and_no_active_run(self):
        ds, srv = setup()
        with self.assertRaisesRegex(ProposalError, "IDLE"):
            build(ds, "RUN_PIPELINE", {})
        ds, srv = setup(statuses={"LOT-000013": "IDLE"})
        p = build(ds, "run_pipeline", {"stop_after": "optimize"})
        self.assertEqual(p["params"], {"stop_after": "OPTIMIZE"})
        ds, srv = setup(statuses={"LOT-000013": "IDLE"})
        srv.runs = [{"status": "RUNNING"}]
        with self.assertRaisesRegex(ProposalError, "RUNNING"):
            build(ds, "RUN_PIPELINE", {})

    def test_release_lots_rules(self):
        ds, srv = setup(statuses={"LOT-000010": "PROCESSING"})
        srv.items[0]["open_tasks"] = 1
        p = build(ds, "RELEASE_LOTS", {"lot_ids": ["lot-000010"]})
        self.assertEqual(p["params"]["lot_ids"], ["LOT-000010"])
        with self.assertRaisesRegex(ProposalError, "งานค้าง"):
            build(ds, "RELEASE_LOTS", {"lot_ids": [srv.items[0]["lot_id"]]})
        with self.assertRaisesRegex(ProposalError, "ไม่พบ"):
            build(ds, "RELEASE_LOTS", {"lot_ids": ["LOT-999999"]})

    def test_block_kitchen_caps_hours(self):
        ds, _ = setup()
        p = build(ds, "BLOCK_KITCHEN", {"department_id": "kitchen_deli", "hours": 20, "then_run_pipeline": True})
        self.assertEqual(p["params"], {"department_id": "KITCHEN_DELI", "date": REF.isoformat(), "hours": 6.0,
                                       "then_run_pipeline": True})
        with self.assertRaisesRegex(ProposalError, "ไม่พบครัว"):
            build(ds, "BLOCK_KITCHEN", {"department_id": "NOPE"})

    def test_chat_tool_returns_card_not_action(self):
        ds, srv = setup(statuses={"LOT-000013": "IDLE"})
        tool = TOOLS["propose_action"]
        result, art = tool.fn(ds, tool.coerce({"kind": "RUN_PIPELINE", "reason": "ทดสอบ"}))
        self.assertEqual(art["type"], "proposal")
        self.assertEqual(art["kind"], "RUN_PIPELINE")
        self.assertIn("ยังไม่ได้ทำ", result["status"])
        self.assertFalse(any(c.startswith("POST") for c in srv.calls))   # ไม่มีการเขียนอะไร


class Notify(unittest.TestCase):
    FACTS = {"lot": "LOT-000013", "จำนวน": 8, "กำหนดเสร็จ": "08:30"}

    def test_grounded_message_used(self):
        llm = ScriptedLLM({NOVA: ["<thinking>x</thinking>LOT-000013 จำนวน 8 ชิ้น เลยกำหนด 08:30 แล้ว"]})
        c = notify.compose(llm, self.FACTS, "template")
        self.assertEqual((c["model_used"], c["message"]), (NOVA, "LOT-000013 จำนวน 8 ชิ้น เลยกำหนด 08:30 แล้ว"))

    def test_invented_number_falls_back(self):
        llm = ScriptedLLM({NOVA: ["เสียหาย 1,500 บาท"], QWEN: ["เลยกำหนด 09:45"]})
        c = notify.compose(llm, self.FACTS, "template")
        self.assertEqual((c["model_used"], c["message"]), ("TEMPLATE", "template"))
        self.assertEqual(len(c["warnings"]), 2)

    def test_no_tools_sent(self):
        llm = ScriptedLLM({NOVA: ["LOT-000013 เลยกำหนด"]})
        notify.compose(llm, self.FACTS, "t")
        self.assertEqual(len(llm.seen), 1)


class Events(unittest.TestCase):
    def test_task_rejected_kitchen_reason_proposes_block_then_replan(self):
        ds, srv = setup(statuses={"LOT-000020": "IDLE"})
        ev = {"trigger": "EVENT", "event_type": "TASK_REJECTED",
              "payload": {"task_id": "t-1", "lot_id": "LOT-000020", "action_type": "KITCHEN_REPURPOSE",
                          "action_quantity": 1, "reason": "เครื่องปั่นในครัวเสีย", "staff_name": "สมหญิง",
                          "department_id": "KITCHEN_DELI"}}
        out = run(ev, ds, srv)
        self.assertEqual((out["notifications"], out["proposals"]), (1, 1))
        batch = srv.posted[-1]
        self.assertEqual(batch["proposals"][0]["kind"], "BLOCK_KITCHEN")
        self.assertTrue(batch["proposals"][0]["params"]["then_run_pipeline"])
        n = batch["notifications"][0]
        self.assertEqual((n["dedupe_key"], n["proposal_ref"], n["event_type"]), ("REJECTED:t-1", 0, "TASK_REJECTED"))
        self.assertIn("เครื่องปั่นในครัวเสีย", n["message"])   # LLM script ว่าง -> ข้อความสำเร็จรูป
        self.assertEqual(batch["run"]["trigger"], "EVENT")
        self.assertTrue(batch["run"]["tool_calls"])           # route ที่อ่านถูกบันทึกไว้ (audit)

    def test_task_rejected_other_reason_proposes_pipeline(self):
        ds, srv = setup(statuses={"LOT-000020": "IDLE"})
        ev = {"trigger": "EVENT", "event_type": "TASK_REJECTED",
              "payload": {"task_id": "t-2", "lot_id": "LOT-000020", "action_type": "MARKDOWN", "reason": "ป้ายราคาหมด"}}
        run(ev, ds, srv)
        self.assertEqual(srv.posted[-1]["proposals"][0]["kind"], "RUN_PIPELINE")

    def test_task_rejected_lot_still_busy_no_proposal(self):
        ds, srv = setup()       # lot ยัง CHECKED = มีงานอื่น
        run({"trigger": "EVENT", "event_type": "TASK_REJECTED",
             "payload": {"task_id": "t-3", "lot_id": "LOT-000020", "action_type": "MARKDOWN", "reason": "x"}}, ds, srv)
        self.assertEqual(srv.posted[-1]["proposals"], [])
        self.assertIsNone(srv.posted[-1]["notifications"][0]["proposal_ref"])

    def test_dedupe_second_event_is_skipped(self):
        ds, srv = setup(statuses={"LOT-000020": "IDLE"})
        ev = {"trigger": "EVENT", "event_type": "TASK_REJECTED",
              "payload": {"task_id": "t-4", "lot_id": "LOT-000020", "action_type": "MARKDOWN", "reason": "x"}}
        run(ev, ds, srv)
        ds2 = DataSource(ApiClient("http://fake/api/v1", transport=srv), clock=clock_at("10:05"))
        out = run(ev, ds2, srv)
        self.assertEqual(out["notifications"], 0)
        self.assertIn("ซ้ำ 1", out["summary"])

    def test_kitchen_full_includes_what_if(self):
        ds, srv = setup()
        run({"trigger": "EVENT", "event_type": "KITCHEN_FULL",
             "payload": {"department_id": "KITCHEN_DELI", "date": REF.isoformat(), "hours_needed": 7.5,
                         "lot_ids": ["LOT-000006"], "review_ids": ["r1", "r2"]}}, ds, srv)
        n = srv.posted[-1]["notifications"][0]
        self.assertEqual(n["dedupe_key"], f"KITCHEN_FULL:KITCHEN_DELI:{REF}:r1:r2")
        self.assertIn("7.5", n["message"])
        self.assertEqual(srv.posted[-1]["proposals"], [])

    def test_pipeline_failed_proposes_release_of_stuck(self):
        ds, srv = setup(statuses={"LOT-000013": "PROCESSING", "LOT-000010": "PROCESSING"})
        run({"trigger": "EVENT", "event_type": "PIPELINE_FAILED",
             "payload": {"pipeline_run_id": "p-1", "current_step": "OPTIMIZE", "error": "OPTIMIZE ล้ม (exit 2)"}}, ds, srv)
        p = srv.posted[-1]["proposals"][0]
        self.assertEqual((p["kind"], p["params"]["lot_ids"]), ("RELEASE_LOTS", ["LOT-000010", "LOT-000013"]))
        self.assertEqual(srv.posted[-1]["notifications"][0]["severity"], "CRITICAL")

    def test_unknown_event(self):
        ds, srv = setup()
        self.assertEqual(run({"trigger": "EVENT", "event_type": "NOPE"}, ds, srv)["status"], 400)


class Watch(unittest.TestCase):
    def test_overdue_task_once(self):
        ds, srv = setup("09:00")            # task ของ fixture due 08:30 ยัง PENDING
        out = run({"trigger": "SCHEDULE", "event_type": "WATCH"}, ds, srv)
        keys = [n["dedupe_key"] for n in srv.posted[-1]["notifications"]]
        self.assertIn("OVERDUE:11111111-1111-1111-1111-111111111111", keys)
        self.assertEqual(out["notifications"], 1)
        ds2 = DataSource(ApiClient("http://fake/api/v1", transport=srv), clock=clock_at("10:00"))
        self.assertEqual(run({"trigger": "SCHEDULE", "event_type": "WATCH"}, ds2, srv)["notifications"], 0)

    def test_outside_hours_skipped_unless_forced(self):
        ds, srv = setup("23:30")
        self.assertEqual(run({"trigger": "SCHEDULE", "event_type": "WATCH"}, ds, srv)["notifications"], 0)
        ds, srv = setup("23:30")
        self.assertEqual(run({"trigger": "SCHEDULE", "event_type": "WATCH", "payload": {"force": True}}, ds, srv)
                         ["notifications"], 1)

    def test_reviews_due_and_expired_grouped(self):
        ds, srv = setup("10:00")
        srv.tasks = []
        srv.reviews = [{"review_id": f"rv{i}", "lot_id": "LOT-000020", "priority": 1, "product": {"name": "กล้วย"},
                        "decision": {"action_type": "MARKDOWN"},
                        "review_deadline": f"{REF}T{'09' if i < 4 else '10'}:{'30' if i < 4 else '45'}:00+07:00"}
                       for i in range(5)]
        run({"trigger": "SCHEDULE", "event_type": "WATCH"}, ds, srv)
        ns = srv.posted[-1]["notifications"]
        self.assertEqual(len(ns), 2)                               # เลยเวลา 4 รายการรวมเป็น 1 + ใกล้หมด 1
        self.assertTrue(ns[0]["dedupe_key"].startswith("REVIEW_EXPIRED_GROUP:"))
        self.assertEqual(ns[1]["dedupe_key"], "REVIEW_DUE:rv4")

    def test_stuck_lots_only_when_no_pipeline_running(self):
        ds, srv = setup("10:00", statuses={"LOT-000013": "PROCESSING"})
        srv.tasks = []
        run({"trigger": "SCHEDULE", "event_type": "WATCH"}, ds, srv)
        b = srv.posted[-1]
        self.assertEqual(b["proposals"][0]["params"]["lot_ids"], ["LOT-000013"])
        ds, srv = setup("10:00", statuses={"LOT-000013": "PROCESSING"})
        srv.tasks, srv.runs = [], [{"status": "RUNNING"}]
        self.assertEqual(run({"trigger": "SCHEDULE", "event_type": "WATCH"}, ds, srv)["notifications"], 0)

    def test_llm_capped(self):
        ds, srv = setup("10:00")
        srv.tasks = [dict(srv.tasks[0], task_id=f"t{i}", due_by=f"{REF}T09:0{i}:00+07:00") for i in range(3)]
        srv.reviews = [{"review_id": f"rv{i}", "lot_id": "LOT-000020", "review_deadline": f"{REF}T10:30:00+07:00",
                        "decision": {"action_type": "MARKDOWN"}} for i in range(3)]
        llm = ScriptedLLM({NOVA: ["มีเรื่องต้องดูในร้าน"] * 10})
        run({"trigger": "SCHEDULE", "event_type": "WATCH"}, ds, srv, llm)
        self.assertEqual(len(srv.posted[-1]["notifications"]), 6)
        self.assertEqual(len(llm.seen), events.MAX_LLM_NOTICES)


if __name__ == "__main__":
    unittest.main()
