"""เทสต์ offline ของ Phase 3 (รอบเช้า / Morning brief / Evening summary / tool รายงาน) รันจากโฟลเดอร์ AI:

    python -m unittest manager_agent.tests.test_daily -v
"""
import unittest
from unittest import mock

from manager_agent import daily, events
from manager_agent.config import settings
from manager_agent.data import DataSource
from manager_agent.tests.fakes import REF, FakeServer, ScriptedLLM, clock_at
from manager_agent.tools import TOOLS

from ai_engine.optimizer import ApiClient  # noqa: E402


def setup(hhmm="09:00", idle=()):
    srv = FakeServer()
    for it in srv.items:
        it["ai_status"] = "IDLE" if it["lot_id"] in idle else "CHECKED"
    ds = DataSource(ApiClient("http://fake/api/v1", transport=srv), clock=clock_at(hhmm))
    return ds, srv


def run(event, ds, llm=None):
    return events.handle(event, ds, llm or ScriptedLLM({}), events.Sink(ds.client))


def decision(lot, action, qty, profit):
    return {"lot_id": lot, "action_type": action, "action_quantity": qty, "expected_profit_impact": profit,
            "status": "IN_REVIEW", "lot": {"product_id": None}}


class MorningRun(unittest.TestCase):
    def test_starts_pipeline_when_idle(self):
        ds, srv = setup(idle=("LOT-000013",))
        out = run({"trigger": "SCHEDULE", "event_type": "MORNING_RUN"}, ds)
        self.assertTrue(out["started"])
        self.assertIn("POST ai/pipeline-runs", srv.calls)
        self.assertEqual(srv.posted[-1]["notifications"], [])

    def test_skips_and_notifies(self):
        ds, srv = setup()
        out = run({"trigger": "SCHEDULE", "event_type": "MORNING_RUN"}, ds)
        self.assertFalse(out["started"])
        self.assertNotIn("POST ai/pipeline-runs", srv.calls)
        self.assertEqual(srv.posted[-1]["notifications"][0]["dedupe_key"], f"MORNING_RUN:{REF}")

    def test_auto_off_proposes_instead(self):
        ds, srv = setup(idle=("LOT-000013",))
        with mock.patch.object(settings, "AUTO_MORNING_RUN", False):
            out = run({"trigger": "SCHEDULE", "event_type": "MORNING_RUN"}, ds)
        self.assertFalse(out["started"])
        self.assertNotIn("POST ai/pipeline-runs", srv.calls)
        self.assertEqual(srv.posted[-1]["proposals"][0]["kind"], "RUN_PIPELINE")


class MorningBrief(unittest.TestCase):
    def brief(self, **kw):
        ds, srv = setup(kw.get("hhmm", "09:00"))
        lot_pid = {i["lot_id"]: i["product_id"] for i in srv.items}
        srv.decisions = [dict(decision("LOT-000020", "MARKDOWN", 98, 128.13), lot={"product_id": lot_pid["LOT-000020"]}),
                         dict(decision("LOT-000013", "LANDFILL", 8, -989.04), lot={"product_id": lot_pid["LOT-000013"]})]
        srv.items = [dict(i, ai_status="PROCESSING") if i["lot_id"] == "LOT-000010" else i for i in srv.items]
        srv.daily_reports = kw.get("history", [])
        srv.reviews = kw.get("reviews", [])
        if "kitchen_jobs" in kw:
            srv.kitchen_overview["jobs"] = kw["kitchen_jobs"]
        out = run({"trigger": "EVENT", "event_type": "PIPELINE_SUCCEEDED",
                   "payload": {"pipeline_run_id": "pr-1", "run_id": srv.inputs["run_id"]}}, ds)
        return out, srv

    def test_metrics_and_report(self):
        out, srv = self.brief()
        b = srv.posted[-1]
        rep = b["report"]
        self.assertEqual((rep["kind"], rep["report_date"]), ("MORNING", REF.isoformat()))
        m = rep["metrics"]
        self.assertEqual(m["decisions"], 2)
        self.assertEqual([a["action_type"] for a in m["actions"]], ["MARKDOWN", "LANDFILL"])   # ขายต่อก่อน กำจัดท้าย
        self.assertAlmostEqual(m["planned_disposal_kg"], 3.84)          # ขนมปัง 480g x 8 (กติกาเดียวกับ Optimizer)
        self.assertAlmostEqual(m["expected_net_profit_thb"], -860.91)
        self.assertGreater(m["improvement_vs_baseline_thb"], 0)         # dry-run รอบเดียวกัน
        self.assertEqual(m["at_risk"], {"CRITICAL": 4, "HIGH": 9})
        codes = [a["code"] for a in rep["anomalies"]]
        self.assertIn("STUCK_LOTS", codes)                              # LOT-000010 PROCESSING ไม่มี decision
        self.assertEqual(rep["message"], b["notifications"][0]["message"])
        self.assertEqual(b["notifications"][0]["dedupe_key"], f"MORNING:{REF}:pr-1")

    def test_disposal_spike_vs_history(self):
        hist = [{"report_date": "2026-10-15", "kind": "MORNING", "metrics": {"planned_disposal_kg": 1.0}}]
        _, srv = self.brief(history=hist)
        self.assertIn("DISPOSAL_HIGH", [a["code"] for a in srv.posted[-1]["report"]["anomalies"]])

    def test_kitchen_over_and_urgent_reviews(self):
        jobs = [{"kind": "WAITING_APPROVAL", "department_id": "KITCHEN_DELI", "date": REF.isoformat(), "hours": 7.0}]
        reviews = [{"review_id": "r1", "lot_id": "LOT-000020", "review_deadline": f"{REF}T09:30:00+07:00"}]
        _, srv = self.brief(kitchen_jobs=jobs, reviews=reviews)
        codes = [a["code"] for a in srv.posted[-1]["report"]["anomalies"]]
        self.assertIn("KITCHEN_OVER", codes)       # รอ 7 ชม. แต่เหลือ 6
        self.assertIn("REVIEW_URGENT", codes)

    def test_manual_brief_uses_latest_succeeded_and_updates_report_when_deduped(self):
        ds, srv = setup()
        srv.runs = [{"pipeline_run_id": "pr-9", "status": "SUCCEEDED", "run_id": srv.inputs["run_id"]}]
        run({"trigger": "SCHEDULE", "event_type": "MORNING_BRIEF"}, ds)
        ds2 = DataSource(ApiClient("http://fake/api/v1", transport=srv), clock=clock_at("10:00"))
        run({"trigger": "SCHEDULE", "event_type": "MORNING_BRIEF"}, ds2)
        self.assertEqual(srv.posted[-1]["notifications"], [])           # แจ้งซ้ำถูกข้าม
        self.assertTrue(srv.posted[-1]["report"]["message"])            # แต่รายงานยังอัปเดต

    def test_no_pipeline_yet(self):
        ds, srv = setup()
        srv.runs = []
        run({"trigger": "SCHEDULE", "event_type": "MORNING_BRIEF"}, ds)
        self.assertNotIn("report", srv.posted[-1])


