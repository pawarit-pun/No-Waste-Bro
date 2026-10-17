"""รัน:  python -m unittest ai_engine.tests.test_optimizer -v   (ไม่ต้องมี pytest/เน็ต/Supabase)"""
from __future__ import annotations

import copy
import json
import os
import types
import unittest
from datetime import date, datetime, time

from ai_engine.clock import BKK
from ai_engine.demo.offline_snapshot import build_offline_inputs, snapshot_lots
from ai_engine.optimizer import ApiClient, OptimizerConfig, PlanValidationError, run_optimizer
from ai_engine.optimizer.config import ACTION_BY_METHOD
from ai_engine.optimizer.context import build_context
from ai_engine.optimizer.io import DEFAULT_API_BASE, load_inputs_from_supabase
from ai_engine.optimizer.models import Inputs, to_base
from ai_engine.optimizer.rules import next_pickup, partner_trip_cost, tier_price
from ai_engine.optimizer.validate import validate_plan


def at(d: str, t: str = "08:00") -> datetime:
    return datetime.combine(date.fromisoformat(d), time.fromisoformat(t), tzinfo=BKK)


NOW = at("2026-10-16")


def full_run(now=NOW, cfg=None):
    inputs, demand = build_offline_inputs(now)
    return inputs, demand, run_optimizer(inputs, demand, now, cfg)


