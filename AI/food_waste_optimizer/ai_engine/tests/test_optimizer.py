"""รัน (จากโฟลเดอร์ AI/food_waste_optimizer):  python -m unittest ai_engine.tests.test_optimizer -v

ข้อมูลทดสอบ = fixtures/supabase_2026-10-16.json คือผลจริงของ GET /ai/optimize-inputs และ GET /products บน Supabase
(รอบสแกน 16 ต.ค.; donation_partners + waste_history อัปเดตตาม Supabase วันที่ 22 ต.ค.) เทสต์ที่ต้องการกรณีที่ข้อมูลวันนั้นไม่มี (เช่น บริจาคผ่าน, ครัวใช้วัตถุดิบแบบ FEFO) จะแก้สำเนาของ
ข้อมูลนี้ในเทสต์เองและบอกไว้ในชื่อเทสต์ ไม่ได้ใช้ตอนรันจริง
"""
from __future__ import annotations

import copy
import json
import math
import os
import unittest
from unittest import mock
from datetime import date, datetime, timedelta
from pathlib import Path

from ai_engine.optimizer import (ApiClient, OptimizerConfig, PlanValidationError, optimize_and_post, run_optimizer,
                                 simulated_now)
from ai_engine.optimizer.config import BKK
from ai_engine.optimizer.context import build_context
from ai_engine.optimizer.demand import expected_sold, remaining_fraction, survival_segments
from ai_engine.optimizer.models import Inputs, to_base
from ai_engine.optimizer.rules import calls_per_week, max_pickup_gap, partner_trip_cost, sell_end, tier_price
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

    def test_no_expected_sales_still_stays_on_shelf(self):
        # บั๊กเดิม: ราคาปกติคาดว่าขายไม่ได้ (P10 = P50 = P90 = 0 เมื่อ lot อื่นรับลูกค้าไปก่อน) -> tier 0 ถูกตัดด้วย K5
        # solver ไม่มีทางวางขายต่อ ต้องดึงทั้ง lot ไปฝังกลบตอนเช้า ทั้งที่ทิ้งหลังปิดร้านเสียเท่ากันและยังมีโอกาสขาย
        data = copy.deepcopy(REAL)
        salmon = next(r for r in data["at_risk_lots"] if r["lot"]["lot_id"] == "LOT-000006")
        salmon["shelf"] = shelf_rows(salmon["lot"]["current_selling_price"], [(0, 0, 0, 0)], "2026-10-16")
        for hhmm in ("09:00", "21:30"):
            r = run(data, hhmm, with_baselines=False)
            self.assertEqual(r["violations"], [], hhmm)
            lot = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000006")
            self.assertIn("SELL_REGULAR", {p["method"] for p in lot["portions"]}, hhmm)
            self.assertFalse(any(p["details"].get("timing") == "NOW" for p in lot["portions"]), hhmm)
        closed = build_context(Inputs.from_json(data, PRODUCTS), at("22:30")).lots["LOT-000006"]
        self.assertEqual(closed.tiers, [])                                  # ร้านปิดแล้ว ไม่เหลือเวลาขาย
        self.assertEqual(closed.excluded["MARKDOWN:0"], ["K5_NO_SALES_EXPECTED"])

    def test_lost_sales_cost_full_price_plus_disposal(self):
        # ล็อตอื่นซื้อมาแล้ว (ต้นทุนจม): ขายไม่ออก 1 หน่วย = เสียรายได้เต็มราคา + ค่ากำจัดหน่วยนั้น (ไม่ใช่แค่ margin)
        data = copy.deepcopy(REAL)
        salmon = next(r for r in data["at_risk_lots"] if r["lot"]["lot_id"] == "LOT-000006")
        salmon["shelf"] = shelf_rows(salmon["lot"]["current_selling_price"], [(0, 5, 3, 8), (20, 12, 9, 15)], "2026-10-16")
        salmon["shelf"][1]["lost_sales_other_lots"] = 2.0
        ctx = build_context(Inputs.from_json(data, PRODUCTS), at("08:00"))          # 08:00 = เต็มวัน ไม่ต้องปรับตามเวลา
        lc = ctx.lots["LOT-000006"]
        tier = next(t for t in lc.tiers if t["discount_pct"] == 20)
        per_unit = min(ctx.partners[pid].cost_per_kg * lc.weight_kg for pid in lc.eol)
        self.assertGreater(per_unit, 0)
        self.assertAlmostEqual(tier["lost_sales_cost"], 2.0 * (lc.product.regular_price + per_unit), delta=0.02)

    def test_pickup_weekday_and_window(self):          # 2026-10-16 = วันศุกร์ (5)
        p = self.ctx.partners
        # อาหารสัตว์โหมด BIN: รอถังถึงปริมาณที่คุ้ม (~2.33 วัน -> อาทิตย์ 18 ต.ค.) รอบถัดไป [2,3,4,6] = อังคาร 20 ต.ค.
        # เกินเพดานเวลา (3 วัน = 19 ต.ค. 10:00) -> ใช้รอบสุดท้ายก่อนเพดาน = เสาร์ 17 ต.ค.
        self.assertEqual(p["P-ANI-01"].pickup.isoformat(), "2026-10-17T16:00:00+07:00")
        # landfill: ถังว่างรอถึง 6.2 kg (~1.75 วัน -> อาทิตย์ไม่มีรอบ จันทร์ 19 ต.ค. เกินเพดาน 2 วัน) -> เสาร์ 17 ต.ค.
        self.assertEqual(p["P-LDF-01"].pickup.isoformat(), "2026-10-17T20:00:00+07:00")
        self.assertEqual(p["P-DON-01"].pickup.isoformat(), "2026-10-16T10:00:00+07:00")   # DEDICATED: 09:00 + เตรียม 60 นาที
        late = build_context(Inputs.from_json(REAL, PRODUCTS), at("21:30")).partners
        self.assertEqual(late["P-LDF-01"].pickup.isoformat(), "2026-10-17T20:00:00+07:00")

    def test_trip_cost_formula(self):
        p = self.ctx.inputs.partners
        self.assertEqual(partner_trip_cost(p["P-DON-01"]), 550.0)                  # DONATION: fixed เท่านั้น
        self.assertAlmostEqual(partner_trip_cost(p["P-LDF-01"]), 650 + 78.625)     # fixed + travel

    def test_partner_rules_on_real_data(self):
        lc = self.ctx.lots["LOT-000011"]
        self.assertIn("P4_MIN_DAYS 1d at pickup < 2d", lc.excluded["DONATION:P-DON-01"])
        self.assertIn("P-CMP-01", lc.partner_ok)             # ปุ๋ยหมักโหมด BIN: ขั้นต่ำต่อถัง ไม่ใช่ต่อรอบ (ไม่มี P7)
        data = copy.deepcopy(REAL)                           # ไม่มีประวัติของทิ้ง -> DEDICATED -> ขั้นต่ำต่อรอบ (P7)
        data.pop("waste_history")
        for partner in data["donation_partners"]:
            if partner["partner_id"] == "P-CMP-01":
                partner["min_kg_per_pickup"] = 100
        lc = build_context(Inputs.from_json(data, PRODUCTS), at("09:00")).lots["LOT-000011"]
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
                         ("RCP-003", "LOT-000006", 2, 6))             # 900 g / 300 g ต่อแพ็ก = 3 แพ็ก ต่อ batch
        self.assertLessEqual(job["expected_sold_units"], job["menu_demand_cap"] + 0.01)
        self.assertGreater(job["net_profit_thb"], 0)

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
        # เริ่ม 09:30 (ตอนนี้ + 30 นาที) + 45 นาที x 2 batch = เสร็จ 11:00 ไม่ใช่ 17:00 ตายตัว
        self.assertEqual((k[0]["batch_count"], k[0]["due_by"]), (2, "2026-10-16T11:00:00+07:00"))

    def test_rag_can_see_why_options_were_rejected(self):
        d = next(d for d in self.payload["decisions"] if d["assessment_id"].startswith("eb742153"))   # สลัดไก่
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
        self.assertNotIn("LOT-000013", {x["lot_id"] for x in fefo})      # LOT-000013 หมดอายุแล้ว DB ไม่ตัด
        self.assertLessEqual({x["lot_id"] for x in fefo}, {"LOT-000009", "LOT-000001"})
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
            if method == "GET" and route == "ai/optimize-runs":
                return 200, json.dumps({"reference_date": REAL["reference_date"], "suggested_run_id": REAL["run_id"],
                                        "runs": []})
            if method == "GET" and route == "optimization-decisions":
                return 200, json.dumps({"run_id": None, "decisions": []})
            writes.append((method, route, json.loads(body)))
            if route == "optimization-decisions":
                n = len(json.loads(body)["decisions"])
                return 201, json.dumps({"created": n, "decisions": [{"decision_id": f"d{i}"} for i in range(n)]})
            return 200, json.dumps({"updated": [], "not_found": []})
        return ApiClient("http://127.0.0.1:8000/api/v1", transport=transport)

    def test_default_base_is_aws_server(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ApiClient().base_url, "https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1/")

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


