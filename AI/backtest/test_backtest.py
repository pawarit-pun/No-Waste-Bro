"""เทสต์ของ backtest (รันจากโฟลเดอร์ AI/backtest): python -m unittest test_backtest -v

- โลกจำลอง: กติการถ bins ให้ผลนโยบาย 1-2 ตรงกับ backtest 22 ต.ค. ทุกบาท, dedicated เรียกรถทุกวันที่มีรอบรับและมีของ
- วงจร lot แบบ main: แผนชั่วคราวไม่มี task, decision ของ partner เอาของออกวันนี้, ลดราคาแยก lot ใหม่ (IDLE),
  task ถูกปฏิเสธไม่ทำอะไร, lot ที่ไม่อยู่ในแผน = ค้าง PROCESSING, ของหมดอายุไม่ถูกทิ้งเองอัตโนมัติ
- รันจริง 3 วัน (Forecaster + Risk Scanner + Optimizer ของ main) ของไม่หาย และ task เอาของออก due วันนี้ทั้งหมด
"""
import json
import unittest
from collections import defaultdict
from datetime import date

from world import FIXED_RULES, HERE, LANDFILL, Bin, Ledger, Lot, World, calls_per_week, expire, max_pickup_gap, \
    run_pickups, run_rule_policy
from policy_lifecycle import LifecyclePolicy

START = date(2026, 8, 17)
D = date(2026, 8, 18)                                                  # อังคาร: รถฝังกลบมีรอบรับ (จ-ส)


def lot(uid="L1", qty=10, expiry=date(2026, 8, 20), price=50.0):
    return Lot(uid, "BAK-003", date(2026, 8, 15), expiry, qty, 20.0, price, 50.0)


def portion(method, units, **details):
    return {"method": method, "units": units, "details": details}


def result(lots_plan, decisions, allocations, release=()):
    return {"plan": {"lots": lots_plan, "kitchen_jobs": []}, "payload": {"decisions": decisions},
            "allocations": allocations, "lots_to_release": list(release), "violations": [], "payload_errors": []}


class WorldRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = json.loads((HERE / "data" / "reference_optimizer-update.json").read_text(encoding="utf-8"))
        cls.bins = World(START, 60, "bins")

    def test_bins_reproduces_reference_policy1(self):
        led = run_rule_policy(self.bins, "p1", None)
        self.assertAlmostEqual(round(led.net, 2), self.ref["policy1"]["net_profit"], places=2)
        self.assertEqual(dict(led.calls), self.ref["policy1"]["calls"])

    def test_bins_reproduces_reference_policy2(self):
        for k, rule in FIXED_RULES.items():
            led = run_rule_policy(self.bins, k, rule)
            self.assertAlmostEqual(round(led.net, 2), self.ref["policy2_variants"][k]["net_profit"], places=2, msg=k)

    def test_pickup_schedule_helpers(self):
        self.assertEqual(max_pickup_gap([1, 3, 5]), 3)                 # ศ -> จ = 3 วัน
        self.assertEqual(calls_per_week([1, 2, 3, 4, 5, 6, 7], 2.0), 4)
        self.assertEqual(calls_per_week([2, 3, 4, 6], 2.0), 3)

    def test_dedicated_calls_every_pickup_day_with_items(self):
        w = World(START, 7, "dedicated")
        rules = w.rules(D)
        self.assertTrue(all(r.mode == "DEDICATED" for r in rules.values()))
        bins, led = defaultdict(Bin), Ledger("t")
        bins[LANDFILL].items.append((0.5, D))
        run_pickups(bins, rules, D, led)
        self.assertEqual(led.calls[LANDFILL], 1)
        self.assertAlmostEqual(led.money["trip_fee"], rules[LANDFILL].trip_cost)
        bins[LANDFILL].items.append((0.5, D))
        run_pickups(bins, rules, date(2026, 8, 23), led)               # อาทิตย์: รถฝังกลบไม่มีรอบรับ
        self.assertEqual(led.calls[LANDFILL], 1)

    def test_expired_without_decision_stays_in_store(self):
        w = World(START, 7, "dedicated")
        bins, led = defaultdict(Bin), Ledger("t")
        l = lot(expiry=D)
        expire(w, [l], bins, D, led, auto_landfill=False)
        self.assertEqual(l.qty, 10)
        expire(w, [l], bins, D, led, auto_landfill=True)
        self.assertEqual((l.qty, led.units["LANDFILL"]), (0, 10))


