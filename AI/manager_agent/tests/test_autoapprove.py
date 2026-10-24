"""เทสต์ offline ของ Phase 4 (Auto-approve) รันจากโฟลเดอร์ AI:

    python -m unittest manager_agent.tests.test_autoapprove -v

plan ในคิวสร้างจาก decision จริงของ Optimizer บน fixture (mock_v4 2026-10-16) แบบเดียวกับที่ pipeline ส่งเข้าคิว
"""
import unittest
import uuid
from datetime import datetime

from manager_agent import autoapprove, events
from manager_agent.tests.fakes import REF, ScriptedLLM
from manager_agent.tests.test_events import setup

DEFAULT = {"actions": ["MARKDOWN"], "max_discount_pct": 30, "max_value_thb": 2000,
           "min_minutes_before_deadline": 30, "daily_limit": 30, "undo_minutes": 15}


def seed(srv, ds, enabled=True, params=None, approved_today=0, model="amazon.nova-lite-v1:0"):
    """decision ของ Optimizer (dry-run บน fixture) -> decision ใน server + plan WAITING ในคิว"""
    plan = ds.plan("base")
    lot_of = {a["assessment_id"]: a["lot_id"] for a in srv.inputs["at_risk_lots"]}
    inv = {i["lot_id"]: i for i in srv.items}
    srv.decisions, srv.reviews = [], []
    for d in plan["payload"]["decisions"]:
        lot = lot_of[d["assessment_id"]]
        did = str(uuid.uuid4())
        srv.decisions.append({**d, "decision_id": did, "lot_id": lot, "run_id": srv.inputs["run_id"], "status": "IN_REVIEW"})
        exp = inv[lot]["expiration_date"]
        srv.reviews.append({
            "review_id": str(uuid.uuid4()), "decision_id": did, "run_id": srv.inputs["run_id"], "lot_id": lot,
            "review_status": "WAITING", "model_used": model, "priority": 2, "lot_expired": exp < REF.isoformat(),
            "review_deadline": d.get("due_by") or f"{exp}T22:00:00+07:00",
            "decision": {k: d.get(k) for k in ("action_type", "action_quantity", "discount_pct", "new_recommended_price",
                                               "expected_profit_impact", "due_by")},
            "product": inv[lot]["product"]})
    p = {**DEFAULT, **(params or {})}
    srv.policy = {"policy_id": "AUTO_APPROVE", "enabled": enabled, "params": p, "owner_staff_id": "STF-001",
                  "owner": {"staff_id": "STF-001", "full_name": "วิภา ผู้จัดการ"},
                  "today": {"approved": approved_today, "lots": 0, "remaining": p["daily_limit"] - approved_today}}
    ds.invalidate("reviews", "decisions")


class Rules(unittest.TestCase):
    NOW = datetime.fromisoformat(f"{REF}T10:00:00+07:00")

    def row(self, **kw):
        d = {"action_type": "MARKDOWN", "action_quantity": 10, "discount_pct": 20, "new_recommended_price": 80,
             "expected_profit_impact": 100, "alternatives": [{"expected_profit_impact": 50}]}
        d.update(kw.pop("decision", {}))
        return {"review_id": "r", "lot_id": "L", "review_status": "WAITING", "model_used": "nova", "decision": d,
                "lot_price": 100, "min_allowed_price": 50, "review_deadline": f"{REF}T22:00:00+07:00", **kw}

    def codes(self, **kw):
        return autoapprove.evaluate(self.row(**kw), DEFAULT, self.NOW)[0]

    def test_pass(self):
        fails, facts = autoapprove.evaluate(self.row(), DEFAULT, self.NOW)
        self.assertEqual(fails, [])
        self.assertEqual(facts["value_thb"], 1000)
        self.assertEqual(facts["minutes_left"], 720)

    def test_each_rule(self):
        self.assertIn("AA_ACTION", self.codes(decision={"action_type": "LANDFILL"}))
        self.assertIn("AA_DISCOUNT", self.codes(decision={"discount_pct": 40}))
        self.assertIn("AA_PRICE", self.codes(decision={"new_recommended_price": 40}))
        self.assertIn("AA_VALUE", self.codes(decision={"action_quantity": 21}))
        self.assertIn("AA_NOT_BEST", self.codes(decision={"alternatives": [{"expected_profit_impact": 150}]}))
        self.assertIn("AA_TEMPLATE", self.codes(model_used="TEMPLATE"))
        self.assertIn("AA_EXPIRED", self.codes(lot_expired=True))
        self.assertIn("AA_DEADLINE", self.codes(review_deadline=f"{REF}T10:20:00+07:00"))
        self.assertIn("AA_UNDONE", self.codes(agent_undone_at="2026-10-16T09:00:00+07:00"))

    def test_infeasible_alternatives_ignored(self):
        alts = [{"option": "KITCHEN", "rejected_because": ["K1"]},
                {"action_type": "DISCARD", "feasible": False, "expected_profit_impact": 999},
                {"scope": "WHOLE_LOT", "expected_profit_impact": 999}]
        self.assertEqual(self.codes(decision={"alternatives": alts}), [])

    def test_kitchen_never_allowed_even_if_listed(self):
        p = {**DEFAULT, "actions": ["KITCHEN_REPURPOSE"]}
        r = self.row(decision={"action_type": "KITCHEN_REPURPOSE"})
        self.assertIn("AA_ACTION", autoapprove.evaluate(r, p, self.NOW)[0])

    def test_whole_lot_and_limit(self):
        a1, a2 = self.row(review_id="a1", lot_id="A"), self.row(review_id="a2", lot_id="A", decision={"action_type": "DONATE"})
        b = self.row(review_id="b", lot_id="B", review_deadline=f"{REF}T12:00:00+07:00")
        c = self.row(review_id="c", lot_id="C")
        picked, skipped = autoapprove.select([a1, a2, b, c], DEFAULT, remaining=1, now=self.NOW)
        self.assertEqual([l["lot_id"] for l in picked], ["B"])            # deadline ใกล้สุดก่อน
        reasons = {s["review_id"]: s["reasons"] for s in skipped}
        self.assertEqual(reasons["a1"], ["AA_LOT"])                         # a1 ผ่านเอง แต่ a2 ไม่ผ่าน
        self.assertEqual(reasons["a2"], ["AA_ACTION"])
        self.assertEqual(reasons["c"], ["AA_LIMIT"])


