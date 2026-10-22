"""Backtest 3 นโยบายจัดการ lot บนร้านจำลองจาก mock_v3 (ช่วง test ของ Forecaster) แล้วสรุปเป็น HTML

ใช้งาน (จากโฟลเดอร์ AI/backtest, Python ที่มี lightgbm + scipy เช่น server/.venv):
    python run_backtest.py                       # 60 วัน 2026-08-17 -> 2026-10-15
    python run_backtest.py --start 2026-09-16 --days 30

นโยบาย (ร้านเดียวกัน ของเข้าร้านชุดเดียวกัน ลูกค้าชุดเดียวกัน):
  1 ร้านแบบเดิม       ขายราคาปกติ ของหมดอายุทิ้ง landfill
  2 ลดราคาตามกฎตายตัว  ตามจำนวนวันที่เหลือขาย (ดู FIXED_RULES) ของหมดอายุทิ้ง landfill
  3 product ของเรา     ทุกเช้า Risk Scanner + Forecaster สแกน lot IDLE -> Optimizer ตัดสินใจ -> ร้านทำตาม

โลกจำลอง (เหมือนกันทุกนโยบาย):
  - สต็อกวันแรก = lot_daily.csv วันเริ่ม, ของเข้าร้าน = lot_outcomes.csv (วันรับ / วันหมดอายุ / จำนวน)
  - ลูกค้า = product_daily.latent_demand (ความต้องการจริงที่ราคาเต็ม ไม่ใช่ค่าพยากรณ์)
  - ลดราคา: ยอดเพิ่ม x TRUE_LIFT (ค่าที่ตัวสร้างข้อมูล simulate.py ใช้จริง) ไม่ใช่ค่าที่ Forecaster ประมาณ
  - แบ่งลูกค้าให้ lot แบบเดียวกับตัวสร้างข้อมูล: lot ลดราคาได้ก่อน, 40% หยิบ lot ใหม่สุด, ที่เหลือ FIFO
  - ของทิ้ง: ถังของ partner (ข้อมูล partner จริงจาก Supabase) เรียกรถเมื่อถึงปริมาณที่คุ้มหรือใกล้เพดานเวลา
    กติกาเดียวกันทุกนโยบาย (นโยบาย 1-2 ใช้ landfill อย่างเดียว) ปิดรอบสุดท้ายเก็บถังที่เหลือทั้งหมด
Forecaster ของนโยบาย 3 เทรนใหม่ด้วยข้อมูลก่อนช่วง test (2026-08-04) เท่านั้น ไม่เห็นยอดขายในช่วง backtest

กำไรสุทธิ = รายได้ขาย + มูลค่าเมนูครัว + buyback - ค่าเที่ยว - ค่า handling - ต้นทุนสินค้าทุกหน่วยที่ออกจากร้าน
ความเสียหายจากของทิ้ง = ต้นทุนสินค้าที่ทิ้ง / ส่ง partner + ค่าเที่ยว + handling - buyback
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
AI_DIR = HERE.parent
sys.path.insert(0, str(AI_DIR / "risk_forecaster"))
sys.path.insert(0, str(AI_DIR / "food_waste_optimizer"))

from common import config as rf_config                                            # noqa: E402
from common.sources import load_reference                                         # noqa: E402
from forecaster.model import Forecaster                                           # noqa: E402
from risk_scanner import handoff, risk                                            # noqa: E402
from ai_engine.optimizer import OptimizerConfig, run_optimizer                    # noqa: E402
from ai_engine.optimizer.config import BKK                                        # noqa: E402
from ai_engine.optimizer.context import build_context                             # noqa: E402
from ai_engine.optimizer.models import Inputs                                     # noqa: E402

MOCK = AI_DIR / "risk_forecaster" / "data" / "mock_v3"
SNAPSHOT = AI_DIR / "food_waste_optimizer" / "ai_engine" / "tests" / "fixtures" / "supabase_2026-10-16.json"
TEST_START = date(2026, 8, 4)                       # ช่วง test ของ Forecaster (forecaster_v3_metrics.json)
TRUE_LIFT = {0: 1.0, 20: 1.12, 30: 1.20, 50: 1.35}  # server/scripts/forecast_data/simulate.py MARKDOWN_LIFT
NEWEST_SHARE = 0.40                                 # simulate.py PICK_NEWEST_SHARE
LANDFILL = "P-LDF-01"
# ส่วนลดตามวันที่เหลือขาย (>= 3 วัน, 2 วัน, 1 วัน, วันสุดท้าย) ช่วงตามที่ทีมกำหนด: 0-10 / 10-20 / 20-30 / 30-50%
FIXED_RULES = {"ต่ำ": (0, 10, 20, 30), "กลาง": (5, 15, 25, 40), "สูง": (10, 20, 30, 50)}
METHOD_TH = {"SELL_REGULAR": "ขายราคาปกติ", "MARKDOWN": "ขายลดราคา", "KITCHEN": "เข้าครัว", "DONATION": "บริจาค",
             "ANIMAL_FEED": "อาหารสัตว์", "COMPOSTING": "ปุ๋ยหมัก", "ANAEROBIC_DIGESTION": "ก๊าซชีวภาพ",
             "LANDFILL": "ฝังกลบ"}


def true_lift(pct: float) -> float:
    return float(np.interp(min(max(pct, 0.0), 50.0), list(TRUE_LIFT), list(TRUE_LIFT.values())))


def kg_per_unit(p: dict) -> float:
    size, unit = p.get("net_content_value"), str(p.get("net_content_unit") or "").upper()
    return float(size) * (1000 if unit in ("KG", "L") else 1) / 1000 if size else 0.0


# ---------------------------------------------------------------- โลกจำลอง
@dataclass(eq=False)
class Lot:
    uid: str
    product_id: str
    received: date
    expiry: date
    qty: int
    cost: float
    price: float
    regular: float
    status: str = "IDLE"            # นโยบาย 3: IDLE (รอสแกน) / CHECKED (มี decision แล้ว)
    eol_partner: str | None = None  # นโยบาย 3: ของที่เหลือตอนหมดอายุไป partner นี้ (decision END_OF_LIFE)

    @property
    def disc(self) -> float:
        return max(0.0, (1 - self.price / self.regular) * 100) if self.regular else 0.0


@dataclass
class Bin:
    items: list = field(default_factory=list)     # [(kg, วันที่เข้าถัง)]

    @property
    def kg(self) -> float:
        return sum(k for k, _ in self.items)


class Ledger:
    def __init__(self, name: str):
        self.name = name
        self.money = Counter()        # revenue_full, revenue_md, kitchen_value, buyback, trip_fee, handling, cogs_*
        self.units = Counter()        # ตามวิธี (METHOD_TH)
        self.kg = Counter()
        self.calls = Counter()
        self.calls_below_min = 0
        self.daily = []               # กำไรสุทธิสะสมรายวัน
        self.notes = Counter()

    @property
    def cogs(self) -> float:
        return sum(v for k, v in self.money.items() if k.startswith("cogs_"))

    @property
    def net(self) -> float:
        m = self.money
        return (m["revenue_full"] + m["revenue_md"] + m["kitchen_value"] + m["buyback"]
                - m["trip_fee"] - m["handling"] - self.cogs)

    @property
    def waste_loss(self) -> float:
        m = self.money
        return m["cogs_waste"] + m["trip_fee"] + m["handling"] - m["buyback"]


class World:
    def __init__(self, start: date, days: int):
        self.start, self.end = start, start + timedelta(days=days - 1)
        snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.opt_products = snap["optimize_inputs"]["products"]
        self.catalog = snap["products"]
        self.recipes = snap["optimize_inputs"]["recipes"]
        self.partners = snap["optimize_inputs"]["donation_partners"]
        self.kitchen_rows = [r for r in snap["optimize_inputs"]["kitchen_capacity"]
                             if r["capacity_date"] == snap["optimize_inputs"]["kitchen_capacity"][0]["capacity_date"]]
        self.products = {p["product_id"]: p for p in self.opt_products}
        self.kg = {pid: kg_per_unit(p) for pid, p in self.products.items()}
        pdy = pd.read_csv(MOCK / "product_daily.csv")
        pdy["sale_date"] = pd.to_datetime(pdy.sale_date).dt.date
        self.pdy = pdy
        self.demand = {(r.product_id, r.sale_date): int(r.latent_demand) for r in pdy.itertuples()}
        lot_daily = pd.read_csv(MOCK / "lot_daily.csv")
        outcomes = pd.read_csv(MOCK / "lot_outcomes.csv")
        received = dict(zip(outcomes.lot_uid, outcomes.received_date))
        first = lot_daily[lot_daily.date == start.isoformat()]
        self.initial = [(r.lot_uid, r.product_id, date.fromisoformat(received.get(r.lot_uid, start.isoformat())),
                         date.fromisoformat(r.expiration_date), int(r.opening_qty))
                        for r in first.itertuples() if r.opening_qty > 0]
        later = outcomes[(outcomes.received_date > start.isoformat()) & (outcomes.received_date <= self.end.isoformat())]
        self.deliveries = defaultdict(list)
        for r in later.itertuples():
            self.deliveries[date.fromisoformat(r.received_date)].append(
                (r.lot_uid, r.product_id, date.fromisoformat(r.received_date), date.fromisoformat(r.expiration_date),
                 int(r.initial_qty)))

    def new_lot(self, row) -> Lot:
        uid, pid, rec, exp, qty = row
        p = self.products[pid]
        return Lot(uid, pid, rec, exp, qty, float(p["base_cost"]), float(p["regular_price"]), float(p["regular_price"]))

    def waste_history(self, d: date, days: int = 28) -> dict:
        """ของทิ้งเฉลี่ยต่อวันแยกหมวด (kg) ย้อนหลัง 28 วันถึงเมื่อวาน (เหมือน server: GET /ai/optimize-inputs)"""
        part = self.pdy[(self.pdy.sale_date >= d - timedelta(days=days)) & (self.pdy.sale_date < d)]
        n = part.sale_date.nunique()
        kg = defaultdict(float)
        for r in part.itertuples():
            kg[self.products[r.product_id]["category"]] += r.waste_qty * self.kg[r.product_id]
        return {"from": (d - timedelta(days=days)).isoformat(), "to": (d - timedelta(days=1)).isoformat(),
                "days": n, "kg_per_day": {c: v / n for c, v in kg.items()} if n else {}}

    def partner_ctx(self, d: date, bins: dict | None = None) -> dict:
        """พารามิเตอร์ถังของ partner วันนั้น (โหมด / ปริมาณที่คุ้ม / เพดานเวลา) จาก Optimizer ตัวจริง"""
        inp = {"reference_date": d.isoformat(), "run_id": None, "at_risk_lots": [], "products": self.opt_products,
               "recipes": [], "kitchen_capacity": [], "donation_partners": self.partners, "ingredient_stock": [],
               "waste_history": self.waste_history(d), "partner_bins": []}
        ctx = build_context(Inputs.from_json(inp, self.catalog), datetime.combine(d, time(8, 0), tzinfo=BKK))
        return ctx.partners


# ---------------------------------------------------------------- ขาย / ทิ้ง / เรียกรถ
def sell(world: World, lots: list, d: date, led: Ledger) -> None:
    by_product = defaultdict(list)
    for l in lots:
        if l.qty > 0 and l.received <= d <= l.expiry:
            by_product[l.product_id].append(l)
    for pid, plots in by_product.items():
        want = float(world.demand.get((pid, d), 0))
        for l in sorted([l for l in plots if l.disc > 0.5], key=lambda l: (-l.disc, l.expiry, l.uid)):
            if want <= 0:
                break
            lift = true_lift(l.disc)
            take = min(l.qty, int(round(want * lift)))
            _sold(l, take, led)
            want = max(0.0, want - take / lift)
        reg = sorted([l for l in plots if l.disc <= 0.5 and l.qty > 0], key=lambda l: (l.expiry, l.uid))
        want_n = int(round(want))
        if want_n > 0 and len(reg) > 1:
            newest = max(reg, key=lambda l: (l.received, l.expiry, l.uid))
            take = min(newest.qty, int(round(want_n * NEWEST_SHARE)))
            _sold(newest, take, led)
            want_n -= take
        for l in reg:
            if want_n <= 0:
                break
            take = min(l.qty, want_n)
            _sold(l, take, led)
            want_n -= take


def _sold(l: Lot, n: int, led: Ledger) -> None:
    if n <= 0:
        return
    l.qty -= n
    key = "MARKDOWN" if l.disc > 0.5 else "SELL_REGULAR"
    led.money["revenue_md" if l.disc > 0.5 else "revenue_full"] += n * l.price
    led.money["cogs_sold"] += n * l.cost
    led.units[key] += n


def to_bin(world: World, bins: dict, pid: str, lot: Lot, n: int, d: date, led: Ledger, method: str) -> None:
    if n <= 0:
        return
    lot.qty -= n
    kg = n * world.kg[lot.product_id]
    bins[pid].items.append((kg, d))
    led.money["cogs_waste"] += n * lot.cost
    led.units[method] += n
    led.kg[method] += kg


def run_pickups(world: World, bins: dict, pctx: dict, d: date, led: Ledger, flush: bool = False) -> None:
    """เรียกรถตามกติกาถัง: วันที่ partner มีรอบรับ, ถังถึงปริมาณที่คุ้ม (BIN) หรือรอรอบหน้าแล้วจะเกินเพดานเวลา
    DEDICATED เรียกทุกครั้งที่มีของ, flush = ปิดรอบ backtest เก็บถังที่เหลือ"""
    for pid, b in bins.items():
        if not b.items:
            continue
        pc = pctx[pid]
        days = pc.partner.pickup_days
        if not flush and d.isoweekday() not in days:
            continue
        kg = b.kg
        call = flush or pc.mode == "DEDICATED"
        if not call:
            nxt = next(d + timedelta(days=i) for i in range(1, 8) if (d + timedelta(days=i)).isoweekday() in days)
            oldest = min(t for _, t in b.items)
            call = kg >= pc.expected_kg - 1e-9 or (nxt - oldest).days > pc.max_wait_days + 1e-9
        if call:
            led.money["trip_fee"] += pc.trip_cost
            led.money["handling"] += pc.handling * kg
            led.money["buyback"] += pc.partner.buyback * kg
            led.calls[pid] += 1
            led.calls_below_min += kg < pc.min_kg - 1e-9
            b.items.clear()


def expire(world: World, lots: list, bins: dict, d: date, led: Ledger) -> None:
    for l in lots:
        if l.expiry == d and l.qty > 0:
            pid = l.eol_partner or LANDFILL
            method = world_partner_type(world, pid)
            to_bin(world, bins, pid, l, l.qty, d, led, method)


def world_partner_type(world: World, pid: str) -> str:
    return next(p["partner_type"] for p in world.partners if p["partner_id"] == pid)


# ---------------------------------------------------------------- นโยบาย 1, 2
def run_rule_policy(world: World, name: str, discounts: tuple | None) -> Ledger:
    led = Ledger(name)
    lots = [world.new_lot(r) for r in world.initial]
    bins = defaultdict(Bin)
    d = world.start
    pctx = None
    while d <= world.end:
        lots += [world.new_lot(r) for r in world.deliveries.get(d, [])]
        pctx = world.partner_ctx(d)
        if discounts:
            for l in lots:
                if l.qty <= 0 or l.received > d or l.expiry < d:
                    continue
                left = (l.expiry - d).days
                pct = discounts[0] if left >= 3 else discounts[1] if left == 2 else discounts[2] if left == 1 else discounts[3]
                price = round(l.regular * (1 - pct / 100), 2)
                floor = world.products[l.product_id].get("min_allowed_price")
                l.price = max(price, float(floor)) if floor is not None else price
        sell(world, lots, d, led)
        run_pickups(world, bins, pctx, d, led)
        expire(world, lots, bins, d, led)
        lots = [l for l in lots if l.qty > 0 and l.expiry > d]
        led.daily.append(round(led.net, 2))
        d += timedelta(days=1)
    run_pickups(world, bins, pctx, d, led, flush=True)
    led.daily[-1] = round(led.net, 2)
    led.notes["ending_units"] = sum(l.qty for l in lots)
    led.notes["ending_cost"] = round(sum(l.qty * l.cost for l in lots), 2)
    return led


# ---------------------------------------------------------------- นโยบาย 3: Risk Scanner + Forecaster + Optimizer
class Product3:
    def __init__(self, world: World):
        self.world = world
        self.fc = Forecaster.load()
        df = pd.read_csv(MOCK / "training_dataset.csv")
        hist, products_df, rows = self.fc.build_training(df)
        self.model = self.fc.model_until(rows, pd.Timestamp(TEST_START))       # ไม่เห็นข้อมูลตั้งแต่ช่วง test
        before = hist[hist.sale_date < pd.Timestamp(TEST_START)]
        self.fc.lifts = Forecaster._estimate_lifts(before, Forecaster.clearance_products(products_df))
        self.thresholds = rf_config.load_thresholds()
        ref_products, self.rf_recipes = load_reference()
        self.rf_products = {p["product_id"]: p for p in ref_products}
        self.prod_df = pd.DataFrame([{"product_id": p["product_id"], "category": p["category"],
                                      "shelf_life_days": p["shelf_life_days"]} for p in ref_products])
        pdy = pd.read_csv(MOCK / "product_daily.csv", dtype={"stockout_hour": "Int64"})
        self.pdy_records = pdy
        ctx = pd.read_csv(MOCK / "daily_context.csv")
        self.ctx = ctx
        self.stats = Counter()

    def history(self, d: date) -> list:
        p = self.pdy_records
        keep = (p.sale_date >= (d - timedelta(days=rf_config.HISTORY_DAYS)).isoformat()) & (p.sale_date < d.isoformat())
        return json.loads(p[keep].sort_values(["product_id", "sale_date"]).to_json(orient="records", force_ascii=False))

    def scan(self, lots: list, d: date):
        scan_lots = [{"lot_id": l.uid, "product_id": l.product_id, "received_date": l.received.isoformat(),
                      "expiration_date": l.expiry.isoformat(), "initial_quantity": l.qty, "current_quantity": l.qty,
                      "unit_cost": l.cost, "current_selling_price": l.price, "ai_status": "IDLE"} for l in lots]
        targets = set()
        for l in lots:
            targets |= {(l.product_id, d + timedelta(days=i)) for i in range((l.expiry - d).days + 1)}
        for r in self.rf_recipes:
            if r["is_active"]:
                targets |= {(r["output_product_id"], d + timedelta(days=i)) for i in range(int(r["shelf_life_days"]) + 1)}
        to = max([l.expiry for l in lots] + [d + timedelta(days=7)]).isoformat()
        ctx = json.loads(self.ctx[(self.ctx.context_date >= d.isoformat()) & (self.ctx.context_date <= to)]
                         .to_json(orient="records", force_ascii=False))
        mu = self.fc.predict_daily(self.history(d), ctx, self.prod_df, d, sorted(targets), model=self.model)
        demand = {(r.product_id, r.date.date()): float(r.mu) for r in mu.itertuples()}
        results = risk.assess(scan_lots, demand, self.fc.phi_for, d, self.thresholds, 0.0)
        recipe_rows = handoff.build(results, self.rf_products, self.rf_recipes, demand, self.fc.lifts, d, self.fc.phi_for)
        return results, recipe_rows

    def run(self) -> Ledger:
        w, led = self.world, Ledger("product")
        lots = [w.new_lot(r) for r in w.initial]
        bins = defaultdict(Bin)
        d, pctx = w.start, None
        while d <= w.end:
            lots += [w.new_lot(r) for r in w.deliveries.get(d, [])]
            pctx = w.partner_ctx(d)
            self.day(lots, bins, d, led)
            sell(w, lots, d, led)
            run_pickups(w, bins, pctx, d, led)
            expire(w, lots, bins, d, led)
            lots = [l for l in lots if l.qty > 0 and l.expiry > d]
            led.daily.append(round(led.net, 2))
            d += timedelta(days=1)
        run_pickups(w, bins, pctx, d, led, flush=True)
        led.daily[-1] = round(led.net, 2)
        led.notes.update(self.stats)
        led.notes["ending_units"] = sum(l.qty for l in lots)
        led.notes["ending_cost"] = round(sum(l.qty * l.cost for l in lots), 2)
        return led

    def day(self, lots: list, bins: dict, d: date, led: Ledger) -> None:
        w = self.world
        idle = [l for l in lots if l.status == "IDLE" and l.qty > 0 and l.received <= d <= l.expiry]
        if not idle:
            return
        results, recipe_rows = self.scan(idle, d)
        by_uid = {l.uid: l for l in lots}
        run_id = f"sim-{d.isoformat()}"
        at_risk = []
        for r in results:
            p = r["payload"]
            self.stats["lots_scanned"] += 1
            if p["risk_level"] not in rf_config.FORWARD_LEVELS:
                continue
            l = by_uid[p["lot_id"]]
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
        kitchen = [{**k, "capacity_date": (d + timedelta(days=i)).isoformat()} for i in (0, 1) for k in w.kitchen_rows]
        open_bins = [{"partner_id": pid, "open_kg": b.kg, "decisions": len(b.items),
                      "oldest_at": datetime.combine(min(t for _, t in b.items), time(20, 0), tzinfo=BKK).isoformat()}
                     for pid, b in bins.items() if b.items]
        inputs = {"reference_date": d.isoformat(), "run_id": run_id, "at_risk_lots": at_risk,
                  "recipe_demand": [{**r, "run_id": run_id} for r in recipe_rows], "products": w.opt_products,
                  "recipes": w.recipes, "kitchen_capacity": kitchen, "donation_partners": w.partners,
                  "ingredient_stock": stock, "waste_history": w.waste_history(d), "partner_bins": open_bins}
        now = datetime.combine(d, time(8, 0), tzinfo=BKK)
        try:
            res = run_optimizer(inputs, products_catalog=w.catalog, now=now, strict=False, with_baselines=False)
        except Exception as e:                                         # ไม่ให้ทั้ง backtest ล้มเพราะวันเดียว
            self.stats["optimizer_errors"] += 1
            print(f"  {d}: optimizer error {type(e).__name__}: {e}")
            return
        self.stats["violation_days"] += bool(res["violations"] or res["payload_errors"])
        self.apply(res, lots, bins, d, led, by_uid)

    def apply(self, res: dict, lots: list, bins: dict, d: date, led: Ledger, by_uid: dict) -> None:
        w, plan = self.world, res["plan"]
        decided = {x["assessment_id"] for x in res["payload"]["decisions"]}
        released = set(res["lots_to_release"])
        for x in res["payload"]["decisions"]:
            self.stats[f"decision_{x['action_type']}"] += 1
        for lo in plan["lots"]:
            l = by_uid[lo["lot_id"]]
            eol = Counter()
            for p in lo["portions"]:
                m, det, n = p["method"], p["details"], p["units"]
                if m == "MARKDOWN" and n > 0:                          # ติดป้ายทุกชิ้นบนชั้น -> lot ใหม่ราคาลด (IDLE)
                    l.qty -= n
                    lots.append(Lot(f"{l.uid}~md{d:%m%d}", l.product_id, l.received, l.expiry, n, l.cost,
                                    float(det["unit_price"]), l.regular))
                elif m in ("KITCHEN", "KITCHEN_INGREDIENT"):
                    take = min(n, l.qty)
                    l.qty -= take
                    led.money["cogs_kitchen"] += take * l.cost
                    led.units["KITCHEN"] += take
                elif det.get("partner_id") and det.get("timing") == "NOW":
                    to_bin(w, bins, det["partner_id"], l, min(n, l.qty), d, led, m)
                elif det.get("partner_id") and det.get("timing") == "END_OF_LIFE" and not det.get("provisional"):
                    eol[det["partner_id"]] += n
                elif m == "UNRESOLVED" and det.get("timing") != "END_OF_LIFE":
                    to_bin(w, bins, LANDFILL, l, min(n, l.qty), d, led, "LANDFILL")
            if eol:
                l.eol_partner = eol.most_common(1)[0][0]
            l.status = "IDLE" if lo["lot_id"] in released else "CHECKED"
            if lo["assessment_id"] not in decided and lo["lot_id"] not in released:
                self.stats["lots_without_decision"] += 1
        for j in plan["kitchen_jobs"]:                                 # มูลค่าเมนู (ค่าคาดหมาย) - ค่าไฟน้ำ - วัตถุดิบปกติ
            led.money["kitchen_value"] += (j["revenue_thb"] - j["utility_cost_thb"]
                                           - j["primary_from_regular_stock_thb"] + j["secondary_credit_thb"])
            for x in j["inputs"]:
                if x["role"] != "ANCHOR" and not x.get("at_risk") and x["lot_id"] in by_uid:
                    src = by_uid[x["lot_id"]]
                    src.qty -= min(src.qty, math.ceil(x["units"] - 1e-9))   # DB ตัดเป็นหน่วยเต็ม ต้นทุนอยู่ในมูลค่าเมนูแล้ว


# ---------------------------------------------------------------- รายงาน
def summarize(led: Ledger) -> dict:
    m = led.money
    sold_units = led.units["SELL_REGULAR"] + led.units["MARKDOWN"]
    waste_units = sum(v for k, v in led.units.items() if k not in ("SELL_REGULAR", "MARKDOWN", "KITCHEN"))
    landfill_kg = led.kg["LANDFILL"]
    waste_kg = sum(led.kg.values())
    return {
        "name": led.name, "net_profit": round(led.net, 2), "waste_loss": round(led.waste_loss, 2),
        "revenue": round(m["revenue_full"] + m["revenue_md"], 2), "revenue_markdown": round(m["revenue_md"], 2),
        "kitchen_value": round(m["kitchen_value"], 2), "buyback": round(m["buyback"], 2),
        "trip_fee": round(m["trip_fee"], 2), "handling": round(m["handling"], 2),
        "cogs_total": round(led.cogs, 2), "cogs_waste": round(m["cogs_waste"], 2),
        "units": dict(led.units), "sold_units": sold_units, "waste_units": waste_units,
        "kg": {k: round(v, 2) for k, v in led.kg.items()}, "waste_kg": round(waste_kg, 2),
        "landfill_kg": round(landfill_kg, 2), "calls": dict(led.calls), "calls_below_min": led.calls_below_min,
        "daily": led.daily, "notes": dict(led.notes),
    }


def pct(a: float, b: float) -> float:
    return (a - b) / abs(b) * 100 if b else 0.0


def baht(x: float) -> str:
    return f"{x:,.0f}"


def signed(x: float) -> str:
    return f"{x:+,.0f}" if round(x) else "0"


def environment(world: World, fc) -> dict:
    """สภาพแวดล้อมของ backtest สำหรับรายงาน: ร้านจำลอง / partner / ผลวัดของ Forecaster + Risk Scanner บนช่วง test"""
    fm = json.loads((rf_config.MODEL_DIR / f"{rf_config.MODEL_VERSION}_metrics.json").read_text(encoding="utf-8"))
    th = json.loads((rf_config.MODEL_DIR / "risk_thresholds.json").read_text(encoding="utf-8"))
    pctx = world.partner_ctx(world.start)
    return {
        "data": MOCK.name, "history": fm["history"], "split": fm["split"],
        "categories": sorted({p["category"] for p in world.products.values()}),
        "store_hours": f"{rf_config.STORE_OPEN_HOUR:02d}:00-{rf_config.STORE_CLOSE_HOUR:02d}:00",
        "true_lift": TRUE_LIFT, "newest_share": NEWEST_SHARE, "max_hold_days": OptimizerConfig().max_hold_days,
        "partners": [{"partner_id": pid, "type": pc.partner.partner_type, "mode": pc.mode,
                      "trip_cost": round(pc.trip_cost, 2), "pickup_days": sorted(pc.partner.pickup_days)}
                     for pid, pc in sorted(pctx.items())],
        "forecaster": {"version": rf_config.MODEL_VERSION, "model": "LightGBM" if fm["chosen"] == "lgbm" else fm["chosen"],
                       "trees": fm["params"]["n_estimators"], "features": int(fc.model.n_features_in_),
                       "trained_until": (TEST_START - timedelta(days=1)).isoformat(),
                       "test_wape": fm["test_wape"], "fva_pct": fm["test_fva_pct"], "bias_pct": fm["test_bias_pct"],
                       "coverage_80": {k: v["coverage_pct"] for k, v in fm["test_coverage_80"].items()},
                       "lifts_used": {str(k): round(v, 3) for k, v in fc.lifts.items()}},
        "risk": {"cutoffs": {k: th[k] for k in ("MEDIUM", "HIGH", "CRITICAL")}, "forward": list(rf_config.FORWARD_LEVELS),
                 "test": th["test"]},
    }


CSS = """
:root{--bg:#fff6ec;--card:#fff;--ink:#3b2a1d;--muted:#7d6552;--accent:#e8853d;--accent-dark:#b35a1b;
--soft:#ffe8d1;--soft2:#fff2e4;--line:#f4e3d2;--bad:#c0392b}
body{margin:0;background:var(--bg);font-family:"Sarabun","Noto Sans Thai","Leelawadee UI",Tahoma,sans-serif;color:var(--ink)}
.page{max-width:1280px;margin:0 auto;padding:32px 40px}
h1{font-size:30px;margin:0 0 4px} h2{font-size:20px;margin:30px 0 12px;color:var(--accent-dark)}
.meta{color:var(--muted);font-size:15px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:22px}
.kpi,table,.note,.card{background:var(--card);border-radius:14px;box-shadow:0 1px 3px rgba(120,70,20,.14)}
.kpi{padding:18px 20px;border-top:5px solid var(--accent)}
.kpi.bad{border-top-color:var(--bad)} .kpi.bad .kpi-sub{color:var(--bad)}
.kpi-label{font-size:14px;color:var(--muted)} .kpi-value{font-size:30px;font-weight:700;margin:6px 0 2px}
.kpi-sub{font-size:14px;color:var(--accent-dark);font-weight:600}
table{width:100%;border-collapse:collapse;overflow:hidden;font-size:15px}
th{background:var(--accent-dark);color:#fff;font-weight:600;padding:10px 12px;text-align:right}
td{padding:9px 12px;text-align:right;border-bottom:1px solid var(--line)}
th.l,td.l{text-align:left} tr:last-child td{border-bottom:none} tr.ours td{background:var(--soft2);font-weight:700}
.two{display:grid;grid-template-columns:1fr 1fr;gap:20px} .three{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.note,.card{padding:16px 20px;font-size:14px;line-height:1.65;color:#4a3828}
.card h3{margin:0 0 10px;font-size:16px;color:var(--accent-dark)}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:5px 14px} .kv .k{color:var(--muted)}
.bar-label{font-size:14px;color:var(--muted);margin:14px 0 4px} .bar-label b{color:var(--ink)}
.bar{display:flex;height:42px;border-radius:10px;overflow:hidden;font-size:13px;font-weight:600}
.bar div{display:flex;align-items:center;padding:0 10px;white-space:nowrap;overflow:hidden}
.seg-fixed{background:#f6d2b0;color:#6b4425} .seg-pool{background:var(--accent);color:#fff}
.seg-ours{background:var(--accent-dark);color:#fff} .seg-rest{background:var(--soft);color:#6b4425}
table.mini{box-shadow:none;font-size:13px;margin-bottom:12px} table.mini th{padding:6px 8px}
table.mini td{padding:5px 8px}
.big{font-size:28px;font-weight:700;color:var(--accent-dark)}
ul.why{margin:0;padding-left:20px} ul.why li{margin:6px 0}
"""


def render_html(res: dict) -> str:
    p1, p2, p3, env = res["policy1"], res["policy2"], res["policy3"], res["environment"]
    fc, rk = env["forecaster"], env["risk"]
    e = html.escape
    rows_policy = [("1 · ร้านแบบเดิม", p1), (f"2 · ลดราคาตามกฎตายตัว (ช่วง{res['policy2_variant']})", p2),
                   ("3 · Risk Scanner + Forecaster + Optimizer", p3)]

    def kpi(label, value, sub="", tone=""):
        return (f'<div class="kpi {tone}"><div class="kpi-label">{e(label)}</div>'
                f'<div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>')

    def kv(rows):
        return '<div class="kv">' + "".join(f'<div class="k">{e(k)}</div><div>{v}</div>' for k, v in rows) + "</div>"

    save1, save2 = p3["net_profit"] - p1["net_profit"], p3["net_profit"] - p2["net_profit"]
    tone = lambda x: "" if x >= 0 else "bad"
    loss_cut1 = (p1["waste_loss"] - p3["waste_loss"]) / p1["waste_loss"] * 100 if p1["waste_loss"] else 0
    landfill_cut1 = (p1["landfill_kg"] - p3["landfill_kg"]) / p1["landfill_kg"] * 100 if p1["landfill_kg"] else 0

    # เพดานเงินที่ประหยัดได้: ความเสียหายของร้านเดิม = ค่าเรียกรถ (คงที่ตราบที่ยังมีของทิ้ง) + ส่วนที่ลดได้จริง
    loss, trip = p1["waste_loss"], p1["trip_fee"]
    pool = loss - trip
    captured = save1 / pool * 100 if pool else 0
    calls1, calls3 = sum(p1["calls"].values()), sum(p3["calls"].values())
    units1 = p1["sold_units"] + p1["waste_units"]
    half = len(p1["daily"]) // 2
    h1 = p3["daily"][half - 1] - p1["daily"][half - 1]
    h2 = (p3["daily"][-1] - p3["daily"][half - 1]) - (p1["daily"][-1] - p1["daily"][half - 1])
    n3 = p3["notes"]

    table = "".join(
        f"<tr{' class=ours' if p is p3 else ''}><td class='l'>{e(n)}</td><td>{baht(p['net_profit'])}</td>"
        f"<td>{baht(p['revenue'])}</td><td>{baht(p['cogs_waste'])}</td>"
        f"<td>{baht(p['trip_fee'] + p['handling'] - p['buyback'])}</td><td>{baht(p['waste_loss'])}</td>"
        f"<td>{p['waste_kg']:,.0f}</td><td>{sum(p['calls'].values())}</td></tr>"
        for n, p in rows_policy)
    methods = ["SELL_REGULAR", "MARKDOWN", "KITCHEN", "DONATION", "ANIMAL_FEED", "COMPOSTING", "ANAEROBIC_DIGESTION",
               "LANDFILL"]
    mix = "".join(f"<tr><td class='l'>{e(METHOD_TH[m])}</td>" + "".join(
        f"<td>{p['units'].get(m, 0):,}</td>" for _, p in rows_policy) + "</tr>" for m in methods)
    variants = "".join(
        f"<tr><td class='l'>ช่วง{e(k)} ({' / '.join(f'{x}%' for x in FIXED_RULES[k])})</td>"
        f"<td>{baht(v['net_profit'])}</td><td>{baht(v['waste_loss'])}</td>"
        f"<td>{signed(p3['net_profit'] - v['net_profit'])}</td><td>{pct(p3['net_profit'], v['net_profit']):+.1f}%</td></tr>"
        for k, v in res["policy2_variants"].items())
    lift = lambda d: " / ".join(f"{int(k)}% → ×{v:.2f}" for k, v in sorted(d.items(), key=lambda kv: int(kv[0])) if int(k))
    days = "จ อ พ พฤ ศ ส อา".split()
    partners = "".join(
        f"<tr><td class='l'>{e(METHOD_TH.get(p['type'], p['type']))}</td><td>{baht(p['trip_cost'])}</td>"
        f"<td class='l'>{'ถังสะสม' if p['mode'] == 'BIN' else 'เรียกเฉพาะ'}</td>"
        f"<td class='l'>{'ทุกวัน' if len(p['pickup_days']) == 7 else ' '.join(days[d - 1] for d in p['pickup_days'])}</td></tr>"
        for p in env["partners"])
    sp = {k: v.replace("->", "→") for k, v in env["split"].items()}
    store = kv([
        ("ข้อมูล", f"{e(env['data'])} ร้านจำลอง (ยอดขายรายชั่วโมงจาก simulate.py)"),
        ("ข้อมูลทั้งหมด", e(env["history"].replace("->", "→"))),
        ("ช่วงที่ทดสอบ", f"<b>{res['start']} → {res['end']} ({res['days']} วัน)</b> อยู่ในช่วง test ของ Forecaster"),
        ("สินค้า", f"{res['products']} SKU · {len(env['categories'])} หมวด ({e(', '.join(env['categories']))})"),
        ("lot", f"สต็อกวันแรก + ของเข้าร้าน รวม {res['lots_total']:,} lot (ชุดเดียวกันทุกนโยบาย)"),
        ("ลูกค้า", "latent_demand = ความต้องการจริงที่ราคาเต็ม (ไม่ใช่ค่าพยากรณ์)"),
        ("ร้านเปิด", f"{env['store_hours']} · นโยบาย 3 สแกนและตัดสินใจทุกเช้า 08:00"),
        ("ลดราคาแล้วขายเพิ่ม", f"{lift(env['true_lift'])} (ค่าจริงของตัวสร้างข้อมูล)"),
        ("ลูกค้าหยิบ lot", f"ลดราคาก่อน · {env['newest_share']:.0%} หยิบ lot ใหม่สุด · ที่เหลือหมดอายุก่อนได้ก่อน"),
    ])
    cov = " · ".join(f"{k} วัน {v:.1f}%" for k, v in fc["coverage_80"].items())
    model = kv([
        ("โมเดลในเครื่อง", f"{e(fc['version'])}.pkl · {e(fc['model'])} {fc['trees']} ต้นไม้ · {fc['features']} feature (เทรนแล้ว)"),
        ("แบ่งข้อมูล", f"train {e(sp['train'])}<br>validation {e(sp['validation'])}<br>test {e(sp['test'])}"),
        ("ใน backtest", f"<b>เทรนใหม่ด้วยข้อมูลถึง {fc['trained_until']} เท่านั้น</b> ไม่เห็นยอดขายช่วงทดสอบ"),
        ("ความคลาดเคลื่อน (WAPE)", f"{fc['test_wape']['lgbm']:.2f}% · ค่าเฉลี่ยวันเดียวกันของสัปดาห์ "
                                   f"{fc['test_wape']['same_dow']:.2f}% (ดีกว่า {fc['fva_pct']:.1f}%)"),
        ("ทายเกิน/ขาดรวม", f"{fc['bias_pct']:+.2f}%"),
        ("ยอดจริงตกในช่วงพยากรณ์ 80%", cov),
        ("lift ที่โมเดลประมาณ", f"{lift(fc['lifts_used'])} (จากข้อมูลก่อน test)"),
        ("Risk Scanner", f"เกณฑ์ MEDIUM / HIGH / CRITICAL = {' / '.join(str(v) for v in rk['cutoffs'].values())} · "
                         f"ส่งต่อ {e(' + '.join(rk['forward']))}"),
        ("Risk Scanner ช่วง test", f"แม่น (precision) {rk['test']['forward_precision']:.1%} · "
                                   f"จับได้ (recall) {rk['test']['forward_recall']:.1%}"),
    ])
    disposal = (f"<table class='mini'><tr><th class='l'>partner (Supabase จริง)</th><th>บาท/ครั้ง</th>"
                f"<th class='l'>โหมด</th><th class='l'>วันรับ</th></tr>{partners}</table>") + kv([
        ("กติกาถัง", f"เรียกรถเมื่อถึงปริมาณที่คุ้ม หรือของรอเกิน {env['max_hold_days']:g} วัน (เหมือนกันทุกนโยบาย)"),
        ("นโยบาย 1-2", "ของหมดอายุไปฝังกลบอย่างเดียว"),
        ("นโยบาย 3", "เลือกได้ทุก partner + เข้าครัวทำเมนู + ลดราคา"),
        ("ปิดรอบ", "วันสุดท้ายเก็บถังที่เหลือทั้งหมด (ทุกนโยบาย)"),
    ])
    why = "".join(f"<li>{x}</li>" for x in [
        f"<b>ร้านต้นแบบทิ้งน้อยอยู่แล้ว:</b> ของทิ้ง {p1['waste_units']:,} จาก {units1:,} ชิ้น "
        f"({p1['waste_units'] / units1:.1%}) ความเสียหายจากของทิ้งเป็น {loss / p1['revenue']:.1%} ของรายได้",
        f"<b>ค่าเรียกรถลดไม่ได้:</b> {baht(trip)} บาท ({trip / loss:.0%} ของความเสียหาย) "
        + (f"ทุกนโยบายเรียกรถ {calls1} ครั้งเท่ากัน" if calls1 == calls3 else f"เรียกรถ {calls1} → {calls3} ครั้ง")
        + f" เพราะเพดานเก็บของ {env['max_hold_days']:g} วันบังคับให้เรียกตามเวลา ไม่ใช่ตามปริมาณ",
        f"<b>Risk Scanner จับ lot ที่จะเหลือได้ราว {rk['test']['forward_recall']:.0%}:</b> "
        f"{res['days']} วันส่งต่อ Optimizer {n3.get('lots_forwarded', 0):,} lot ที่หลุดการตรวจจับถูกทิ้งเหมือนร้านเดิม",
        f"<b>ร้านเล็ก ข้อมูล mock:</b> {res['products']} SKU ผลจึงควรดูเป็น % ของเพดาน ({captured:.0f}%) มากกว่าจำนวนบาท",
    ])
    w_fixed = trip / loss * 100 if loss else 0
    w_ours = min(max(captured, 0), 100)

    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtest ผลกระทบ No-Waste-Bro</title><style>{CSS}</style></head><body><div class="page">
<h1>ผลกระทบของ No-Waste-Bro: backtest {res['days']} วัน</h1>
<div class="meta">ร้านจำลองจาก {e(env['data'])} · {res['start']} ถึง {res['end']} (ช่วง test ของ Forecaster) · สินค้า {res['products']} SKU ·
lot เข้าร้าน {res['lots_total']:,} lot · ลูกค้าจริงจาก latent_demand · หน่วยเงิน: บาท</div>

<div class="kpis">
{kpi("กำไรสุทธิ · นโยบาย 3 (ของเรา)", baht(p3['net_profit']), f"ร้านแบบเดิม {baht(p1['net_profit'])} · กฎตายตัว {baht(p2['net_profit'])}")}
{kpi("กำไรสุทธิ เทียบร้านแบบเดิม (บาท)", signed(save1), f"{pct(p3['net_profit'], p1['net_profit']):+.1f}% · ได้ {captured:.0f}% ของเพดานที่ประหยัดได้", tone(save1))}
{kpi("กำไรสุทธิ เทียบลดราคาตามกฎ (บาท)", signed(save2), f"{pct(p3['net_profit'], p2['net_profit']):+.1f}%", tone(save2))}
{kpi("ความเสียหายจากของทิ้งลดลง เทียบร้านแบบเดิม", f"{loss_cut1:.1f}%", f"ฝังกลบ {p1['landfill_kg']:,.0f} → {p3['landfill_kg']:,.0f} kg ({-landfill_cut1:+.1f}%)", tone(loss_cut1))}
</div>

<h2>เทียบ 3 นโยบาย</h2>
<table><tr><th class="l">นโยบาย</th><th>กำไรสุทธิ</th><th>รายได้ขาย</th><th>ต้นทุนของที่ทิ้ง</th>
<th>ค่ากำจัดสุทธิ</th><th>ความเสียหายจากของทิ้ง</th><th>ของทิ้ง (kg)</th><th>เรียกรถ (ครั้ง)</th></tr>{table}</table>

<h2>เพดานเงินที่ประหยัดได้ในร้านนี้</h2>
<div class="two">
<div class="card">
<div class="bar-label">ความเสียหายจากของทิ้งของร้านแบบเดิม <b>{baht(loss)} บาท</b> ({loss / p1['net_profit']:.1%} ของกำไร)</div>
<div class="bar"><div class="seg-fixed" style="width:{w_fixed:.1f}%">ค่าเรียกรถ {baht(trip)} (คงที่)</div>
<div class="seg-pool" style="width:{100 - w_fixed:.1f}%">ส่วนที่ลดได้ {baht(pool)}</div></div>
<div class="bar-label">ส่วนที่ลดได้ = <b>เพดานการประหยัด {baht(pool)} บาท</b> (กำไรเพิ่มได้สูงสุดราว {pool / p1['net_profit']:.1%})</div>
<div class="bar"><div class="seg-ours" style="width:{w_ours:.1f}%">ของเรา {signed(save1)}</div>
<div class="seg-rest" style="width:{100 - w_ours:.1f}%">ยังเหลือ {baht(pool - max(save1, 0))}</div></div>
<div style="margin-top:14px"><span class="big">{captured:.1f}%</span> ของเพดาน · ต้นทุนของที่ทิ้ง {baht(p1['cogs_waste'])} +
handling {baht(p1['handling'] - p1['buyback'])} บาท<br>
ถ้าไม่มีของทิ้งเลยจนไม่ต้องเรียกรถ เพดานตามทฤษฎี = {baht(loss)} บาท ({loss / p1['net_profit']:.1%} ของกำไร)</div>
</div>
<div class="card"><h3>ทำไมตัวเลขดูน้อย</h3><ul class="why">{why}</ul></div>
</div>

<h2>สภาพแวดล้อมที่ใช้ทดสอบ</h2>
<div class="three">
<div class="card"><h3>ร้านจำลองและช่วงเวลา</h3>{store}</div>
<div class="card"><h3>Forecaster + Risk Scanner</h3>{model}</div>
<div class="card"><h3>การกำจัดและ partner</h3>{disposal}</div>
</div>

<div class="two">
<div><h2>สินค้าไปทางไหน (หน่วย)</h2>
<table><tr><th class="l">วิธี</th><th>1 · เดิม</th><th>2 · กฎตายตัว</th><th>3 · ของเรา</th></tr>{mix}</table></div>
<div><h2>เทียบกฎตายตัวทุกช่วงส่วนลด</h2>
<table><tr><th class="l">ส่วนลด (≥3 / 2 / 1 วัน / วันสุดท้าย)</th><th>กำไรสุทธิ</th><th>ความเสียหาย</th>
<th>ของเราดีกว่า (บาท)</th><th>%</th></tr>{variants}</table>
<h2>ความสม่ำเสมอ</h2>
<div class="note">กำไรของเราเทียบร้านแบบเดิม: {half} วันแรก <b>{signed(h1)}</b> บาท · {len(p1['daily']) - half} วันหลัง <b>{signed(h2)}</b> บาท ·
นโยบาย 3 สแกน {n3.get('lots_scanned', 0):,} ครั้ง ส่งต่อ Optimizer {n3.get('lots_forwarded', 0):,} lot ·
decision ลดราคา {n3.get('decision_MARKDOWN', 0)} · เข้าครัว {n3.get('decision_KITCHEN_REPURPOSE', 0)} · ฝังกลบ {n3.get('decision_LANDFILL', 0)}</div></div>
</div>

<h2>วิธีคิดเงินและข้อจำกัด</h2>
<div class="note">
<b>กำไรสุทธิ</b> = รายได้ขาย + มูลค่าเมนูครัว + รับซื้อคืน − ค่าเรียกรถ − handling − ต้นทุนสินค้าทุกหน่วยที่ออกจากร้าน ·
<b>ความเสียหายจากของทิ้ง</b> = ต้นทุนของที่ทิ้ง + ค่าเรียกรถ + handling − รับซื้อคืน ·
<b>นโยบาย 2</b> เทียบกับช่วงส่วนลดที่ได้กำไรมากสุด (ไม่ให้ตัวเลขของเราดูดีเกินจริง) ·
<b>ข้อจำกัด:</b> ไม่จำลองของเสียหายระหว่างวัน, มูลค่าเมนูครัวใช้ค่าคาดหมายของแผน, ข้อมูลเป็น mock {res['products']} SKU
</div>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=date(2026, 8, 17))
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--out", type=Path, default=HERE / "output")
    ap.add_argument("--render-only", action="store_true", help="สร้าง HTML ใหม่จาก backtest_result.json เดิม (ไม่รันใหม่)")
    args = ap.parse_args()
    if args.render_only:
        path = args.out / "backtest_result.json"
        res = json.loads(path.read_text(encoding="utf-8"))
        if "environment" not in res:
            world = World(date.fromisoformat(res["start"]), res["days"])
            res["environment"] = environment(world, Product3(world).fc)
            path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        (args.out / "backtest_report.html").write_text(render_html(res), encoding="utf-8")
        print(f"ไฟล์: {args.out / 'backtest_report.html'}")
        return
    if args.start < TEST_START:
        raise SystemExit(f"--start ต้องไม่ก่อน {TEST_START} (Forecaster ต้องไม่เห็นข้อมูลช่วงที่ทดสอบ)")
    world = World(args.start, args.days)
    print(f"backtest {world.start} -> {world.end} | lot เริ่ม {len(world.initial)} | ของเข้าร้าน "
          f"{sum(len(v) for v in world.deliveries.values())} lot")

    p1 = summarize(run_rule_policy(world, "policy1", None))
    print(f"  1 ร้านแบบเดิม           กำไรสุทธิ {p1['net_profit']:>12,.2f}  ความเสียหาย {p1['waste_loss']:>10,.2f}")
    variants = {}
    for k, rule in FIXED_RULES.items():
        variants[k] = summarize(run_rule_policy(world, f"policy2_{k}", rule))
        print(f"  2 กฎตายตัว ช่วง{k:<5}      กำไรสุทธิ {variants[k]['net_profit']:>12,.2f}  ความเสียหาย {variants[k]['waste_loss']:>10,.2f}")
    best2 = max(variants, key=lambda k: variants[k]["net_profit"])     # เทียบกับกฎที่ดีที่สุด (ไม่ให้ตัวเลขดูดีเกินจริง)
    print("  3 Risk Scanner + Forecaster + Optimizer (รายวัน) ...")
    product = Product3(world)
    p3 = summarize(product.run())
    print(f"  3 ของเรา                 กำไรสุทธิ {p3['net_profit']:>12,.2f}  ความเสียหาย {p3['waste_loss']:>10,.2f}")

    res = {"start": world.start.isoformat(), "end": world.end.isoformat(), "days": args.days,
           "products": len(world.products),
           "lots_total": len(world.initial) + sum(len(v) for v in world.deliveries.values()),
           "policy1": p1, "policy2": variants[best2], "policy2_variant": best2, "policy2_variants": variants,
           "policy3": p3,
           "saving_vs_policy1_thb": round(p3["net_profit"] - p1["net_profit"], 2),
           "saving_vs_policy1_pct": round(pct(p3["net_profit"], p1["net_profit"]), 2),
           "saving_vs_policy2_thb": round(p3["net_profit"] - variants[best2]["net_profit"], 2),
           "saving_vs_policy2_pct": round(pct(p3["net_profit"], variants[best2]["net_profit"]), 2),
           "environment": environment(world, product.fc)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "backtest_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (args.out / "backtest_report.html").write_text(render_html(res), encoding="utf-8")
    print(f"\nของเรา vs ร้านแบบเดิม: {res['saving_vs_policy1_thb']:+,.2f} บาท ({res['saving_vs_policy1_pct']:+.2f}%)")
    print(f"ของเรา vs กฎตายตัว (ช่วง{best2}): {res['saving_vs_policy2_thb']:+,.2f} บาท ({res['saving_vs_policy2_pct']:+.2f}%)")
    print(f"ไฟล์: {args.out / 'backtest_report.html'}")


if __name__ == "__main__":
    main()