class Lifecycle(unittest.TestCase):
    """apply() ด้วยผล Optimizer ที่เขียนเอง (ไม่ต้องรัน Forecaster)"""

    def setUp(self):
        self.world = World(START, 7, "dedicated")
        self.bins, self.led = defaultdict(Bin), Ledger("t")

    def apply(self, res, lots, approve_rate=1.0, forwarded=None):
        pol = LifecyclePolicy(self.world, scanner=None, approve_rate=approve_rate)
        for l in lots:
            l.status = "PROCESSING"
        pol.apply(res, lots, self.bins, D, self.led, {l.uid: l for l in lots},
                  forwarded or {l.uid for l in lots})
        return pol

    def test_provisional_disposal_has_no_task_and_lot_is_released(self):
        l = lot()
        p = portion("LANDFILL", 4, timing="END_OF_LIFE", provisional=True, partner_id=LANDFILL)
        res = result([{"lot_id": "L1", "portions": [portion("SELL_REGULAR", 6), p]}], [],
                     [{"lot_id": "L1", **portion("SELL_REGULAR", 6), "decision_index": None},
                      {"lot_id": "L1", **p, "decision_index": None}], release=["L1"])
        pol = self.apply(res, [l])
        self.assertEqual((l.qty, l.status, l.eol_partner, l.deferrals), (10, "IDLE", None, 1))
        self.assertEqual(pol.stats["deferral_days"], 1)

    def test_partner_decision_removes_today_then_lot_returns_idle(self):
        l = lot()
        p = portion("LANDFILL", 3, timing="NOW", provisional=False, partner_id=LANDFILL)
        res = result([{"lot_id": "L1", "portions": [portion("SELL_REGULAR", 7), p]}],
                     [{"action_type": "LANDFILL", "action_quantity": 3, "due_by": f"{D}T20:00:00+07:00"}],
                     [{"lot_id": "L1", **portion("SELL_REGULAR", 7), "decision_index": None},
                      {"lot_id": "L1", **p, "decision_index": 0}])
        pol = self.apply(res, [l])
        self.assertEqual((l.qty, l.status, self.bins[LANDFILL].kg > 0), (7, "CHECKED", True))
        self.assertEqual((pol.stats["partner_tasks"], pol.stats["partner_tasks_due_today"]), (1, 1))
        pol.end_of_day([l], D)
        self.assertEqual(l.status, "IDLE")                             # release_lot_if_idle หลัง task จบ

    def test_markdown_splits_new_idle_lot(self):
        l = lot()
        p = portion("MARKDOWN", 4, discount_pct=20, unit_price=40.0)
        lots = [l]
        res = result([{"lot_id": "L1", "portions": [p, portion("SELL_REGULAR", 6)]}],
                     [{"action_type": "MARKDOWN", "action_quantity": 4}],
                     [{"lot_id": "L1", **p, "decision_index": 0},
                      {"lot_id": "L1", **portion("SELL_REGULAR", 6), "decision_index": None}])
        self.apply(res, lots)
        new = lots[-1]
        self.assertEqual((l.qty, new.qty, new.price, new.status), (6, 4, 40.0, "IDLE"))

    def test_rejected_task_does_nothing(self):
        l = lot()
        p = portion("LANDFILL", 3, timing="NOW", provisional=False, partner_id=LANDFILL)
        res = result([{"lot_id": "L1", "portions": [p]}], [{"action_type": "LANDFILL", "action_quantity": 3}],
                     [{"lot_id": "L1", **p, "decision_index": 0}])
        pol = self.apply(res, [l], approve_rate=0.0)
        self.assertEqual((l.qty, pol.stats["tasks_rejected"]), (10, 1))
        pol.end_of_day([l], D)
        self.assertEqual(l.status, "IDLE")

    def test_end_of_life_decision_sets_tonight_partner(self):
        l = lot(expiry=D)
        p = portion("LANDFILL", 5, timing="END_OF_LIFE", provisional=False, partner_id=LANDFILL)
        res = result([{"lot_id": "L1", "portions": [portion("SELL_REGULAR", 5), p]}],
                     [{"action_type": "LANDFILL", "action_quantity": 5, "due_by": f"{D}T20:00:00+07:00"}],
                     [{"lot_id": "L1", **portion("SELL_REGULAR", 5), "decision_index": None},
                      {"lot_id": "L1", **p, "decision_index": 0}])
        self.apply(res, [l])
        self.assertEqual(l.eol_partner, LANDFILL)
        expire(self.world, [l], self.bins, D, self.led, auto_landfill=False)
        self.assertEqual(l.qty, 0)

    def test_forwarded_lot_missing_from_plan_is_stuck(self):
        a, b = lot("A"), lot("B")
        res = result([{"lot_id": "A", "portions": [portion("SELL_REGULAR", 10)]}], [],
                     [{"lot_id": "A", **portion("SELL_REGULAR", 10), "decision_index": None}], release=["A"])
        pol = self.apply(res, [a, b])
        self.assertEqual((a.status, b.status, pol.stats["stuck_processing"]), ("IDLE", "PROCESSING", 1))

    def test_zero_unit_portion_blocks_release_on_main(self):
        # เคสจริง RTE-001-01272 (5 ก.ย.): ของเหลือไปปุ๋ยหมักวันจันทร์ (แผนชั่วคราว) + ฝังกลบคืนนี้ 0 หน่วย (ปัดเศษ)
        # 0 หน่วยไม่มี decision แต่ไม่ใช่แผนชั่วคราว -> lots_to_release ของ main ไม่คืน lot -> ค้าง PROCESSING
        from ai_engine.optimizer.pipeline import lots_to_release
        l = lot(expiry=D)
        portions = [portion("SELL_REGULAR", 7),
                    portion("COMPOSTING", 3, timing="END_OF_LIFE", provisional=True, partner_id="P-CMP-01"),
                    portion("LANDFILL", 0, timing="END_OF_LIFE", provisional=False, partner_id=LANDFILL)]
        plan_lot = {"lot_id": "L1", "days_to_expiry": 0, "portions": portions}
        release = lots_to_release({"lots": [plan_lot]})
        self.assertEqual(release, [])
        res = result([plan_lot], [], [{"lot_id": "L1", **p, "decision_index": None} for p in portions], release)
        pol = self.apply(res, [l])
        self.assertEqual((l.status, pol.stats["stuck_processing"], pol.stats["stuck_zero_unit_portion"]),
                         ("PROCESSING", 1, 1))
        pol.end_of_day([l], D)
        self.assertEqual((l.status, pol.stats["expired_overnight_provisional"]), ("PROCESSING", 1))

    def test_expired_overnight_without_plan_is_not_forwarded(self):
        pol = LifecyclePolicy(self.world, scanner=None)
        pol.end_of_day([lot(expiry=D)], D)
        self.assertEqual(pol.stats["expired_overnight_not_forwarded"], 1)

    def test_expired_nights_are_counted(self):
        l = lot(expiry=D)
        pol = LifecyclePolicy(self.world, scanner=None)
        pol.end_of_day([l], D)                                         # คืนแรก: รอรอบสแกนเช้า
        pol.end_of_day([l], date(2026, 8, 19))                         # สแกนแล้วยังค้าง
        self.assertEqual((pol.stats["expired_unit_days"], pol.stats["expired_unit_days_over_1_night"]), (20, 10))


