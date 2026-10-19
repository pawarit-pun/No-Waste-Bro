"""รัน (จากโฟลเดอร์ AI/food_waste_optimizer):  python -m unittest ai_engine.tests.test_optimizer -v

ข้อมูลทดสอบ = fixtures/supabase_2026-10-16.json คือผลจริงของ GET /ai/optimize-inputs และ GET /products บน Supabase
(รอบสแกน 16 ต.ค.) เทสต์ที่ต้องการกรณีที่ข้อมูลวันนั้นไม่มี (เช่น บริจาคผ่าน, ครัวใช้วัตถุดิบแบบ FEFO) จะแก้สำเนาของ
ข้อมูลนี้ในเทสต์เองและบอกไว้ในชื่อเทสต์ ไม่ได้ใช้ตอนรันจริง
"""
from __future__ import annotations

import copy
import json
import os
import unittest
from unittest import mock
from datetime import date, datetime
from pathlib import Path

from ai_engine.optimizer import (ApiClient, OptimizerConfig, PlanValidationError, optimize_and_post, run_optimizer,
                                 simulated_now)
from ai_engine.optimizer.config import BKK
from ai_engine.optimizer.context import build_context
from ai_engine.optimizer.demand import remaining_fraction
from ai_engine.optimizer.models import Inputs, to_base
from ai_engine.optimizer.rules import partner_trip_cost, tier_price
from ai_engine.optimizer.validate import fefo_simulation, validate_plan

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "supabase_2026-10-16.json").read_text(encoding="utf-8"))
REAL = FIXTURE["optimize_inputs"]
PRODUCTS = FIXTURE["products"]


def at(hhmm: str, day: str = "2026-10-16") -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}:00+07:00")


def run(inputs=None, hhmm="09:00", **kw):
    return run_optimizer(inputs or REAL, products_catalog=kw.pop("products", PRODUCTS), now=at(hhmm), **kw)


def forward(inputs: dict, lot_id: str, shelf: list) -> dict:
    """(เฉพาะเทสต์) ทำให้ lot ที่ Risk Scanner ไม่ได้ส่งต่อในวันนั้น กลายเป็น HIGH พร้อม shelf"""
    lot = next(l for l in FIXTURE_LOTS if l["lot_id"] == lot_id)
    row = {"assessment_id": f"00000000-0000-0000-0000-{lot_id[-6:]:0>12}", "run_id": inputs["run_id"], "lot_id": lot_id,
           "assessed_at": "2026-10-16T08:00:00+07:00",
           "days_to_expiry": (date.fromisoformat(lot["expiration_date"]) - date(2026, 10, 16)).days,
           "sellable_hours": None, "quantity_at_assessment": lot["current_quantity"], "forecast_daily_demand": 10.0,
           "predicted_units_sold_before_expiry": shelf[0]["expected_qty"],
           "predicted_leftover_units": lot["current_quantity"] - shelf[0]["expected_qty"],
           "sell_through_probability": 0.0, "risk_score": 60.0, "risk_level": "HIGH", "model_version": "test",
           "lot": dict(lot, ai_status="PROCESSING"), "shelf": shelf}
    inputs["at_risk_lots"].append(row)
    return inputs


def _lots_from_stock() -> list:
    """lot ทั้งหมดของวัตถุดิบจาก ingredient_stock (เติมราคา/ต้นทุนจากสินค้า ใช้เฉพาะเทสต์ forward)"""
    rows = []
    for s in REAL["ingredient_stock"]:
        p = next(p for p in PRODUCTS if p["product_id"] == s["product_id"])
        for lot in s["lots"]:
            rows.append(dict(lot, product_id=s["product_id"], unit_cost=p["base_cost"],
                             current_selling_price=p["regular_price"], received_date="2026-10-14",
                             initial_quantity=lot["current_quantity"], ai_status="IDLE"))
    return rows


FIXTURE_LOTS = _lots_from_stock()