class EveningSummary(unittest.TestCase):
    def test_counts_and_kg(self):
        ds, srv = setup("21:30")
        pid13 = next(i["product_id"] for i in srv.items if i["lot_id"] == "LOT-000013")
        srv.tasks = [
            dict(srv.tasks[0], task_status="COMPLETED", actual_quantity_handled=6, product_id=pid13,
                 expected_profit_impact=-700.0, completed_at=f"{REF}T20:00:00+07:00"),
            {"task_id": "m1", "lot_id": "LOT-000020", "product_id": "PRD-X", "action_type": "MARKDOWN", "action_quantity": 10,
             "task_status": "PENDING", "due_by": f"{REF}T12:00:00+07:00"},
            {"task_id": "m2", "lot_id": "LOT-000020", "product_id": "PRD-X", "action_type": "MARKDOWN", "action_quantity": 5,
             "task_status": "REJECTED", "due_by": f"{REF}T12:00:00+07:00"},
        ]
        srv.daily_reports = [{"report_date": REF.isoformat(), "kind": "MORNING",
                              "metrics": {"actions": [{"action_type": "LANDFILL", "units": 8}]}}]
        run({"trigger": "SCHEDULE", "event_type": "EVENING_SUMMARY"}, ds)
        rep = srv.posted[-1]["report"]
        m = rep["metrics"]
        self.assertEqual(m["tasks"], {"total": 3, "completed": 1, "rejected": 1, "open": 1, "overdue": 1})
        self.assertAlmostEqual(m["disposal_kg"], 2.88)                 # 6 x 0.48 kg (ทำจริง ไม่ใช่ที่วางแผน)
        self.assertEqual(m["morning_planned_units"], {"LANDFILL": 8})
        self.assertEqual({a["code"] for a in rep["anomalies"]}, {"OVERDUE_AT_CLOSE", "REJECTED_TODAY"})
        self.assertEqual(rep["kind"], "EVENING")


class ReportTool(unittest.TestCase):
    def test_get_daily_report(self):
        ds, srv = setup()
        srv.daily_reports = [{"report_date": REF.isoformat(), "kind": "MORNING", "message": "แผนวันนี้", "metrics": {"decisions": 2}}]
        tool = TOOLS["get_daily_report"]
        r, _ = tool.fn(ds, tool.coerce({"kind": "MORNING"}))
        self.assertEqual(r["reports"][0]["metrics"], {"decisions": 2})
        with self.assertRaisesRegex(ValueError, "มี:"):
            tool.fn(ds, tool.coerce({"kind": "EVENING"}))

    def test_unit_kg(self):
        products = {"A": {"net_content_value": 480, "net_content_unit": "G"},
                    "B": {"net_content_value": 1, "net_content_unit": "L"}, "C": {}}
        self.assertEqual((daily.unit_kg(products, "A"), daily.unit_kg(products, "B"), daily.unit_kg(products, "C")),
                         (0.48, 1.0, 0.0))


if __name__ == "__main__":
    unittest.main()