class UnitsAndRules(unittest.TestCase):
    def test_unit_conversion_kg_and_l_times_1000(self):
        self.assertEqual(to_base(1, "KG"), (1000.0, "MASS"))
        self.assertEqual(to_base(1.5, "L"), (1500.0, "VOLUME"))
        self.assertEqual(to_base(830, "ML"), (830.0, "VOLUME"))
        self.assertEqual(to_base(None, "G"), (None, None))

    def test_tier_price_half_up(self):
        self.assertEqual(tier_price(47.5, 20), 38.0)
        self.assertEqual(tier_price(23.75, 50), 11.88)      # 11.875 -> 11.88 (half-up)

    def test_markdown_deeper_than_min_price_is_excluded(self):
        inputs, demand = build_offline_inputs(NOW)
        ctx = build_context(Inputs.from_json(inputs), demand, NOW)
        lc = ctx.lots["LOT-000001"]
        self.assertTrue(all(t["discount_pct"] <= 50 for t in lc.tiers))   # min_allowed_price = 50% ของราคาปกติ
        self.assertIn("K2_BELOW_MIN_PRICE", lc.excluded["MARKDOWN:60"])

    def test_pickup_weekday_and_time_window(self):
        inputs, _ = build_offline_inputs(at("2026-10-10"))     # วันเสาร์
        p = Inputs.from_json(inputs).partners
        cfg = OptimizerConfig()
        sat_noon = at("2026-10-10", "12:00")
        self.assertEqual(next_pickup(p["P-ANI-01"], at("2026-10-10", "08:00"), cfg).isoformat(), "2026-10-10T16:00:00+07:00")
        # เที่ยงวัน: ADG (07-10) หมดช่วงแล้ว -> วันถัดไป 07:00
        self.assertEqual(next_pickup(p["P-ADG-01"], sat_noon, cfg).isoformat(), "2026-10-11T07:00:00+07:00")
        # ศุกร์ไม่อยู่ใน pickup_days ของ ANIMAL_FEED [2,3,4,6] -> เสาร์
        self.assertEqual(next_pickup(p["P-ANI-01"], at("2026-10-16"), cfg).isoformat(), "2026-10-17T16:00:00+07:00")
        # หลัง 22:00 LANDFILL (จ-ส) รอบวันนี้ไม่ทัน
        self.assertEqual(next_pickup(p["P-LDF-01"], at("2026-10-16", "21:30"), cfg).isoformat(), "2026-10-17T20:00:00+07:00")

    def test_donation_cost_is_fixed_only(self):
        inputs, _ = build_offline_inputs(NOW)
        p = Inputs.from_json(inputs).partners
        self.assertEqual(partner_trip_cost(p["P-DON-01"]), 550.0)
        self.assertAlmostEqual(partner_trip_cost(p["P-LDF-01"]), 650 + 78.625)

    def test_donation_blocked_by_min_days_and_min_kg(self):
        inputs, demand = build_offline_inputs(NOW)
        ctx = build_context(Inputs.from_json(inputs), demand, NOW)
        self.assertIn("P4_MIN_DAYS_1D_LEFT_NEED_2", ctx.lots["LOT-000007"].excluded["DONATION:P-DON-01"])
        self.assertTrue(any(r.startswith("P7_BELOW_MIN_KG") for r in ctx.lots["LOT-000009"].excluded["COMPOSTING:P-CMP-01"]))


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs, cls.demand, cls.result = full_run()
        cls.plan, cls.payload = cls.result["plan"], cls.result["payload"]

    def test_no_violations_and_payload_ok(self):
        self.assertEqual(self.result["violations"], [])
        self.assertEqual(self.result["payload_errors"], [])
        self.assertTrue(self.plan["summary"]["reconciliation_ok"])

    def test_mass_balance_every_lot(self):
        for lo in self.plan["lots"]:
            self.assertEqual(sum(p["units"] for p in lo["portions"]), lo["quantity"], lo["lot_id"])
            self.assertAlmostEqual(sum(p["share_pct"] for p in lo["portions"]), 100.0, delta=0.05)

    def test_one_price_tier_per_lot(self):
        for lo in self.plan["lots"]:
            self.assertLessEqual(sum(p["method"] in ("SELL_REGULAR", "MARKDOWN") for p in lo["portions"]), 1)

    def test_optimized_beats_every_baseline(self):
        b = self.plan["baselines"]
        for k in ("do_nothing_no_disposal_cost", "regular_price_then_landfill", "markdown_then_landfill"):
            self.assertGreater(b["optimized"]["net_profit_thb"], b[k]["net_profit_thb"], k)

    def test_kitchen_hours_never_exceed_budget(self):
        for u in self.plan["kitchen_usage"]:
            self.assertLessEqual(u["hours_used"], u["hours_budget"] + 1e-6)

    def test_kitchen_one_decision_per_job_and_hours_not_double_booked(self):
        kitchen = [d for d in self.payload["decisions"] if d["action_type"] == "KITCHEN_REPURPOSE"]
        self.assertEqual(len(kitchen), len(self.plan["kitchen_jobs"]))
        hours = sum(self.inputs_recipe_mins(d["target_recipe_id"]) * d["batch_count"] / 60 for d in kitchen)
        self.assertAlmostEqual(hours, sum(j["hours"] for j in self.plan["kitchen_jobs"]), delta=0.05)

    def inputs_recipe_mins(self, rid):
        return next(r["estimated_prep_time_mins"] for r in self.inputs["recipes"] if r["recipe_id"] == rid)

    def test_trip_respects_min_and_capacity(self):
        for t in self.plan["trips"]:
            self.assertGreaterEqual(t["kg"] + 1e-3, t["min_kg"])
            self.assertLessEqual(t["kg"], t["capacity_kg"] + 1e-3)

    def test_payload_shape_matches_table(self):
        allowed = {"assessment_id", "action_type", "action_quantity", "discount_pct", "new_recommended_price",
                   "target_recipe_id", "batch_count", "target_partner_id", "due_by", "expected_profit_impact",
                   "decision_score", "alternatives"}
        for d in self.payload["decisions"]:
            self.assertLessEqual(set(d), allowed)
            self.assertIn(d["action_type"], {"MARKDOWN", "KITCHEN_REPURPOSE", "DONATE", "DISCARD"})
            if d["action_type"] == "MARKDOWN":
                self.assertTrue(0 < d["discount_pct"] < 100 and "batch_count" not in d)
        json.dumps(self.payload)                                   # serialise ได้

    def test_extended_mode_uses_real_partner_actions(self):
        _, _, r = full_run(cfg=OptimizerConfig(action_mode="extended"))
        types_ = {d["action_type"] for d in r["payload"]["decisions"]}
        self.assertLessEqual(types_, set(ACTION_BY_METHOD["extended"].values()))

    def test_validator_catches_tampered_plan(self):
        inputs, demand = build_offline_inputs(NOW)
        ctx = build_context(Inputs.from_json(inputs), demand, NOW)
        plan = copy.deepcopy(self.plan)
        plan["lots"][0]["portions"][0]["units"] += 1               # ทำให้จำนวนไม่สมดุล
        self.assertTrue(any(v["rule"] == "H1_MASS_BALANCE" for v in validate_plan(plan, ctx)))

    def test_nothing_at_risk_on_demo_date_2026_10_10(self):
        now = at("2026-10-10")
        inputs, demand = build_offline_inputs(now)
        r = run_optimizer(inputs, demand, now)
        self.assertEqual(r["payload"]["decisions"], [])

    def test_expired_lot_only_waste_routes(self):
        now = at("2026-10-17", "08:00")                            # LOT-000006 (หมด 10-16) หมดอายุแล้ว
        inputs, demand = build_offline_inputs(now)
        r = run_optimizer(inputs, demand, now)
        lot = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000006")
        self.assertTrue(lot["portions"] and all(p["method"] in ("LANDFILL", "ANAEROBIC_DIGESTION") for p in lot["portions"]))

    def test_waste_partner_takes_goods_even_if_pickup_after_expiry(self):
        # regression: min_days_before_expiry NULL (=0) ต้องไม่ตัด landfill เมื่อรอบรับเป็นวันหลังหมดอายุ
        now = at("2026-10-16", "21:30")                            # LANDFILL รอบวันนี้หมดแล้ว -> พรุ่งนี้ 20:00 (หลัง LOT-000006 หมดอายุ)
        inputs, demand = build_offline_inputs(now)
        r = run_optimizer(inputs, demand, now)
        self.assertEqual(r["plan"]["summary"]["unresolved_units"], 0)
        lot = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000006")
        self.assertIn("LANDFILL", {p["method"] for p in lot["portions"]})

    def test_missing_disposal_flags_deny_and_warn(self):
        inputs, demand = build_offline_inputs(NOW)
        for p in inputs["products"]:
            p.pop("allow_landfill")
        ctx = build_context(Inputs.from_json(inputs), demand, NOW)
        self.assertTrue(any("allow_" in w for w in ctx.warnings))
        self.assertTrue(all("LANDFILL:P-LDF-01" not in lc.partner_ok and "P-LDF-01" not in lc.partner_ok for lc in ctx.lots.values()))

    def test_late_in_day_shrinks_kitchen_window(self):
        now = at("2026-10-16", "15:00")                            # เหลือก่อน 17:00 แค่ ~1.5 ชม.
        inputs, demand = build_offline_inputs(now)
        r = run_optimizer(inputs, demand, now)
        today = [u for u in r["plan"]["kitchen_usage"] if u["date"] == "2026-10-16"]
        self.assertTrue(all(u["hours_used"] <= 1.5 + 1e-6 for u in today))