def shelf_rows(price, rows, until):
    return [{"discount_pct": d, "price": tier_price(price, d), "expected_qty": e, "low_qty": lo, "high_qty": hi,
             "applies_from": "2026-10-16", "applies_until": until, "lost_sales_other_lots": 0.0} for d, e, lo, hi in rows]


class Units(unittest.TestCase):
    def test_unit_conversion_kg_l_times_1000(self):
        self.assertEqual(to_base(1, "KG"), (1000.0, "MASS"))
        self.assertEqual(to_base(1.5, "L"), (1500.0, "VOLUME"))
        self.assertEqual(to_base(830, "ML"), (830.0, "VOLUME"))

    def test_tier_price_half_up(self):
        self.assertEqual(tier_price(115.5, 30), 80.85)
        self.assertEqual(tier_price(23.75, 50), 11.88)       # 11.875 -> 11.88

    def test_now_is_reference_date_plus_wall_clock(self):
        now = simulated_now(date(2026, 10, 16), datetime(2026, 10, 19, 16, 15, 30, tzinfo=BKK))
        self.assertEqual(now.isoformat(), "2026-10-16T16:15:30+07:00")

    def test_open_hours_fraction(self):
        cfg = OptimizerConfig()
        self.assertAlmostEqual(remaining_fraction(at("09:00"), date(2026, 10, 16), date(2026, 10, 16), cfg), 13 / 14)
        self.assertAlmostEqual(remaining_fraction(at("16:15"), date(2026, 10, 16), date(2026, 10, 17), cfg), 19.75 / 28)
        self.assertEqual(remaining_fraction(at("22:30"), date(2026, 10, 16), date(2026, 10, 16), cfg), 0.0)


class Rules(unittest.TestCase):
    def setUp(self):
        self.ctx = build_context(Inputs.from_json(REAL, PRODUCTS), at("09:00"))

    def test_only_levels_the_forecaster_sent(self):
        lc = self.ctx.lots["LOT-000006"]
        self.assertEqual(lc.excluded["MARKDOWN:40"], ["K3_NOT_FORECAST"])
        self.assertTrue(all(t["discount_pct"] in (0, 20, 30, 50) for t in lc.tiers))

    def test_expired_lot_has_no_price_options(self):
        self.assertEqual(self.ctx.lots["LOT-000013"].tiers, [])
        self.assertEqual(self.ctx.lots["LOT-000013"].excluded["MARKDOWN:ALL"], ["K0_EXPIRED"])

    def test_pickup_weekday_and_window(self):          # 2026-10-16 = วันศุกร์ (5)
        p = self.ctx.partners
        self.assertEqual(p["P-ANI-01"].pickup.isoformat(), "2026-10-17T16:00:00+07:00")   # [2,3,4,6] -> เสาร์
        self.assertEqual(p["P-LDF-01"].pickup.isoformat(), "2026-10-16T20:00:00+07:00")
        self.assertEqual(p["P-DON-01"].pickup.isoformat(), "2026-10-16T10:00:00+07:00")   # 09:00 + เตรียม 60 นาที
        late = build_context(Inputs.from_json(REAL, PRODUCTS), at("21:30")).partners
        self.assertEqual(late["P-LDF-01"].pickup.isoformat(), "2026-10-17T20:00:00+07:00")

    def test_trip_cost_formula(self):
        p = self.ctx.inputs.partners
        self.assertEqual(partner_trip_cost(p["P-DON-01"]), 550.0)                  # DONATION: fixed เท่านั้น
        self.assertAlmostEqual(partner_trip_cost(p["P-LDF-01"]), 650 + 78.625)     # fixed + travel

    def test_partner_rules_on_real_data(self):
        lc = self.ctx.lots["LOT-000011"]
        self.assertIn("P4_MIN_DAYS 1d at pickup < 2d", lc.excluded["DONATION:P-DON-01"])
        self.assertTrue(lc.excluded["COMPOSTING:P-CMP-01"][0].startswith("P7_BELOW_MIN_KG"))
        self.assertIn("P2_CATEGORY_SEAFOOD_NOT_ACCEPTED", self.ctx.lots["LOT-000006"].excluded["ANIMAL_FEED:P-ANI-01"])

    def test_missing_disposal_flags_are_denied(self):
        ctx = build_context(Inputs.from_json(REAL), at("09:00"))           # ไม่ส่ง GET /products
        self.assertTrue(any(w.startswith("W0_DISPOSAL_FLAGS_MISSING") for w in ctx.warnings))
        self.assertNotIn("P-LDF-01", ctx.lots["LOT-000011"].partner_ok)


class RealDataPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = run()
        cls.plan, cls.payload = cls.r["plan"], cls.r["payload"]

    def test_clean_and_reconciled(self):
        self.assertEqual(self.r["violations"], [])
        self.assertEqual(self.r["payload_errors"], [])
        self.assertTrue(self.plan["summary"]["reconciliation_ok"])
        self.assertEqual(self.plan["summary"]["unresolved_units"], 0)

    def test_every_unit_of_every_lot_has_a_route(self):
        for lo in self.plan["lots"]:
            self.assertEqual(sum(p["units"] for p in lo["portions"]), lo["quantity"], lo["lot_id"])
        for lot_id in {a["lot_id"] for a in self.r["allocations"]}:
            share = sum(a["share_pct"] for a in self.r["allocations"] if a["lot_id"] == lot_id)
            self.assertAlmostEqual(share, 100.0, delta=0.05)

    def test_salmon_goes_to_kitchen_before_it_expires(self):
        job = self.plan["kitchen_jobs"][0]
        self.assertEqual((job["recipe_id"], job["anchor_lot_id"], job["batches"], job["anchor_units"]),
                         ("RCP-003", "LOT-000006", 1, 3))             # 900 g / 300 g ต่อแพ็ก = 3 แพ็ก
        self.assertLessEqual(job["expected_sold_units"], job["menu_demand_cap"] + 0.01)

    def test_beats_baselines(self):
        b = self.plan["baselines"]
        self.assertGreaterEqual(b["optimized"]["net_profit_thb"], b["regular_price_then_landfill"]["net_profit_thb"])
        self.assertGreaterEqual(b["optimized"]["net_profit_thb"], b["markdown_then_landfill"]["net_profit_thb"])

    def test_payload_matches_table_columns_without_weight_or_share(self):
        allowed = {"assessment_id", "action_type", "action_quantity", "discount_pct", "new_recommended_price",
                   "target_recipe_id", "batch_count", "target_partner_id", "due_by", "expected_profit_impact",
                   "decision_score", "alternatives"}
        for d in self.payload["decisions"]:
            self.assertLessEqual(set(d), allowed)
            self.assertNotIn("weight_kg", json.dumps(d))
            self.assertNotIn("share_pct", json.dumps(d))
        self.assertIn("weight_kg", self.r["allocations"][0])
        self.assertIn("share_pct", self.r["allocations"][0])
        json.dumps(self.payload)

    def test_kitchen_decision_is_bookable(self):
        k = [d for d in self.payload["decisions"] if d["action_type"] == "KITCHEN_REPURPOSE"]
        self.assertEqual(len(k), 1)
        self.assertEqual((k[0]["batch_count"], k[0]["due_by"]), (1, "2026-10-16T17:00:00+07:00"))

    def test_rag_can_see_why_options_were_rejected(self):
        d = next(d for d in self.payload["decisions"] if d["assessment_id"].startswith("c1ccb78e"))
        options = {a.get("option") for a in d["alternatives"]}
        self.assertIn("DONATION:P-DON-01", options)
        self.assertTrue(any(a.get("scope") == "WHOLE_LOT" for a in d["alternatives"]))