class NewsvendorDemand(unittest.TestCase):
    """ยอดขายจาก P10/P50/P90 แทน demand_kappa (demand.survival_segments)"""

    def test_segments_follow_quantiles(self):
        segs = survival_segments(20, 13, 27)                 # P50 = 20, P10 = 13, P90 = 27
        self.assertEqual([round(w, 6) for w, _ in segs], [13, 7, 7, 7])
        self.assertEqual([round(p, 3) for _, p in segs], [0.95, 0.7, 0.3, 0.05])
        self.assertAlmostEqual(expected_sold(segs, 1000), 13 * .95 + 7 * .7 + 7 * .3 + 7 * .05)
        self.assertLess(expected_sold(segs, 15), 15)          # วางของ 15 ชิ้น ไม่ได้ขายหมดแน่นอน

    def test_no_uncertainty_sells_exactly(self):
        self.assertEqual(survival_segments(5, 5, 5), [(5.0, 1.0)])
        self.assertEqual(expected_sold(survival_segments(5, 5, 5), 8), 5.0)

    def test_limit_cuts_width(self):
        self.assertAlmostEqual(sum(w for w, _ in survival_segments(20, 13, 27, limit=10)), 10)

    def test_shelf_and_end_of_life_add_up(self):
        r = run(with_baselines=False)
        lot = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000012")
        sale = next(p for p in lot["portions"] if p["method"] == "SELL_REGULAR")
        eol = [p for p in lot["portions"] if p["details"].get("timing") == "END_OF_LIFE"]
        self.assertTrue(eol)
        self.assertEqual(sale["units"] + sum(p["units"] for p in eol), sale["details"]["shelf_units"])
        self.assertAlmostEqual(sale["details"]["expected_sold"] + sum(p["details"]["expected_units"] for p in eol),
                               sale["details"]["shelf_units"], places=2)


