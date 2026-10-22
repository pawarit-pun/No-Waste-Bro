"""เทสต์ offline ของ Manager Agent (ไม่ต้องมี AWS / server) รันจากโฟลเดอร์ AI:

    python -m unittest manager_agent.tests.test_agent -v

ข้อมูล = fixture mock_v4_2026-10-16.json ของ Optimizer (lot demo 13 ล็อตที่ HIGH / CRITICAL), LLM = สคริปต์
"""
import json
import unittest

from manager_agent import guard  # manager_agent.config ใส่ food_waste_optimizer ใน sys.path ก่อน import ai_engine
from manager_agent.agent import ManagerAgent, sanitize_history
from manager_agent.config import settings
from manager_agent.data import DataSource
from manager_agent.handler import lambda_handler
from manager_agent.tests.fakes import FakeServer, ScriptedLLM, clock_at, fake_sop
from manager_agent.tools import TOOLS, reason_th, tool_config

from ai_engine.optimizer import ApiClient  # noqa: E402

NOVA, QWEN = settings.PRIMARY_MODEL, settings.FALLBACK_MODEL


def make_ds(hhmm="09:00"):
    srv = FakeServer()
    ds = DataSource(ApiClient("http://fake/api/v1", transport=srv), clock=clock_at(hhmm))
    ds.sop_retriever = fake_sop
    return ds, srv


def call(ds, name, **args):
    tool = TOOLS[name]
    return tool.fn(ds, tool.coerce(args))


class Tools(unittest.TestCase):
    def setUp(self):
        self.ds, self.srv = make_ds()

    def test_specs_are_valid_converse_tools(self):
        cfg = tool_config()
        self.assertEqual(len(cfg["tools"]), len(TOOLS))
        for t in cfg["tools"]:
            spec = t["toolSpec"]
            self.assertRegex(spec["name"], r"^[a-z_]+$")
            self.assertEqual(spec["inputSchema"]["json"]["type"], "object")
            json.dumps(t, ensure_ascii=False)

    def test_snapshot_counts(self):
        r, art = call(self.ds, "get_store_snapshot")
        self.assertEqual(r["lots_in_stock"], 13)
        self.assertEqual(r["lots_by_risk_level"], {"CRITICAL": 4, "HIGH": 9})
        self.assertEqual(r["plans_waiting_approval"], 3)
        self.assertEqual(r["overdue_tasks"], 1)              # due 08:30 ตอนนี้ 09:00
        self.assertEqual(art["type"], "snapshot")

    def test_at_risk_sorted_and_counted(self):
        r, _ = call(self.ds, "list_at_risk_lots", limit="3")  # โมเดลส่งเลขเป็น string ได้
        self.assertEqual((r["total"], r["shown"]), (13, 3))
        self.assertEqual([l["risk_level"] for l in r["lots"]], ["CRITICAL"] * 3)
        self.assertEqual(r["lots"][0]["lot_id"], "LOT-000013")
        r, _ = call(self.ds, "list_at_risk_lots", risk_levels=["HIGH"], category="PRODUCE")
        self.assertTrue(r["lots"] and all(l["category"] == "PRODUCE" and l["risk_level"] == "HIGH" for l in r["lots"]))

    def test_get_lot_case_insensitive_and_missing(self):
        r, art = call(self.ds, "get_lot", lot_id="lot-000013")
        self.assertEqual(r["lot_id"], "LOT-000013")
        self.assertEqual(len(r["tasks"]), 1)
        self.assertEqual(art, {"type": "lot", "lot_id": "LOT-000013"})
        with self.assertRaises(ValueError):
            call(self.ds, "get_lot", lot_id="LOT-999999")

    def test_coerce_rejects_bad_args(self):
        with self.assertRaises(ValueError):
            TOOLS["get_lot"].coerce({})
        with self.assertRaises(ValueError):
            TOOLS["list_tasks"].coerce({"status": "done"})
        with self.assertRaises(ValueError):
            TOOLS["get_lot"].coerce({"lot_id": "LOT-1", "drop_table": True})

    def test_list_tasks_filters(self):
        r, _ = call(self.ds, "list_tasks", status="all")
        self.assertEqual(r["total"], 2)
        r, _ = call(self.ds, "list_tasks", overdue_only=True)
        self.assertEqual([t["lot_id"] for t in r["tasks"]], ["LOT-000013"])

    def test_plan_matches_optimizer(self):
        r, _ = call(self.ds, "get_plan")
        self.assertEqual(r["lots"], 13)
        self.assertEqual(r["unresolved_units"], 0)
        self.assertGreater(r["improvement_vs_regular_then_landfill_thb"], 0)
        # ส่วนที่กำจัดวันอื่นเป็นแผนชั่วคราว ไม่นับเป็นงานวันนี้
        self.assertIn("ส่งทำอาหารสัตว์", r["provisional_units_by_method"])
        self.assertNotIn("อาหารสัตว์", r["task_units_today_by_action"])

    def test_explain_decision(self):
        r, art = call(self.ds, "explain_decision", lot_id="LOT-000020")
        self.assertEqual(r["quantity"], sum(p["units"] for p in r["plan"]))
        self.assertTrue(any(p["method"] == "ลดราคา" for p in r["plan"]))
        self.assertEqual(sum(1 for o in r["price_options"] if o["chosen"]), 1)
        self.assertTrue(all(o["reasons"] for o in r["excluded_options"]))
        self.assertEqual(art["type"], "lot_explain")
        kitchen = [p for p in r["plan"] if p["method"] == "ส่งเข้าครัวทำเมนู"]
        self.assertTrue(kitchen and not kitchen[0]["recipe"].startswith("RCP-"))   # ชื่อสูตร ไม่ใช่รหัส
        with self.assertRaises(ValueError):
            call(self.ds, "explain_decision", lot_id="LOT-999999")

    def test_reason_translation(self):
        self.assertEqual(reason_th("P4_MIN_DAYS -1d at pickup < 2d"), "อายุที่เหลือตอนรับของน้อยกว่าที่ partner กำหนด")
        self.assertEqual(reason_th("P2_CATEGORY_MEAT_NOT_ACCEPTED"), "partner ไม่รับสินค้าหมวดนี้")
        self.assertEqual(reason_th("Z9_UNKNOWN"), "Z9_UNKNOWN")

    def test_agent_never_writes(self):
        for name, args in [("get_store_snapshot", {}), ("get_plan", {}), ("what_if", {"no_markdown": ["ALL"]})]:
            call(self.ds, name, **args)
        self.assertNotIn("POST", " ".join(self.srv.calls))     # FakeServer assert ทุก method ที่ไม่ใช่ GET อยู่แล้ว