class Io(unittest.TestCase):
    def test_default_base_url_and_routes(self):
        calls = []

        def transport(method, url, body, headers, timeout):
            calls.append((method, url, body))
            return 200, "{}"
        c = ApiClient(transport=transport)
        c.get_scan_inputs(); c.get_optimize_inputs("abc", 1); c.post_decisions({"decisions": []})
        c.post_risk_assessments({"assessments": []}); c.set_lot_status(["LOT-000001"], "PROCESSING")
        base = "https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1/"
        self.assertEqual(DEFAULT_API_BASE, base)
        self.assertEqual([(m, u) for m, u, _ in calls], [
            ("GET", base + "ai/scan-inputs"),
            ("GET", base + "ai/optimize-inputs?run_id=abc&days_ahead=1"),
            ("POST", base + "optimization-decisions"),
            ("POST", base + "risk-assessments"),
            ("PATCH", base + "inventory-lots/ai-status")])

    def test_http_error_raises(self):
        from ai_engine.optimizer.io import ApiError
        c = ApiClient(transport=lambda *a: (422, '{"detail": "x"}'))
        with self.assertRaises(ApiError):
            c.post_decisions({})

    def test_supabase_loader_matches_offline_inputs(self):
        os.environ["DEMO_DATE"] = "2026-10-16"
        try:
            inputs, demand = build_offline_inputs(NOW)
            tables = {"lot_risk_assessments": inputs["at_risk_lots"], "products": inputs["products"],
                      "recipes": inputs["recipes"], "kitchen_capacity_daily": inputs["kitchen_capacity"],
                      "donation_partners": inputs["donation_partners"], "inventory_lots": snapshot_lots()}
            loaded = load_inputs_from_supabase(None, 1, supabase=_FakeSupabase(tables), fetch_all=_fake_fetch_all(tables))
            self.assertEqual(loaded["reference_date"], "2026-10-16")
            a = run_optimizer(inputs, demand, NOW)["plan"]["summary"]["net_profit_thb"]
            b = run_optimizer(loaded, demand, NOW)["plan"]["summary"]["net_profit_thb"]
            self.assertAlmostEqual(a, b, places=2)
        finally:
            os.environ.pop("DEMO_DATE", None)