class EndOfLifePickup(unittest.TestCase):
    def setUp(self):
        self.ctx = build_context(Inputs.from_json(REAL, PRODUCTS), at("09:00"))

    def test_pickup_after_selling_ends(self):
        # landfill โหมด BIN: ของเหลือเข้าถังหลังร้านปิด 22:00 แล้วรอถังถึงปริมาณที่คุ้ม (6.2 kg ≈ 1.75 วัน)
        # สลัด: รอบหลังถังเต็ม = จันทร์ 19 ต.ค. เกินเพดาน 2 วัน (18 ต.ค. 22:00) -> รอบสุดท้ายก่อนเพดาน = เสาร์ 17 ต.ค.
        lots, ldf = self.ctx.lots, self.ctx.partners["P-LDF-01"]
        self.assertEqual(sell_end(lots["LOT-000012"].lot, self.ctx.cfg).isoformat(), "2026-10-16T22:00:00+07:00")
        self.assertLessEqual(lots["LOT-000012"].eol["P-LDF-01"], at("22:00") + timedelta(days=ldf.max_wait_days))
        self.assertEqual(lots["LOT-000012"].eol["P-LDF-01"].isoformat(), "2026-10-17T20:00:00+07:00")
        self.assertEqual(lots["LOT-000011"].eol["P-LDF-01"].isoformat(), "2026-10-19T20:00:00+07:00")   # 17 ต.ค. + 1.75 วัน
        self.assertEqual(lots["LOT-000013"].eol, {})                     # หมดอายุแล้ว ไม่มีของวางขาย

    def test_same_day_trips_are_merged(self):
        self.assertEqual(self.ctx.slots[("P-LDF-01", date(2026, 10, 17))].isoformat(), "2026-10-17T20:00:00+07:00")
        r = run(with_baselines=False)
        self.assertEqual(len({t["trip_id"] for t in r["plan"]["trips"]}), len(r["plan"]["trips"]))
        for t in r["plan"]["trips"]:
            self.assertEqual(t["trip_id"], f"{t['partner_id']}@{t['pickup_at'][:10]}")

    def test_validator_rejects_eol_before_selling_ends(self):
        r = run(with_baselines=False)
        plan = copy.deepcopy(r["plan"])
        lot = next(l for l in plan["lots"] if l["lot_id"] == "LOT-000012")
        p = next(p for p in lot["portions"] if p["details"].get("timing") == "END_OF_LIFE")
        p["details"]["pickup_at"] = "2026-10-16T20:00:00+07:00"
        self.assertTrue(any(v["rule"] == "H4_PICKUP_SLOT" for v in validate_plan(plan, self.ctx)))

    def test_eol_decision_carries_pickup_time(self):
        r = run(with_baselines=False)
        eol = [a for a in r["allocations"] if a["details"].get("timing") == "END_OF_LIFE" and a["decision_index"] is not None]
        self.assertTrue(eol)
        d = r["payload"]["decisions"][eol[0]["decision_index"]]
        self.assertEqual(d["due_by"], eol[0]["details"]["pickup_at"])
        self.assertEqual(d["alternatives"][0]["timing"], "END_OF_LIFE")

    def test_scheduled_trips_drop_fixed_cost(self):
        cfg = OptimizerConfig(trip_cost_mode="scheduled")
        ctx = build_context(Inputs.from_json(REAL, PRODUCTS), at("09:00"), cfg)
        self.assertEqual(ctx.partners["P-LDF-01"].trip_cost, 0.0)
        self.assertEqual(ctx.partners["P-ADG-01"].min_kg, 0.0)
        r = run(with_baselines=False, cfg=cfg)
        self.assertEqual(r["violations"], [])
        self.assertNotIn("LANDFILL", r["plan"]["summary"]["units_by_method"])   # มีทางที่ดีกว่าฝังกลบทุก lot


