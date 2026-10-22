"""นโยบาย 3 แบบ main: Risk Scanner + Forecaster + Optimizer รันทุกเช้า และจำลองวงจรสถานะ lot ตามที่ระบบจริงทำ

ลำดับต่อวัน d (ตรงกับ AI/pipeline/worker.py + server/scripts/lot_lifecycle.sql):
  1 SCAN      lot IDLE ที่ยังมีของ (รวม lot หมดอายุแล้ว: GET /ai/scan-inputs ไม่กรองวันหมดอายุ)
              LOW / MEDIUM -> IDLE, HIGH / CRITICAL -> PROCESSING
  2 OPTIMIZE  run_optimizer ของ main ค่าเริ่มต้น (deferred_trip_cost_share = 0) decision เอาของออกเฉพาะเที่ยวที่รับวันนี้
              เที่ยววันอื่น = แผนชั่วคราว (provisional) ไม่มี decision
  3 TASKS     decision 1 ตัว = task 1 ตัว (ข้ามขั้น LLM) ผู้จัดการอนุมัติตาม approve_rate
  4 ลงมือ      MARKDOWN ติดป้าย action_quantity ชิ้น -> lot ใหม่ราคาลด (IDLE: lot_lifecycle ข้อ 3)
              ครัว ตัดของตามงาน, partner NOW ดึงออกตอนนี้, partner END_OF_LIFE ของที่เหลือคืนนี้ไป partner นั้น
              แผนชั่วคราว ไม่ทำอะไร
  5 สถานะ      lots_to_release -> IDLE ทันที, lot ที่มี decision -> CHECKED แล้วคืน IDLE ตอน task จบ (release_lot_if_idle)
              lot ที่ส่งต่อแต่ไม่อยู่ในแผนและไม่ถูกคืน = ค้าง PROCESSING (นับไว้ ไม่แก้ให้ เพราะระบบจริงก็ค้าง)
  6 ขาย / รถ / หมดอายุ  ไม่มี decision = ของหมดอายุค้างในร้าน (ไม่ทิ้งเองอัตโนมัติ) รอรอบสแกนพรุ่งนี้

ข้อจำกัด: ทุก task เสร็จภายในวันที่ออก (งานครัวของพรุ่งนี้ก็ทำวันนี้เหมือน backtest 22 ต.ค.), staff เอาของออกได้ตามจำนวนจริง
"""
from __future__ import annotations

import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

import pandas as pd

from world import AI_DIR, LANDFILL, MOCK, Bin, Ledger, Lot, World, check_conservation, end_of_day_pickups, \
    run_pickups, sell, to_bin

sys.path.insert(0, str(AI_DIR / "risk_forecaster"))
sys.path.insert(0, str(AI_DIR / "food_waste_optimizer"))

from common import config as rf_config                                            # noqa: E402
from common.sources import load_reference                                         # noqa: E402
from forecaster.model import Forecaster                                           # noqa: E402
from risk_scanner import handoff, risk                                            # noqa: E402
from ai_engine.optimizer import run_optimizer                                     # noqa: E402
from ai_engine.optimizer.config import BKK                                        # noqa: E402

TEST_START = date(2026, 8, 4)                       # ช่วง test ของ Forecaster (forecaster_v3_metrics.json)
PARTNER_ACTIONS = {"DONATE", "ANIMAL_FEED", "COMPOST", "ANAEROBIC_DIGESTION", "LANDFILL"}