class WhatIf(unittest.TestCase):
    def setUp(self):
        self.ds, _ = make_ds()
        self.base = self.ds.plan("base")["plan"]["summary"]["net_profit_thb"]

    def test_no_markdown_is_worse_and_consistent(self):
        r, art = call(self.ds, "what_if", no_markdown=["ALL"])
        self.assertAlmostEqual(r["net_profit_before_thb"], round(self.base, 2))
        self.assertAlmostEqual(r["net_profit_change_thb"], round(r["net_profit_after_thb"] - r["net_profit_before_thb"], 2),
                               places=1)
        self.assertLess(r["net_profit_change_thb"], 0)           # optimum เดิมเลือกลดราคาเพราะดีกว่า
        md = [u for u in r["units_by_method"] if u["method"].startswith("ลดราคา")]
        self.assertTrue(md and md[0]["after"] == 0)
        self.assertEqual(art["type"], "what_if")
        self.assertLessEqual(len(r["changed_lots"]), 8)

    def test_partner_unavailable_reroutes(self):
        r, _ = call(self.ds, "what_if", partner_unavailable=["p-ani-01"])
        moved = {u["method"]: u["change"] for u in r["units_by_method"]}
        self.assertLess(moved.get("ส่งทำอาหารสัตว์", 0), 0)
        self.assertLessEqual(r["net_profit_change_thb"], 0.01)  # ตัดทางเลือกออก กำไรไม่ดีขึ้น

    def test_force_discount_only_forecast_levels(self):
        with self.assertRaisesRegex(ValueError, "ระดับที่มี"):
            call(self.ds, "what_if", force_discount={"lot_id": "LOT-000020", "discount_pct": 45})
        r, _ = call(self.ds, "what_if", force_discount={"lot_id": "LOT-000020", "discount_pct": 50})
        self.assertLessEqual(r["net_profit_change_thb"], 0.01)
        self.assertTrue(any(c["lot_id"] == "LOT-000020" for c in r["changed_lots"]))

    def test_kitchen_zero_hours(self):
        r, _ = call(self.ds, "what_if", kitchen_hours={"department_id": "KITCHEN_DELI", "hours": 0})
        self.assertLessEqual(r["net_profit_change_thb"], 0.01)

    def test_demand_scale_bounds(self):
        with self.assertRaises(ValueError):
            call(self.ds, "what_if", demand_scale=3)
        up, _ = call(self.ds, "what_if", demand_scale=1.3)
        self.assertGreater(up["net_profit_change_thb"], 0)

    def test_empty_scenario(self):
        with self.assertRaises(ValueError):
            call(self.ds, "what_if")

    def test_base_inputs_untouched(self):
        before = json.dumps(self.ds.optimize_inputs(), sort_keys=True, default=str)
        call(self.ds, "what_if", no_markdown=["ALL"], demand_scale=0.7)
        self.assertEqual(before, json.dumps(self.ds.optimize_inputs(), sort_keys=True, default=str))