class TripCost(unittest.TestCase):
    """partner เรียกรถเฉพาะ (on-call): DEDICATED จ่ายค่าเที่ยวเต็มต่อการเรียก + ขั้นต่ำต่อรอบ, BIN คิดค่าเที่ยวเฉลี่ยต่อ kg
    ของเกินความจุ = รอบขนเพิ่มของเที่ยวเดียวกัน จ่ายค่าเที่ยวครั้งเดียว"""

    def test_trip_cost_follows_partner_mode(self):
        for inputs, products in ((REAL, PRODUCTS), (MockV4.V4["optimize_inputs"], MockV4.V4["products"])):
            r = run(copy.deepcopy(inputs), products=products, with_baselines=False)
            self.assertEqual(r["violations"], [])
            ctx = build_context(Inputs.from_json(inputs, products), at("09:00"))
            partners = {t["partner_id"] for t in r["plan"]["trips"]}
            for t in r["plan"]["trips"]:
                pc = ctx.partners[t["partner_id"]]
                self.assertEqual(t["mode"], pc.mode)
                if pc.mode == "DEDICATED":
                    self.assertAlmostEqual(t["trip_cost_thb"], round(partner_trip_cost(pc.partner), 2))
                    self.assertGreaterEqual(t["kg"], pc.min_kg - 1e-2, t["trip_id"])
                elif t["full_call"]:                         # เที่ยวเต็ม: ไม่เกินค่าเรียกรถ 1 ครั้ง (+ ของที่ยังขายได้ต่อ kg)
                    self.assertLessEqual(t["trip_cost_thb"], pc.fee_per_kg * t["kg"] + 0.05)
                else:
                    self.assertAlmostEqual(t["trip_cost_thb"], pc.fee_per_kg * t["kg"], delta=0.05)
            for d in r["payload"]["decisions"]:              # decision partner ทุกตัวอยู่บนเที่ยวที่คิดเงินแล้ว
                if d.get("target_partner_id"):
                    self.assertIn(d["target_partner_id"], partners)

    def test_over_capacity_pays_one_trip_and_extra_rounds_are_free(self):
        cfg = OptimizerConfig()
        data = copy.deepcopy(REAL)
        data.pop("waste_history")                             # ไม่มีประวัติของทิ้ง -> ทุก partner DEDICATED
        for partner in data["donation_partners"]:
            if partner["partner_id"] == "P-LDF-01":
                partner["max_capacity_kg_per_pickup"] = 2.0          # ต่อรอบขนรับได้ 2 kg
        r = run(data, with_baselines=False, cfg=cfg)
        self.assertEqual(r["violations"], [])
        self.assertEqual(r["plan"]["summary"]["unresolved_units"], 0)    # ไม่ตัดของทิ้งเพราะความจุ
        trip = next(t for t in r["plan"]["trips"] if t["trip_id"] == "P-LDF-01@2026-10-16")
        self.assertEqual(trip["mode"], "DEDICATED")
        self.assertGreater(trip["kg"], 2.0)
        self.assertEqual(trip["rounds"], math.ceil(trip["kg"] / 2.0 - 1e-9))
        self.assertEqual(trip["extra_rounds_free"], trip["rounds"] - 1)
        self.assertAlmostEqual(trip["trip_cost_thb"], 650 + 78.625, places=2)  # จ่ายเที่ยวเดียว
        normal = copy.deepcopy(REAL)
        normal.pop("waste_history")
        normal = next(t for t in run(normal, with_baselines=False, cfg=cfg)["plan"]["trips"] if t["trip_id"] == trip["trip_id"])
        self.assertEqual(normal["rounds"], 1)