class ScanModel:
    """Forecaster + Risk Scanner (สร้างครั้งเดียว ใช้ได้หลายรอบ)
    until = เทรนใหม่ด้วยข้อมูลก่อนวันนั้นเท่านั้น (ไม่เห็นยอดขายช่วงที่ทดสอบ) | None = โมเดลตัวจริงในเครื่อง (เหมือน run_scan.py)"""

    def __init__(self, until: date | None = TEST_START):
        self.fc = Forecaster.load()
        self.trained_until = until
        if until is None:
            self.model = self.fc.model
        else:
            df = pd.read_csv(MOCK / "training_dataset.csv")
            hist, products_df, rows = self.fc.build_training(df)
            self.model = self.fc.model_until(rows, pd.Timestamp(until))
            before = hist[hist.sale_date < pd.Timestamp(until)]
            self.fc.lifts = Forecaster._estimate_lifts(before, Forecaster.clearance_products(products_df))
        self.thresholds = rf_config.load_thresholds()
        ref_products, self.recipes = load_reference()
        self.products = {p["product_id"]: p for p in ref_products}
        self.prod_df = pd.DataFrame([{"product_id": p["product_id"], "category": p["category"],
                                      "shelf_life_days": p["shelf_life_days"]} for p in ref_products])
        self.pdy = pd.read_csv(MOCK / "product_daily.csv", dtype={"stockout_hour": "Int64"})
        self.ctx = pd.read_csv(MOCK / "daily_context.csv")

    def history(self, d: date) -> list:
        p = self.pdy
        keep = (p.sale_date >= (d - timedelta(days=rf_config.HISTORY_DAYS)).isoformat()) & (p.sale_date < d.isoformat())
        return json.loads(p[keep].sort_values(["product_id", "sale_date"]).to_json(orient="records", force_ascii=False))

    def scan(self, lots: list, d: date):
        scan_lots = [{"lot_id": l.uid, "product_id": l.product_id, "received_date": l.received.isoformat(),
                      "expiration_date": l.expiry.isoformat(), "initial_quantity": l.qty, "current_quantity": l.qty,
                      "unit_cost": l.cost, "current_selling_price": l.price, "ai_status": "IDLE"} for l in lots]
        targets = set()
        for l in lots:
            targets |= {(l.product_id, d + timedelta(days=i)) for i in range((l.expiry - d).days + 1)}
        for r in self.recipes:
            if r["is_active"]:
                targets |= {(r["output_product_id"], d + timedelta(days=i)) for i in range(int(r["shelf_life_days"]) + 1)}
        to = max([l.expiry for l in lots] + [d + timedelta(days=7)]).isoformat()
        ctx = json.loads(self.ctx[(self.ctx.context_date >= d.isoformat()) & (self.ctx.context_date <= to)]
                         .to_json(orient="records", force_ascii=False))
        mu = self.fc.predict_daily(self.history(d), ctx, self.prod_df, d, sorted(targets), model=self.model)
        demand = {(r.product_id, r.date.date()): float(r.mu) for r in mu.itertuples()}
        results = risk.assess(scan_lots, demand, self.fc.phi_for, d, self.thresholds, 0.0)
        recipe_rows = handoff.build(results, self.products, self.recipes, demand, self.fc.lifts, d, self.fc.phi_for)
        return results, recipe_rows