class Guard(unittest.TestCase):
    EV = json.dumps({"net_profit_thb": -5116.02, "lots": 13, "lot_id": "LOT-000020", "price": 143.2,
                     "pickup_at": "2026-10-21T16:00:00+07:00", "share": 47.9}, ensure_ascii=False)

    def test_accepts_grounded_numbers(self):
        ok = "ขาดทุน 5,116.02 บาท (ประมาณ 5,116 บาท) มี 13 lot LOT-000020 ราคา 143.20 บาท รับของ 2026-10-21 16:00 น. สัดส่วน 47.9% ข้อ 3"
        self.assertEqual(guard.check(ok, self.EV), [])

    def test_rejects_invented(self):
        probs = guard.check("กำไรเพิ่ม 2,300 บาท LOT-000099 วันที่ 2026-10-30 เวลา 11:00", self.EV)
        self.assertEqual(len(probs), 4, probs)

    def test_strip_thinking(self):
        self.assertEqual(guard.strip_thinking("<thinking>คิดก่อน</thinking>ตอบ 13 lot"), "ตอบ 13 lot")
        self.assertEqual(guard.strip_thinking("<thinking>ค้าง"), "")


class AgentLoop(unittest.TestCase):
    def agent(self, scripts, hhmm="09:00"):
        ds, _ = make_ds(hhmm)
        llm = ScriptedLLM(scripts)
        return ManagerAgent(llm, ds), llm

    def test_tool_then_grounded_answer(self):
        a, llm = self.agent({NOVA: [[("get_store_snapshot", {})],
                                    "<thinking>ดูผล</thinking>วันนี้มี lot เสี่ยง 13 lot เป็น CRITICAL 4 lot และมีงานเลยกำหนด 1 งาน"]})
        out = a.ask("วันนี้มีอะไรด่วน", context={"page": "overview"})
        self.assertEqual(out["model_used"], NOVA)
        self.assertNotIn("thinking", out["answer"])
        self.assertEqual([t["name"] for t in out["tool_calls"]], ["get_store_snapshot"])
        self.assertEqual(out["artifacts"][0]["type"], "snapshot")
        # รอบที่ 2 โมเดลได้ toolResult ของรอบแรก และ role สลับถูกต้อง
        msgs = llm.seen[1][1]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertIn("toolResult", msgs[-1]["content"][0])

    def test_revise_once_then_pass(self):
        a, llm = self.agent({NOVA: [[("get_plan", {})], "กำไรดีขึ้น 9,999 บาท",
                                    "แผนนี้ดีกว่าขายปกติแล้วฝังกลบ 5,318.43 บาท"]})
        out = a.ask("แผนวันนี้ดีกว่าเดิมแค่ไหน")
        self.assertEqual(out["model_used"], NOVA)
        self.assertIn("5,318.43", out["answer"])
        self.assertTrue(any("9,999" in w for w in out["warnings"]))
        self.assertIn("ไม่ผ่านการตรวจ", llm.seen[2][1][-1]["content"][0]["text"])

    def test_fallback_reuses_tool_results(self):
        a, llm = self.agent({NOVA: [[("get_plan", {})], "กำไร 1,234 บาท", "กำไร 4,321 บาท"],
                             QWEN: ["ขาดทุนสุทธิ 5,116.02 บาท"]})
        out = a.ask("กำไรวันนี้เท่าไร")
        self.assertEqual(out["model_used"], QWEN)
        qwen_msgs = llm.seen[-1][1]
        self.assertIn("toolResult", qwen_msgs[-1]["content"][0])    # Qwen เริ่มจากผล tool ของ Nova
        self.assertEqual(len(out["tool_calls"]), 1)                 # ไม่เรียกซ้ำ

    def test_model_error_falls_back(self):
        a, _ = self.agent({NOVA: [RuntimeError("ThrottlingException")],
                           QWEN: [[("get_lot", {"lot_id": "LOT-000013"})], "LOT-000013 เหลือ 8 ชิ้น"]})
        out = a.ask("LOT-000013 เหลือเท่าไร")
        self.assertEqual(out["model_used"], QWEN)
        self.assertTrue(any("Throttling" in w for w in out["warnings"]))

    def test_template_when_all_fail(self):
        a, _ = self.agent({NOVA: [[("explain_decision", {"lot_id": "LOT-000020"})], "ลด 33%", "ลด 33%"],
                           QWEN: ["ลด 33%", "ลด 33%"]})
        out = a.ask("ทำไมลด LOT-000020")
        self.assertEqual(out["model_used"], "TEMPLATE")
        self.assertEqual(out["artifacts"][0]["type"], "lot_explain")   # การ์ดยังแสดงได้

    def test_tool_error_is_returned_to_model(self):
        a, llm = self.agent({NOVA: [[("get_lot", {"lot_id": "LOT-999999"})], "ไม่พบ lot นี้ในระบบ"]})
        out = a.ask("LOT-999999 เป็นยังไง")
        self.assertFalse(out["tool_calls"][0]["ok"])
        res = llm.seen[1][1][-1]["content"][0]["toolResult"]
        self.assertEqual(res["status"], "error")
        self.assertEqual(out["model_used"], NOVA)

    def test_tool_call_limit(self):
        many = [[("get_lot", {"lot_id": f"LOT-0000{n:02d}"})] for n in range(1, 30)]
        a, llm = self.agent({NOVA: many[: settings.MAX_TOOL_CALLS] + ["สรุปได้เท่านี้ครับ"]})
        out = a.ask("ไล่ดูทุก lot")
        self.assertEqual(len(out["tool_calls"]), settings.MAX_TOOL_CALLS)
        last_user = llm.seen[-1][1][-1]["content"]
        self.assertTrue(any(b.get("text", "").startswith("ใช้จำนวนครั้ง") for b in last_user))

    def test_context_lot_is_evidence(self):
        a, llm = self.agent({NOVA: ["คุณกำลังดู LOT-000020 อยู่ครับ"]})
        out = a.ask("lot นี้คืออะไร", context={"page": "inventory", "lot_id": "lot-000020"})
        self.assertEqual(out["model_used"], NOVA)

    def test_history_sanitized(self):
        h = [{"role": "assistant", "text": "สวัสดี"}, {"role": "user", "text": "a"}, {"role": "user", "text": "b"},
             {"role": "assistant", "text": "c"}, {"role": "system", "text": "x"}, {"role": "user", "text": "ค้าง"}]
        msgs = sanitize_history(h, 10)
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertEqual(msgs[0]["content"][0]["text"], "a\nb")


class Handler(unittest.TestCase):
    def test_warmup_and_validation(self):
        import manager_agent.handler as h
        h._llm, h._sop = object(), False                         # ไม่สร้าง boto3 client ในเทสต์
        self.assertEqual(lambda_handler({"warmup": True}), {"warmup": True})
        self.assertEqual(lambda_handler({"question": "  "})["status"], 400)
        self.assertEqual(lambda_handler({"question": "ก" * 2000})["status"], 400)


if __name__ == "__main__":
    unittest.main()