class PartnerBins(unittest.TestCase):
    """partner on-call: สะสมของในถังแล้วเรียกรถเมื่อถึง "ปริมาณที่คุ้มที่สุดภายในเพดานเวลา" ค่าเที่ยวเฉลี่ยต่อ kg
    fixture: donation_partners + waste_history ตามข้อมูล Supabase ปัจจุบัน (ของทิ้ง 28 วันก่อน 16 ต.ค.)"""

    def setUp(self):
        self.ctx = build_context(Inputs.from_json(REAL, PRODUCTS), at("09:00"))

    def test_fewest_calls_per_week_within_hold_limit(self):
        self.assertEqual(calls_per_week({1, 2, 3, 4, 5, 6}, 2), 4)        # จ.พ.ศ.ส. ห่างไม่เกิน 2 วัน (ไม่มีรอบวันอาทิตย์)
        self.assertEqual(calls_per_week({1, 2, 3, 4, 5, 6, 7}, 2), 4)     # 7 วัน / ห่างได้ 2 วัน -> 4 ครั้ง
        self.assertEqual(calls_per_week({2, 3, 4, 6}, 2), 3)              # ตารางเองห่างสุด 3 วัน (ส.->อ.) ใช้ 3 แทน 2
        self.assertEqual(calls_per_week({1, 2, 4, 6}, 2), 4)              # ทุกวันรับจำเป็นหมด
        self.assertEqual(calls_per_week({1, 3, 5, 6, 7}, 3), 3)
        self.assertEqual(calls_per_week({1, 3, 5, 6, 7}, 4), 2)
        self.assertEqual(max_pickup_gap([2, 3, 4, 6]), 3)

    def test_economic_call_kg_and_fee_per_kg(self):
        # ปริมาณที่คุ้ม = min(ความจุ, ของทิ้งต่อวันของหมวดที่รับ x 7 / ครั้งที่เรียกต่อสัปดาห์) ค่าเที่ยวต่อ kg = ค่าเที่ยว / ปริมาณนั้น
        kg_day = REAL["waste_history"]["kg_per_day"]
        calls = {"P-LDF-01": 4, "P-ANI-01": 3, "P-CMP-01": 4, "P-ADG-01": 4}
        for p in REAL["donation_partners"]:
            pc = self.ctx.partners[p["partner_id"]]
            daily = sum(kg_day.get(c, 0.0) for c in p["accepted_categories"])
            self.assertAlmostEqual(pc.daily_kg, daily)
            if p["partner_id"] not in calls:
                continue
            economic = min(p["max_capacity_kg_per_pickup"], daily * 7 / calls[p["partner_id"]])
            self.assertEqual((pc.mode, pc.calls_per_week), ("BIN", calls[p["partner_id"]]), p["partner_id"])
            self.assertAlmostEqual(pc.expected_kg, economic)
            self.assertAlmostEqual(pc.fee_per_kg, partner_trip_cost(pc.partner) / economic)
            self.assertAlmostEqual(pc.cost_per_kg, pc.fee_per_kg + pc.handling - pc.partner.buyback)
        ldf = self.ctx.partners["P-LDF-01"]                  # เดิมเรียกทุกรอบรับ (min_kg 1 kg) ~177 บาท/kg
        self.assertAlmostEqual(ldf.expected_kg, 3.5443 * 1.75, places=2)
        self.assertLess(ldf.cost_per_kg, 120)
        # บริจาค: 4 ครั้ง/สัปดาห์ สะสมได้ 1.36 x 1.75 = 2.38 kg < ขั้นต่ำ 4 kg -> เรียกรถเฉพาะ
        self.assertEqual(self.ctx.partners["P-DON-01"].mode, "DEDICATED")
        self.assertTrue(any(w.startswith("W2_PARTNER_DEDICATED P-DON-01") for w in self.ctx.warnings))
        self.assertTrue(any(w.startswith("W3_PICKUP_GAP_OVER_HOLD P-ANI-01") for w in self.ctx.warnings))

    def test_longer_hold_turns_donation_into_bin(self):
        def mode(hold):
            return build_context(Inputs.from_json(REAL, PRODUCTS), at("09:00"),
                                 OptimizerConfig(max_hold_days=hold)).partners["P-DON-01"].mode
        self.assertEqual(mode(3.0), "DEDICATED")             # 3 ครั้ง/สัปดาห์ -> 3.18 kg < 4 kg
        self.assertEqual(mode(4.0), "BIN")                   # 2 ครั้ง/สัปดาห์ -> 4.77 kg

    def test_bin_waits_for_economic_size_within_hold_limit(self):
        ani = self.ctx.partners["P-ANI-01"]                 # ถังว่าง: รอ 6.61 kg / 2.83 kg ต่อวัน ≈ 2.33 วัน
        self.assertAlmostEqual(ani.wait_now_days, ani.expected_kg / ani.daily_kg)
        self.assertEqual(ani.pickup.isoformat(), "2026-10-17T16:00:00+07:00")    # รอบสุดท้ายก่อนเพดาน 3 วัน
        bins = {b["partner_id"]: b for b in run(with_baselines=False)["plan"]["partner_bins"]}
        ldf = bins["P-LDF-01"]                              # ถัง 3.84 kg < 6.2 kg: ยังไม่เรียก รอถึงเสาร์
        self.assertFalse(ldf["call_now"])
        self.assertEqual((ldf["call_reason"], ldf["expected_call_at"]), ("ECONOMIC_SIZE", "2026-10-17T20:00:00+07:00"))
        self.assertEqual(ldf["must_call_by"], "2026-10-18T10:00:00+07:00")
        self.assertLessEqual(ldf["expected_call_at"], ldf["must_call_by"])

    def test_full_bin_calls_the_truck_now(self):
        data = copy.deepcopy(REAL)
        data["partner_bins"] = [{"partner_id": "P-ANI-01", "open_kg": 7.0, "decisions": 2}]   # เกินปริมาณที่คุ้มแล้ว
        ani = build_context(Inputs.from_json(data, PRODUCTS), at("09:00")).partners["P-ANI-01"]
        self.assertEqual(ani.wait_now_days, 0.0)
        self.assertEqual(ani.pickup.isoformat(), "2026-10-17T16:00:00+07:00")     # รอบรับแรก (เสาร์) ไม่ต้องรอ
        r = run(data, with_baselines=False)
        self.assertEqual(r["violations"], [])
        b = next(b for b in r["plan"]["partner_bins"] if b["partner_id"] == "P-ANI-01")
        self.assertEqual((b["call_now"], b["call_reason"], b["bin_before_kg"]), (True, "ECONOMIC_SIZE", 7.0))

    def test_hold_limit_forces_the_call_before_economic_size(self):
        def ldf_bin(oldest_at):
            data = copy.deepcopy(REAL)
            data["partner_bins"] = [{"partner_id": "P-LDF-01", "open_kg": 0.5, "decisions": 1, "oldest_at": oldest_at}]
            r = run(data, with_baselines=False)
            self.assertEqual(r["violations"], [])
            return next(b for b in r["plan"]["partner_bins"] if b["partner_id"] == "P-LDF-01")
        # ของในถังรอตั้งแต่ 15 ต.ค. 09:00 -> ต้องเรียกก่อน 17 ต.ค. 09:00 ทั้งที่ถังยังไม่ถึง 6.2 kg
        b = ldf_bin("2026-10-15T02:00:00+00:00")
        self.assertEqual((b["call_now"], b["call_reason"], b["expected_call_at"]),
                         (True, "HOLD_LIMIT", "2026-10-16T20:00:00+07:00"))
        b = ldf_bin("2026-10-14T09:00:00+07:00")            # เกินเพดานแล้ว
        self.assertEqual((b["call_now"], b["call_reason"]), (True, "OVERDUE"))

    def test_no_waste_history_means_dedicated_calls(self):
        data = copy.deepcopy(REAL)
        data.pop("waste_history")
        ctx = build_context(Inputs.from_json(data, PRODUCTS), at("09:00"))
        self.assertEqual({pc.mode for pc in ctx.partners.values()}, {"DEDICATED"})
        r = run(data, with_baselines=False)
        self.assertEqual(r["violations"], [])
        for t in r["plan"]["trips"]:
            self.assertGreaterEqual(t["kg"], t["min_kg"] - 1e-2)
            self.assertAlmostEqual(t["trip_cost_thb"], round(partner_trip_cost(ctx.partners[t["partner_id"]].partner), 2))

    def test_route_total_override(self):
        # รถรอบประจำที่รับหลายร้าน: ใส่ kg ต่อเที่ยวรวมทั้งรอบแทนค่าที่คำนวณจากร้านเดียว
        cfg = OptimizerConfig(expected_kg_per_trip_override={"P-CMP-01": 400.0})
        cmp_ = build_context(Inputs.from_json(REAL, PRODUCTS), at("09:00"), cfg).partners["P-CMP-01"]
        self.assertEqual(cmp_.expected_kg, 400.0)
        self.assertAlmostEqual(cmp_.fee_per_kg, (1600 + 53.465) / 400.0)

    def test_sellable_goods_never_ride_a_full_call_for_free(self):
        # ของที่ยังขายได้แต่ดึงออกตอนนี้จ่ายค่าเฉลี่ยต่อ kg เสมอ แม้เที่ยวนั้นเต็มแล้ว -> ไม่เทของบนชั้นลงเที่ยวที่เปิดอยู่
        # ส่วนลดเที่ยวเต็มได้เฉพาะของที่ขายไม่ได้แล้ว (หมดอายุ / ของเหลือหลังหมดเวลาขาย)
        r = run(with_baselines=False)
        ldf = self.ctx.partners["P-LDF-01"]
        for lo in r["plan"]["lots"]:
            sellable = bool(self.ctx.lots[lo["lot_id"]].tiers)
            for p in lo["portions"]:
                d = p["details"]
                if d.get("partner_id") == "P-LDF-01" and d["timing"] == "NOW" and sellable:
                    self.assertAlmostEqual(d["trip_allocated_thb"] / d["kg"], ldf.fee_per_kg, delta=ldf.fee_per_kg * 1e-3)
        bread = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000011")
        self.assertIn("SELL_REGULAR", {p["method"] for p in bread["portions"]})
        self.assertNotIn("NOW", {p["details"].get("timing") for p in bread["portions"]})

    def test_full_call_rows_do_not_break_the_solver(self):
        # เคยพัง: เพดานเที่ยวเต็มเขียน big-M เป็นบาท x kg (สัมประสิทธิ์ 0.05..136,000) -> HiGHS "Solve error"
        # ตอนคำนวณ baseline ของ Mock V4 13:00 ที่ถัง landfill มีของค้าง (ตอนนี้เขียนเป็นหน่วย kg)
        data = copy.deepcopy(MockV4.V4["optimize_inputs"])
        data["partner_bins"] = [{"partner_id": "P-LDF-01", "open_kg": 10.0, "decisions": 3,
                                 "oldest_at": "2026-10-15T08:00:00+07:00"}]
        r = run(data, products=MockV4.V4["products"], hhmm="13:00")
        self.assertEqual(r["violations"], [])
        self.assertTrue(r["plan"]["baselines"])

    def test_big_unsellable_load_pays_one_call_not_per_kg(self):
        # ข้อ 4: ของก้อนใหญ่ที่ขายไม่ได้แล้ว (หมดอายุ 205 kg) ต้องถูกคิดค่าเรียกรถ 1 ครั้ง ไม่ใช่ 205 x ค่าเฉลี่ยต่อ kg
        data = copy.deepcopy(MockV4.V4["optimize_inputs"])
        big = next(r for r in data["at_risk_lots"] if r["lot"]["lot_id"] == "LOT-000020")
        big["lot"]["expiration_date"], big["days_to_expiry"], big["shelf"] = "2026-10-15", -1, []
        r = run(data, products=MockV4.V4["products"], with_baselines=False, cfg=OptimizerConfig(allow_stale_scan=True))
        self.assertEqual(r["violations"], [])
        lot = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000020")
        ctx = build_context(Inputs.from_json(data, MockV4.V4["products"]), at("09:00"))
        for p in lot["portions"]:
            pc = ctx.partners[p["details"]["partner_id"]]
            if pc.mode == "BIN":
                self.assertLessEqual(p["details"]["trip_allocated_thb"], pc.trip_cost + 0.01)    # ≤ ค่าเรียกรถ 1 ครั้ง
                self.assertLess(p["details"]["trip_allocated_thb"], pc.fee_per_kg * p["details"]["kg"] / 10)
        trips = [t for t in r["plan"]["trips"] if t["full_call"]]
        self.assertTrue(trips)
        self.assertTrue(r["plan"]["summary"]["reconciliation_ok"])