class TimeOfDay(unittest.TestCase):
    def test_late_afternoon_no_kitchen_and_less_shelf_demand(self):
        r = run(hhmm="16:15")
        self.assertEqual(r["plan"]["kitchen_jobs"], [])
        self.assertTrue(any(x.startswith("U3_KITCHEN_HOURS") for x in r["plan"]["recipes"]["RCP-003"]["reasons"]))
        lot6 = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000006")
        self.assertAlmostEqual(lot6["demand_fraction"], 5.75 / 14, places=3)

    def test_every_hour_of_the_day_is_valid(self):
        for hhmm in ("00:30", "07:59", "08:00", "10:00", "12:00", "16:45", "20:30", "21:59", "23:30"):
            r = run(hhmm=hhmm, with_baselines=False)
            self.assertEqual(r["violations"], [], hhmm)
            self.assertTrue(r["plan"]["summary"]["reconciliation_ok"], hhmm)


class Lifecycle(unittest.TestCase):
    def test_rerun_skips_assessments_that_already_have_decisions(self):
        first = run(with_baselines=False)
        decided = {d["assessment_id"] for d in first["payload"]["decisions"]}
        again = run(with_baselines=False, decided=decided)
        self.assertEqual(again["payload"]["decisions"], [])
        self.assertTrue(all("A0_ALREADY_DECIDED" in v["reasons"] for v in again["plan"]["skipped_lots"].values()))

    def test_checked_lots_are_skipped(self):
        data = copy.deepcopy(REAL)
        data["at_risk_lots"][0]["lot"]["ai_status"] = "CHECKED"
        r = run(data, with_baselines=False)
        self.assertIn(data["at_risk_lots"][0]["lot_id"], r["plan"]["skipped_lots"])

    def test_stops_when_server_date_is_not_the_scan_date(self):
        data = copy.deepcopy(REAL)
        data["reference_date"] = "2026-10-10"            # server/.env ยังเป็น DEMO_DATE=2026-10-10
        with self.assertRaises(PlanValidationError) as e:
            run_optimizer(data, products_catalog=PRODUCTS, now=at("09:00", "2026-10-10"))
        self.assertEqual(e.exception.violations[0]["rule"], "H0_SCAN_DATE_MISMATCH")
        self.assertIn("DEMO_DATE=2026-10-16", e.exception.violations[0]["detail"])

    def test_validator_catches_tampered_plan(self):
        r = run(with_baselines=False)
        ctx = build_context(Inputs.from_json(REAL, PRODUCTS), at("09:00"))
        plan = copy.deepcopy(r["plan"])
        plan["lots"][0]["portions"][0]["units"] += 1
        self.assertTrue(any(v["rule"] == "H1_MASS_BALANCE" for v in validate_plan(plan, ctx)))