class _StubClient:
    """จำลอง API: อ่านได้ตามข้อมูล offline, เก็บทุกการเขียนไว้ใน self.writes"""
    def __init__(self, now):
        self.now = now
        self.inputs, _ = build_offline_inputs(now)
        self.inputs["at_risk_lots"], self.inputs["run_id"] = [], None
        self.writes, self.posted = [], None

    def get_scan_inputs(self):
        return {"inventory_lots": snapshot_lots(), "sales_history": [], "average_daily_sales": []}

    def get_optimize_inputs(self, run_id=None, days_ahead=1):
        from ai_engine.forecaster.mock_forecaster import mock_forecast, to_at_risk_rows
        data = copy.deepcopy(self.inputs)
        if run_id and self.posted:
            f = {"model_version": self.posted["model_version"], "assessments": self.posted["assessments"]}
            ids = {a["lot_id"]: f"id-{a['lot_id']}" for a in f["assessments"]}
            data["run_id"] = run_id
            data["at_risk_lots"] = to_at_risk_rows(snapshot_lots(), f, run_id, ids, self.now)
        return data

    def set_lot_status(self, lot_ids, status): self.writes.append(("PATCH", status, len(lot_ids)))

    def post_risk_assessments(self, payload):
        self.writes.append(("POST", "risk-assessments")); self.posted = payload
        return {"run_id": "run-1", "created": len(payload["assessments"]),
                "assessments": [{"assessment_id": f"id-{a['lot_id']}", "lot_id": a["lot_id"]} for a in payload["assessments"]]}

    def post_decisions(self, payload):
        self.writes.append(("POST", "optimization-decisions", len(payload["decisions"])))
        return {"created": len(payload["decisions"]), "decisions": []}


class Pipeline(unittest.TestCase):
    def test_dry_run_never_writes(self):
        from ai_engine.optimizer import run_full_pipeline
        c = _StubClient(NOW)
        r = run_full_pipeline(c, dry_run=True, now=NOW)
        self.assertEqual(c.writes, [])
        self.assertEqual(len(r["payload"]["decisions"]), 15)
        self.assertIsNone(r["posted"])

    def test_real_run_writes_in_pipeline_order(self):
        from ai_engine.optimizer import run_full_pipeline
        c = _StubClient(NOW)
        r = run_full_pipeline(c, dry_run=False, now=NOW)
        self.assertEqual([w[:2] for w in c.writes],
                         [("PATCH", "PROCESSING"), ("POST", "risk-assessments"), ("POST", "optimization-decisions")])
        self.assertEqual(r["posted"]["created"], 15)

    def test_optimize_and_post_dry_run_default(self):
        from ai_engine.optimizer import optimize_and_post
        c = _StubClient(NOW)
        c.inputs, demand = build_offline_inputs(NOW)
        c.get_optimize_inputs = lambda run_id=None, days_ahead=1: copy.deepcopy(c.inputs)
        r = optimize_and_post(c, demand=demand, now=NOW)            # dry_run เป็นค่าเริ่มต้น
        self.assertEqual(c.writes, [])
        r = optimize_and_post(c, demand=demand, now=NOW, dry_run=False)
        self.assertEqual(c.writes, [("POST", "optimization-decisions", 15)])


class _Q:
    def __init__(self, rows): self.rows = list(rows)
    def select(self, *a, **k): return self
    def eq(self, c, v): self.rows = [r for r in self.rows if r.get(c) == v]; return self
    def in_(self, c, vs): self.rows = [r for r in self.rows if r.get(c) in vs]; return self
    def gte(self, c, v): self.rows = [r for r in self.rows if r.get(c) >= v]; return self
    def lte(self, c, v): self.rows = [r for r in self.rows if r.get(c) <= v]; return self
    def order(self, *a, **k): return self
    def limit(self, n): self.rows = self.rows[:n]; return self
    def execute(self): return types.SimpleNamespace(data=self.rows)


class _FakeSupabase:
    def __init__(self, tables): self.tables = tables
    def table(self, name): return _Q(self.tables.get(name, []))
    def rpc(self, name, args): return _Q([])


def _fake_fetch_all(tables):
    def fetch_all(table, columns="*", in_filter=None, order_by=()):
        rows = tables[table]
        return [r for r in rows if in_filter is None or r.get(in_filter[0]) in in_filter[1]]
    return fetch_all


if __name__ == "__main__":
    unittest.main()