class Rolling(unittest.TestCase):
    """แผนชั่วคราว: lot ขายราคาปกติที่หมดอายุวันอื่น ของเหลือไปถัง partner โหมด BIN และไม่มี decision อื่น -> คืน IDLE
    ค่ากำจัดต่อ kg เท่ากันทั้งแผนชั่วคราวและ decision จริง จึงไม่มีเที่ยวฟรีที่กลายเป็น decision (บั๊กเดิม)"""

    def test_tomorrow_lot_is_released_without_decision(self):
        # ขนมปังพุดดิ้งหมดอายุพรุ่งนี้: วางขายต่อ ของที่เหลือเป็นแผนชั่วคราว (ไม่เทลง landfill ทั้ง lot เพื่อเลี่ยงค่าเที่ยว)
        r = run(with_baselines=False)
        bread = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000011")
        self.assertEqual(next(p for p in bread["portions"] if p["method"] == "SELL_REGULAR")["details"]["shelf_units"], 55)
        self.assertTrue(all(p["details"].get("provisional") for p in bread["portions"] if p["method"] != "SELL_REGULAR"))
        self.assertIn("LOT-000011", r["lots_to_release"])
        self.assertFalse(any(d["assessment_id"].startswith("c1ccb78e") for d in r["payload"]["decisions"]))

    def test_tonight_leftover_gets_a_decision(self):
        # สลัดหมดอายุคืนนี้: ไม่มีรอบสแกนก่อนกำจัด -> decision รอบนี้ due_by = รอบรับหลังถัง landfill เต็ม (ช้าสุดที่คาด)
        r = run(with_baselines=False)
        salad = [d for d in r["payload"]["decisions"] if d["assessment_id"].startswith("eb742153")]
        self.assertTrue(any(d["action_type"] == "LANDFILL" and d["due_by"] == "2026-10-17T20:00:00+07:00" for d in salad))
        self.assertNotIn("LOT-000012", r["lots_to_release"])

    def test_milk_is_donated_while_still_eligible(self):
        # นมเหลืออายุ 8 วัน ขายไม่ทัน: บริจาคตอนนี้ (รถบริจาคเรียกเฉพาะ 550 บาท) ถูกกว่าปล่อยให้หมดอายุแล้วฝังกลบ
        data = forward(copy.deepcopy(REAL), "LOT-000002", shelf_rows(47.5, [(0, 10, 5, 15)], "2026-10-24"))
        r = run(data, with_baselines=False)
        self.assertEqual(r["violations"], [])
        milk = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000002")
        donated = sum(p["units"] for p in milk["portions"] if p["method"] == "DONATION")
        self.assertGreater(donated, milk["quantity"] / 2)
        self.assertTrue(any(d["action_type"] == "DONATE" and d["due_by"] == "2026-10-16T10:00:00+07:00"
                            for d in r["payload"]["decisions"]))

    def test_provisional_costs_the_same_per_kg_as_a_decision(self):
        r = run(with_baselines=False)
        ldf = build_context(Inputs.from_json(REAL, PRODUCTS), at("09:00")).partners["P-LDF-01"]
        bread = next(l for l in r["plan"]["lots"] if l["lot_id"] == "LOT-000011")
        prov = [p for p in bread["portions"] if p["details"].get("provisional")]
        self.assertTrue(prov)
        for p in prov:
            self.assertAlmostEqual(p["cost_thb"] / p["details"]["kg"], ldf.fee_per_kg + ldf.handling,
                                   delta=ldf.fee_per_kg * 1e-3)

    def test_lot_with_other_decisions_pays_its_trip_in_full(self):
        # บั๊กเดิม: lot ที่มี decision อื่น (ครัว / ลดราคา) ได้เที่ยววันถัดไปฟรีแล้วถูกแปลงเป็น decision จริง
        # ตอนนี้: lot แบบนั้นไม่มีแผนชั่วคราวเลย ของที่เหลืออยู่บนเที่ยวที่คิดเงินแล้ว (BIN ต่อ kg / DEDICATED เต็ม + ขั้นต่ำ)
        for hhmm in ("09:00", "13:00"):
            r = MockV4()._run(hhmm)
            released = set(r["lots_to_release"])
            trips = {t["trip_id"]: t for t in r["plan"]["trips"]}
            for lo in r["plan"]["lots"]:
                prov = [p for p in lo["portions"] if p["details"].get("provisional")]
                if prov:
                    self.assertIn(lo["lot_id"], released, hhmm)
                    self.assertTrue(all(p["method"] == "SELL_REGULAR" or p in prov for p in lo["portions"]))
                for p in lo["portions"]:
                    if p["details"].get("timing") and p["details"].get("partner_id") and p not in prov:
                        trip = trips[p["details"]["trip_id"]]
                        self.assertGreater(trip["trip_cost_thb"], 0, hhmm)
                        self.assertGreaterEqual(trip["kg"], trip["min_kg"] - 1e-2, hhmm)
        lot18 = next(l for l in MockV4()._run("09:00")["plan"]["lots"] if l["lot_id"] == "LOT-000018")
        self.assertIn("KITCHEN_INGREDIENT", {p["method"] for p in lot18["portions"]})
        self.assertFalse(any(p["details"].get("provisional") for p in lot18["portions"]))