class LifecyclePolicy:
    def __init__(self, world: World, scanner: ScanModel, approve_rate: float = 1.0, seed: int = 7,
                 kitchen_days: tuple = (0, 1), with_baselines: bool = False):
        """kitchen_days = ชั่วโมงครัวที่ส่งให้ Optimizer (วันนี้ + พรุ่งนี้ เหมือน days_ahead=1) one-shot ใช้ (0,) = วันนี้เท่านั้น"""
        self.world, self.scanner = world, scanner
        self.approve_rate, self.rng = approve_rate, random.Random(seed)
        self.kitchen_days, self.with_baselines = kitchen_days, with_baselines
        self.last_result, self.last_scan = None, {}
        self.stats = Counter()
        self.deferred_lots, self.expired_lots, self.overdue_lots = set(), set(), set()
        self.eol_plan = {}                                             # (lot, วัน) -> แผนของที่เหลือคืนวันหมดอายุ

    def run(self) -> Ledger:
        w, led = self.world, Ledger("product_main")
        lots = [w.new_lot(r) for r in w.initial]
        bins = defaultdict(Bin)
        d, rules = w.start, None
        while d <= w.end:
            lots += [w.new_lot(r) for r in w.deliveries.get(d, [])]
            rules = w.rules(d)
            for l in lots:
                l.eol_partner = None
            self.day(lots, bins, d, led)
            sell(w, lots, d, led)
            end_of_day_pickups(bins, rules, d, led, w, lots, auto_landfill=False)
            self.end_of_day(lots, d)
            lots = [l for l in lots if l.qty > 0]
            led.daily.append(round(led.net, 2))
            d += timedelta(days=1)
        # ปิดรอบ: ของหมดอายุที่ยังค้างในร้าน (ไม่เคยได้ decision) ทิ้ง landfill ทั้งหมด
        for l in lots:
            if l.expiry <= w.end and l.qty > 0:
                self.stats["expired_flushed_units"] += l.qty
                self.stats["expired_flushed_cost"] += l.qty * l.cost
                to_bin(w, bins, LANDFILL, l, l.qty, w.end, led, "LANDFILL")
        run_pickups(bins, rules, d, led, flush=True)
        led.daily[-1] = round(led.net, 2)
        lots = [l for l in lots if l.qty > 0]
        check_conservation(w, led, lots)
        self.stats["stuck_processing_end"] = sum(l.status == "PROCESSING" for l in lots)
        self.stats["lots_deferred"] = len(self.deferred_lots)
        self.stats["lots_expired_in_store"] = len(self.expired_lots)
        self.stats["lots_expired_over_1_night"] = len(self.overdue_lots)
        self.stats["expired_flushed_cost"] = round(self.stats["expired_flushed_cost"], 2)
        led.notes.update(self.stats)
        led.notes["ending_units"] = sum(l.qty for l in lots)
        led.notes["ending_cost"] = round(sum(l.qty * l.cost for l in lots), 2)
        return led

    # ---------------------------------------------------------------- 1-3 SCAN -> OPTIMIZE
    def day(self, lots: list, bins: dict, d: date, led: Ledger) -> None:
        w = self.world
        idle = [l for l in lots if l.status == "IDLE" and l.qty > 0 and l.received <= d]
        if not idle:
            return
        results, recipe_rows = self.scanner.scan(idle, d)
        self.last_scan = {r["payload"]["lot_id"]: r["payload"] for r in results}
        by_uid = {l.uid: l for l in lots}
        run_id = f"sim-{d.isoformat()}"
        at_risk = []
        for r in results:
            p = r["payload"]
            l = by_uid[p["lot_id"]]
            l.scans += 1
            self.stats["lots_scanned"] += 1
            if p["risk_level"] not in rf_config.FORWARD_LEVELS:
                continue                                               # LOW / MEDIUM -> IDLE สแกนใหม่พรุ่งนี้
            l.status = "PROCESSING"
            self.stats["lots_forwarded"] += 1
            at_risk.append({**{k: v for k, v in p.items() if k != "shelf"}, "assessment_id": f"{run_id}-{l.uid}",
                            "run_id": run_id, "shelf": p.get("shelf") or [],
                            "lot": {"lot_id": l.uid, "product_id": l.product_id, "current_quantity": l.qty,
                                    "unit_cost": l.cost, "current_selling_price": l.price,
                                    "expiration_date": l.expiry.isoformat(), "location_aisle": None,
                                    "location_shelf": None, "ai_status": "PROCESSING"}})
        if not at_risk:
            return
        ingredient_ids = sorted({i["ingredient_product_id"] for r in w.recipes for i in r["ingredients"]})
        stock = [{"product_id": pid, "lots": [{"lot_id": l.uid, "current_quantity": l.qty,
                                               "expiration_date": l.expiry.isoformat()}
                                              for l in sorted(lots, key=lambda l: (l.expiry, l.uid))
                                              if l.product_id == pid and l.qty > 0 and l.expiry >= d and l.received <= d]}
                 for pid in ingredient_ids]
        kitchen = [{**k, "capacity_date": (d + timedelta(days=i)).isoformat()} for i in self.kitchen_days
                   for k in w.kitchen_rows]
        # GET /ai/optimize-inputs ของ main: ไม่มี waste_history / partner_bins
        inputs = {"reference_date": d.isoformat(), "run_id": run_id, "at_risk_lots": at_risk,
                  "recipe_demand": [{**r, "run_id": run_id} for r in recipe_rows], "products": w.opt_products,
                  "recipes": w.recipes, "kitchen_capacity": kitchen, "donation_partners": w.partners,
                  "ingredient_stock": stock}
        now = datetime.combine(d, time(8, 0), tzinfo=BKK)
        try:
            res = run_optimizer(inputs, products_catalog=w.catalog, now=now, strict=False,
                                with_baselines=self.with_baselines)
        except Exception as e:                                         # worker.release_stuck_lots: คืน IDLE ทั้งรอบ
            self.stats["optimizer_errors"] += 1
            print(f"  {d}: optimizer error {type(e).__name__}: {e}")
            for a in at_risk:
                by_uid[a["lot"]["lot_id"]].status = "IDLE"
            return
        self.stats["violation_days"] += bool(res["violations"] or res["payload_errors"])
        self.last_result = res
        self.apply(res, lots, bins, d, led, by_uid, {a["lot"]["lot_id"] for a in at_risk})

    # ---------------------------------------------------------------- 3-5 TASKS -> ลงมือ -> สถานะ
    def apply(self, res: dict, lots: list, bins: dict, d: date, led: Ledger, by_uid: dict, forwarded: set) -> None:
        w, plan, decisions = self.world, res["plan"], res["payload"]["decisions"]
        approved = [self.rng.random() < self.approve_rate for _ in decisions]
        for x, ok in zip(decisions, approved):
            self.stats[f"decision_{x['action_type']}"] += 1
            self.stats["tasks_approved" if ok else "tasks_rejected"] += 1
            if x["action_type"] in PARTNER_ACTIONS and x.get("due_by"):
                self.stats["partner_tasks"] += 1
                self.stats["partner_tasks_due_today"] += str(x["due_by"])[:10] == d.isoformat()

        def decision_of(a):
            i = a.get("decision_index")
            return a.get("covered_by_decision_index") if i is None else i

        done_jobs = set()
        for a in res["allocations"]:
            l, m, n, det = by_uid[a["lot_id"]], a["method"], a["units"], a["details"]
            if det.get("provisional"):
                continue                                               # แผนชั่วคราว: ไม่มี decision ไม่มี task
            i = decision_of(a)
            if i is None or not approved[i] or n <= 0:
                continue                                               # ขายราคาปกติ (ไม่มี task) / task ถูกปฏิเสธ
            if m == "MARKDOWN":                                        # ติดป้าย action_quantity ชิ้น -> lot ใหม่ (IDLE)
                take = min(n, l.qty)
                l.qty -= take
                lots.append(Lot(f"{l.uid}~md{d:%m%d}", l.product_id, l.received, l.expiry, take, l.cost,
                                float(det["unit_price"]), l.regular))
            elif m in ("KITCHEN", "KITCHEN_INGREDIENT"):
                take = min(n, l.qty)
                l.qty -= take
                led.money["cogs_kitchen"] += take * l.cost
                led.units["KITCHEN"] += take
                done_jobs.add(det["job_id"])
            elif det.get("partner_id") and det.get("timing") == "NOW":
                to_bin(w, bins, det["partner_id"], l, min(n, l.qty), d, led, m)
            elif det.get("partner_id") and det.get("timing") == "END_OF_LIFE":
                l.eol_partner = det["partner_id"]                      # staff เอาของที่เหลือจริงออกคืนนี้
            elif m == "UNRESOLVED" and det.get("timing") == "END_OF_LIFE":
                l.eol_partner = LANDFILL                               # DISCARD: ทิ้งเองในร้านหลังหมดเวลาขาย
            elif m == "UNRESOLVED":
                to_bin(w, bins, LANDFILL, l, min(n, l.qty), d, led, "LANDFILL")
        for j in plan["kitchen_jobs"]:                                 # มูลค่าเมนู (ค่าคาดหมาย) - ค่าไฟน้ำ - วัตถุดิบปกติ
            if j["job_id"] not in done_jobs:
                continue
            led.money["kitchen_value"] += (j["revenue_thb"] - j["utility_cost_thb"]
                                           - j["primary_from_regular_stock_thb"] + j["secondary_credit_thb"])
            for x in j["inputs"]:
                if x["role"] != "ANCHOR" and not x.get("at_risk") and x["lot_id"] in by_uid:
                    src = by_uid[x["lot_id"]]
                    take = min(src.qty, math.ceil(x["units"] - 1e-9))   # DB ตัดเป็นหน่วยเต็ม ต้นทุนอยู่ในมูลค่าเมนูแล้ว
                    src.qty -= take
                    led.notes["kitchen_regular_stock_units"] += take

        released = set(res["lots_to_release"])
        with_task = {a["lot_id"] for a in res["allocations"] if a.get("decision_index") is not None}
        planned = set()
        for lo in plan["lots"]:
            lid = lo["lot_id"]
            planned.add(lid)
            l = by_uid[lid]
            if any(p["details"].get("provisional") for p in lo["portions"]):
                l.deferrals += 1
                self.stats["deferral_days"] += 1
                self.deferred_lots.add(lid)
            if lo.get("days_to_expiry") == 0:
                eol = [p for p in lo["portions"] if p["details"].get("timing") == "END_OF_LIFE" and p["units"] > 0]
                self.eol_plan[(lid, d)] = ("provisional" if eol and all(p["details"].get("provisional") for p in eol)
                                           else "decision" if eol else "sell_out")
            if lid in released:
                l.status = "IDLE"
            elif lid in with_task:
                l.status = "CHECKED"
            else:
                self.stats["stuck_processing"] += 1                    # ระบบจริงค้าง PROCESSING (ไม่มีใครคืน)
                # บั๊กของ main: portion 0 หน่วย (ปัดเศษ) ที่ไม่ใช่แผนชั่วคราวไม่มี decision แต่ขวาง lots_to_release
                if any(p["units"] == 0 and not p["details"].get("provisional") and p["method"] not in
                       ("SELL_REGULAR", "KITCHEN_INGREDIENT") for p in lo["portions"]):
                    self.stats["stuck_zero_unit_portion"] += 1
        self.stats["stuck_processing"] += len(forwarded - planned)

    def end_of_day(self, lots: list, d: date) -> None:
        """task ทั้งหมดของวันนี้จบ (ทำ / ปฏิเสธ) -> release_lot_if_idle: lot ที่ยังมีของกลับเป็น IDLE ให้สแกนพรุ่งนี้
        ของหมดอายุที่ยังค้างในร้านข้ามคืน = หน่วย x วัน ที่อยู่ในร้านหลังหมดอายุ
        คืนแรก = รอรอบสแกนเช้าพรุ่งนี้ (ร้านปิดแล้ว) เกิน 1 คืน = รอบสแกนเช้าแล้วก็ยังไม่มีใครเอาออก (ไม่มีรถรับวันนั้น)"""
        for l in lots:
            if l.qty <= 0:
                continue
            if l.status == "CHECKED":
                l.status = "IDLE"
            if l.expiry == d:                                          # คืนแรก: ทำไมไม่มีใครเอาออก
                cause = {"provisional": "provisional", "decision": "decision_short",
                         "sell_out": "expected_sell_out"}.get(self.eol_plan.get((l.uid, d)), "not_forwarded")
                self.stats[f"expired_overnight_{cause}"] += 1
            if l.expiry <= d:
                self.stats["expired_unit_days"] += l.qty
                if (d - l.expiry).days >= 1:
                    self.stats["expired_unit_days_over_1_night"] += l.qty
                    self.overdue_lots.add(l.uid)
                self.expired_lots.add(l.uid)