class Flow(unittest.TestCase):
    def run_event(self, event_type, hhmm="10:00", **seed_kw):
        ds, srv = setup(hhmm)
        seed(srv, ds, **seed_kw)
        out = events.handle({"trigger": "EVENT", "event_type": event_type,
                             "payload": {"run_id": srv.inputs["run_id"], "pipeline_run_id": "pr1"}},
                            ds, ScriptedLLM({}), events.Sink(ds.client))
        return out, srv

    def test_pipeline_succeeded_approves_markdown_only_lots_then_brief(self):
        out, srv = self.run_event("PIPELINE_SUCCEEDED")
        self.assertEqual(len(srv.auto_requests), 1)
        approved = set(out["auto_approve"]["lots"])
        # fixture: lot ที่มีแต่ MARKDOWN 5 lot, LOT-000020 มูลค่า 3,395 บาท เกินเพดาน 2,000
        self.assertEqual(approved, {"LOT-000007", "LOT-000008", "LOT-000010", "LOT-000011"})
        skipped: dict = {}
        for s_ in out["auto_approve"]["skipped"]:
            skipped.setdefault(s_["lot_id"], []).extend(s_["reasons"])
        self.assertEqual(skipped["LOT-000020"], ["AA_VALUE"])
        self.assertIn("AA_LOT", skipped["LOT-000006"])                    # MARKDOWN ผ่าน แต่ lot มีงานครัว/ฝังกลบ
        batch = srv.posted[0]
        self.assertEqual(len(batch["auto_approved"]), 4)
        titles = [n["title"] for n in batch["notifications"]]
        self.assertEqual(titles[0], "AI อนุมัติเอง 4 plan")
        self.assertIn("สรุปแผนวันนี้", titles)
        # brief เห็นคิวหลังอนุมัติ: plan ที่เหลือ = ทั้งหมด - 4
        self.assertEqual(batch["report"]["metrics"]["plans_waiting"], len(srv.reviews))
        self.assertEqual(batch["report"]["metrics"]["auto_approved"]["approved"], 4)

    def test_disabled_or_missing_policy_does_nothing(self):
        out, srv = self.run_event("PIPELINE_SUCCEEDED", enabled=False)
        self.assertEqual(srv.auto_requests, [])
        self.assertEqual(srv.posted[0]["auto_approved"], [])
        ds, srv = setup()
        out = events.handle({"trigger": "SCHEDULE", "event_type": "WATCH", "payload": {}}, ds, ScriptedLLM({}),
                            events.Sink(ds.client))
        self.assertTrue(any("auto-approve policy" in w for w in out["warnings"]))
        self.assertFalse(any(c.startswith("POST agent/auto-approve") for c in srv.calls))

    def test_template_text_and_daily_limit(self):
        out, srv = self.run_event("WATCH", model="TEMPLATE")
        self.assertEqual(srv.auto_requests, [])
        out, srv = self.run_event("WATCH", approved_today=28)      # เหลือ 2: ได้ 2 lot ที่ต้องอนุมัติก่อน
        self.assertEqual(len(srv.auto_requests[0]["review_ids"]), 2)

    def test_watch_outside_hours_skips(self):
        out, srv = self.run_event("WATCH", hhmm="23:30")
        self.assertEqual(srv.auto_requests, [])

    def test_server_refusal_reported_not_crashing(self):
        ds, srv = setup()
        seed(srv, ds)
        srv.auto_server_refuses = [r["review_id"] for r in srv.reviews]
        out = events.handle({"trigger": "SCHEDULE", "event_type": "WATCH", "payload": {}}, ds, ScriptedLLM({}),
                            events.Sink(ds.client))
        self.assertEqual(out["auto_approve"]["approved"], 0)
        self.assertFalse(any(n["event_type"] == "AUTO_APPROVE" for n in srv.posted[0]["notifications"]))

    def test_notification_not_repeated(self):
        ds, srv = setup()
        seed(srv, ds)
        n = autoapprove.run(ds, {})["notices"]
        self.assertEqual(len(n), 1)
        self.assertIn("ย้อนกลับได้ใน 15 นาที", n[0].template)
        self.assertEqual(autoapprove.run(ds, {})["notices"], [])          # รอบถัดไป: ไม่เหลือ plan ที่เข้าเกณฑ์


if __name__ == "__main__":
    unittest.main()