class MarkdownWholeShelf(unittest.TestCase):
    """ลดราคา = ติดป้ายทุกชิ้นที่ solver ให้วางบนชั้น (ไม่ใช่เฉพาะยอดที่คาดว่าขายได้) ราคาตามระดับที่ forecaster พยากรณ์
    ของที่ขายไม่หมดอยู่ใน lot ราคาลด (IDLE) รอบถัดไปวางแผนกำจัดใหม่ รอบนี้ไม่มี decision กำจัดของ lot นั้น"""

    @classmethod
    def setUpClass(cls):
        cls.inputs = copy.deepcopy(MockV4.V4["optimize_inputs"])
        cls.r = run(copy.deepcopy(cls.inputs), products=MockV4.V4["products"], with_baselines=False)
        cls.ctx = build_context(Inputs.from_json(cls.inputs, MockV4.V4["products"]), at("09:00"))

    def _markdown_lots(self):
        return [(lo, p) for lo in self.r["plan"]["lots"] for p in lo["portions"] if p["method"] == "MARKDOWN"]

    def test_labels_every_shelf_unit_at_the_forecast_price(self):
        md = self._markdown_lots()
        self.assertTrue(md)
        by_assessment = {d["assessment_id"]: d for d in self.r["payload"]["decisions"] if d["action_type"] == "MARKDOWN"}
        for lo, p in md:
            det = p["details"]
            self.assertEqual(p["units"], det["shelf_units"])
            self.assertGreater(p["units"], det["expected_sold"])            # ติดป้ายมากกว่ายอดที่คาดว่าขายได้
            self.assertAlmostEqual(p["share_pct"], p["units"] / lo["quantity"] * 100, places=2)
            d = by_assessment[lo["assessment_id"]]
            self.assertEqual(d["action_quantity"], det["shelf_units"])
            self.assertEqual(d["new_recommended_price"], tier_price(lo["current_price"], d["discount_pct"]))
            shelf = next(r["shelf"] for r in self.inputs["at_risk_lots"] if r["lot"]["lot_id"] == lo["lot_id"])
            self.assertIn(d["discount_pct"], {s["discount_pct"] for s in shelf})   # ระดับที่ forecaster ส่งมาเท่านั้น
            self.assertEqual(d["alternatives"][0]["handled_by"], "NEXT_RUN")
            self.assertAlmostEqual(det["expected_leftover"], det["shelf_units"] - det["expected_sold"], places=2)

    def test_leftover_has_no_decision_this_run(self):
        md_lots = {lo["lot_id"] for lo, _ in self._markdown_lots()}
        self.assertFalse([a for a in self.r["allocations"]
                          if a["lot_id"] in md_lots and a["details"].get("timing") == "END_OF_LIFE"])
        for lo, _ in self._markdown_lots():
            self.assertFalse(any(p["details"].get("timing") == "END_OF_LIFE" for p in lo["portions"]))
            self.assertNotIn(lo["lot_id"], self.r["lots_to_release"])     # มี decision แล้ว (lot ราคาลดถูกคืน IDLE โดย server)

    def test_leftover_estimate_uses_bin_cost_per_kg(self):
        # ค่าประมาณกำจัดของเหลือ = ถังของ partner โหมด BIN ค่าเที่ยวเฉลี่ยต่อ kg
        # หรือส่วนแบ่งค่าเรียกรถ 1 ครั้ง ถ้าของเหลือวันนั้นรวมกันถึงปริมาณที่คุ้ม (full_call)
        routes = [r for _, p in self._markdown_lots() for r in p["details"]["leftover_plan"]["routes"]]
        self.assertTrue(routes)
        for route in routes:
            pc = self.ctx.partners[route["partner_id"]]
            self.assertEqual(route["mode"], "BIN")
            per_kg = route["trip_allocated_thb"] / route["kg"]
            if route["full_call"]:
                self.assertLessEqual(per_kg, pc.fee_per_kg + 1e-6)
            else:
                self.assertAlmostEqual(per_kg, pc.fee_per_kg, delta=pc.fee_per_kg * 1e-3)
        self.assertNotIn("next_run_trip_estimates", self.r["plan"])
        for t in self.r["plan"]["trips"]:                    # ของที่ยังไม่ออก decision ไม่ช่วยให้เที่ยวรอบนี้ถึงขั้นต่ำ
            self.assertGreaterEqual(t["kg"], t["min_kg"] - 1e-2)
        self.assertTrue(self.r["plan"]["summary"]["reconciliation_ok"])