class TestOnlyScenarios(unittest.TestCase):
    """สำเนาข้อมูลจริงที่แก้ในเทสต์ เพื่อให้เห็นกรณีที่ข้อมูลวันที่ 16 ไม่มี"""

    def test_donation_wins_only_when_it_is_the_cheaper_route(self):
        # ไม่มีส่วนลดภาษีแล้ว: บริจาคมีแต่ค่า fixed 550 บาท/เที่ยว ถ้ารถ landfill มารับของอื่นอยู่แล้ว ค่าทิ้งเพิ่มแค่ 1.15 บาท/kg
        # เทสต์นี้ให้ landfill ไม่รับ DAIRY และนมล็อตใหม่ขายไม่ทัน -> ธนาคารอาหาร (550) ถูกกว่าก๊าซชีวภาพ (1,850 + ขั้นต่ำ 100 kg)
        data = forward(copy.deepcopy(REAL), "LOT-000002", shelf_rows(47.5, [(0, 10, 5, 15)], "2026-10-24"))
        for partner in data["donation_partners"]:
            if partner["partner_id"] == "P-LDF-01":
                partner["accepted_categories"] = [c for c in partner["accepted_categories"] if c != "DAIRY"]
        r = run(data, with_baselines=False)
        self.assertEqual(r["violations"], [])
        self.assertEqual(r["payload_errors"], [])
        lot = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000002")
        self.assertIn("DONATION", {p["method"] for p in lot["portions"]})
        donate = next(d for d in r["payload"]["decisions"] if d["action_type"] == "DONATE")
        self.assertEqual((donate["target_partner_id"], donate["due_by"]), ("P-DON-01", "2026-10-16T10:00:00+07:00"))
        bread = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000013")
        self.assertNotIn("DONATION", {p["method"] for p in bread["portions"]})          # หมดอายุ: ห้ามบริจาค
        self.assertIn("P5_EXPIRED_FOR_HUMAN_USE", bread["explain"]["excluded"]["DONATION:P-DON-01"])

    def test_kitchen_fefo_deducts_the_earliest_expiring_lot(self):
        # ขนมปังพุดดิ้ง (RCP-006) ใช้นม + ขนมปัง: decision ผูกกับ lot หลักตัวหนึ่ง อีกตัว DB ตัดแบบ FEFO ตอน complete
        data = copy.deepcopy(REAL)
        data = forward(data, "LOT-000009", shelf_rows(40.0, [(0, 20, 15, 25), (30, 24, 18, 30)], "2026-10-17"))
        data = forward(data, "LOT-000001", shelf_rows(47.5, [(0, 40, 30, 50), (20, 44, 34, 54)], "2026-10-18"))
        for rd in data["recipe_demand"]:
            if rd["recipe_id"] == "RCP-006":
                rd.update(menu_qty=60.0, low_qty=48.0, high_qty=72.0, current_stock=0)
        r = run(data, with_baselines=False)
        self.assertEqual(r["violations"], [])            # รวม H6: แผนตรงกับการตัดสต็อกแบบ FEFO ของ DB
        jobs = [j for j in r["plan"]["kitchen_jobs"] if j["recipe_id"] == "RCP-006"]
        self.assertTrue(jobs)
        fefo = [x for j in jobs for x in j["inputs"] if x["role"] != "ANCHOR"]
        self.assertTrue(fefo)
        self.assertEqual({x["lot_id"] for x in fefo}, {"LOT-000009"})   # LOT-000013 หมดอายุแล้ว DB ไม่ตัด
        ctx = build_context(Inputs.from_json(data, PRODUCTS), at("09:00"))
        self.assertEqual(fefo_simulation(r["plan"], ctx)["short"], [])
        lot9 = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000009")
        self.assertIn("KITCHEN_INGREDIENT", {p["method"] for p in lot9["portions"]})
        covered = [a for a in r["allocations"] if a["method"] == "KITCHEN_INGREDIENT"]
        self.assertTrue(all(a["covered_by_decision_index"] is not None for a in covered))


class Io(unittest.TestCase):
    def _client(self, writes):
        def transport(method, url, body, headers, timeout):
            route = url.split("/api/v1/")[1].split("?")[0]
            if method == "GET" and route == "ai/optimize-inputs":
                return 200, json.dumps(REAL)
            if method == "GET" and route == "products":
                return 200, json.dumps(PRODUCTS)
            if method == "GET" and route == "optimization-decisions":
                return 200, json.dumps({"run_id": None, "decisions": []})
            writes.append((method, route, json.loads(body)))
            if route == "optimization-decisions":
                n = len(json.loads(body)["decisions"])
                return 201, json.dumps({"created": n, "decisions": [{"decision_id": f"d{i}"} for i in range(n)]})
            return 200, json.dumps({"updated": [], "not_found": []})
        return ApiClient("http://127.0.0.1:8000/api/v1", transport=transport)

    def test_default_base_is_local_server(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ApiClient().base_url, "http://127.0.0.1:8000/api/v1/")

    def test_dry_run_never_writes(self):
        writes = []
        r = optimize_and_post(self._client(writes), now=at("09:00"), dry_run=True)
        self.assertEqual(writes, [])
        self.assertTrue(r["payload"]["decisions"])

    def test_real_run_posts_and_links_decision_ids(self):
        writes = []
        r = optimize_and_post(self._client(writes), now=at("09:00"), dry_run=False)
        self.assertEqual([w[:2] for w in writes][0], ("POST", "optimization-decisions"))
        self.assertTrue(all(a.get("decision_id") for a in r["allocations"] if a["decision_index"] is not None))


if __name__ == "__main__":
    unittest.main()