class OneShot(unittest.TestCase):
    """กดรันครั้งเดียว: 27 lot ของ demo วันที่ 2026-10-16"""

    @classmethod
    def setUpClass(cls):
        from run_oneshot import DEMO_DATE, demo_lots, proxy_demand
        cls.d = DEMO_DATE
        cls.world = World(cls.d, 1, "dedicated")
        cls.base = demo_lots(cls.world)
        cls.proxy = proxy_demand(cls.world, cls.d)
        cls.world.demand.update(cls.proxy)

    def test_demo_lots_and_proxy_demand(self):
        self.assertEqual(len(self.base), 27)
        self.assertTrue(all(k[1] == self.d for k in self.proxy))
        self.assertEqual({k[0] for k in self.proxy}, set(self.world.products))

    def test_rule_policy_discards_every_expired_lot(self):
        from run_oneshot import run_rule_day
        p1 = run_rule_day(self.world, self.base, self.d, "p1")          # day_summary ตรวจของเช้า = ออก + คงเหลือ
        self.assertEqual(p1["expired_left_units"], 0)                   # รวม LOT-000013 ที่หมดอายุตั้งแต่ 15 ต.ค.
        self.assertGreater(p1["units"].get("LANDFILL", 0), 0)

    def test_main_one_shot_tasks_are_for_today(self):
        from policy_lifecycle import ScanModel
        from run_oneshot import run_main_day
        p3, pol = run_main_day(self.world, self.base, self.d, ScanModel(until=None), 1.0)
        self.assertEqual(p3["notes"]["lots_scanned"], 27)
        self.assertEqual(p3["notes"]["partner_tasks_due_today"], p3["notes"]["partner_tasks"])
        jobs = pol.last_result["plan"]["kitchen_jobs"]
        self.assertTrue(all(j["date"] == self.d.isoformat() for j in jobs))   # ครัวใช้ชั่วโมงวันนี้เท่านั้น
        # ของหมดอายุค้างร้านถูกตัดต้นทุนออกจากกำไรวันนี้
        self.assertAlmostEqual(p3["net_profit"], p3["net_profit_cash"] - p3["expired_left_cost"], places=2)


class SmokeRun(unittest.TestCase):
    """รันจริง 3 วันด้วยโค้ด AI ของ main (เทรน Forecaster ก่อน ~10-20 วินาที)"""

    def test_three_days_dedicated(self):
        from policy_lifecycle import ScanModel
        world = World(START, 3, "dedicated")
        led = LifecyclePolicy(world, ScanModel()).run()                # run() ตรวจของเข้า = ออก + คงเหลือ
        n = led.notes
        self.assertGreater(n["lots_scanned"], 0)
        self.assertEqual(n["optimizer_errors"], 0)
        self.assertEqual(n["partner_tasks_due_today"], n["partner_tasks"])


if __name__ == "__main__":
    unittest.main()