class KitchenTiming(unittest.TestCase):
    def test_menu_sale_starts_when_first_batch_is_done(self):
        r = run(with_baselines=False)
        job = r["plan"]["kitchen_jobs"][0]
        self.assertEqual(job["start_at"], "2026-10-16T09:30:00+07:00")
        self.assertEqual(job["sale_start"], "2026-10-16T10:15:00+07:00")
        self.assertLessEqual(datetime.fromisoformat(job["due_by"]), at("17:00"))

    def test_job_that_cannot_finish_before_shift_end_is_dropped(self):
        r = run(hhmm="16:15", with_baselines=False)                  # เริ่ม 16:45 + 45 นาที > 17:00
        self.assertEqual(r["plan"]["kitchen_jobs"], [])


class MockV4(unittest.TestCase):
    """mock data v4 (27 ล็อต หลายล็อตต่อสินค้า) ผ่าน Risk Scanner แล้ว 13 ล็อตเข้า Optimizer"""
    V4 = json.loads((Path(__file__).parent / "fixtures" / "mock_v4_2026-10-16.json").read_text(encoding="utf-8"))

    def _run(self, hhmm):
        return run_optimizer(copy.deepcopy(self.V4["optimize_inputs"]), products_catalog=self.V4["products"],
                             now=at(hhmm), with_baselines=False)

    def test_every_hour_is_valid(self):
        # เคยพังที่ 13:00: solver ปัด ceil ของวัตถุดิบ 8.0 หน่วยเป็น 9 ภายใน tolerance (H6_FEFO_MISMATCH)
        for hhmm in ("07:00", "09:00", "10:00", "12:00", "13:00", "15:00", "17:00", "19:00", "21:30"):
            r = self._run(hhmm)                                   # strict=True: violation -> raise
            self.assertTrue(r["plan"]["summary"]["reconciliation_ok"], hhmm)

    def test_covers_several_action_types(self):
        # ANIMAL_FEED / ANAEROBIC_DIGESTION เคยมาจากเที่ยววันถัดไปที่คิดค่าเที่ยว 0 บาท (บั๊ก) ตอนนี้ทุกเที่ยวจ่ายเต็ม
        # เที่ยว landfill วันนี้ที่เปิดอยู่แล้วจึงถูกกว่า
        actions = {d["action_type"] for d in self._run("09:00")["payload"]["decisions"]}
        self.assertLessEqual({"MARKDOWN", "KITCHEN_REPURPOSE", "LANDFILL"}, actions)

    def test_lot_without_own_decision_is_released(self):
        # lot ที่ไม่มี decision ของตัวเอง (ขายปกติ / วัตถุดิบรองของครัว / แผนชั่วคราว) ต้องคืน IDLE ไม่งั้นค้าง PROCESSING
        r = self._run("09:00")
        decided = {d["assessment_id"] for d in r["payload"]["decisions"]}
        for lo in r["plan"]["lots"]:
            if lo["assessment_id"] not in decided:
                self.assertIn(lo["lot_id"], r["lots_to_release"])


if __name__ == "__main__":
    unittest.main()