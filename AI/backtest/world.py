"""โลกจำลองของ backtest (ใช้ร่วมกันทุกนโยบาย): ร้าน ลูกค้า ของเข้าร้าน ถัง / รถของ partner บัญชีเงิน

ไฟล์นี้ไม่ import โค้ดของ Optimizer: กติกาเรียกรถเป็นกฎของโลก ไม่ใช่ของนโยบายที่กำลังวัด
(backtest 22 ต.ค. ดึงค่าถังจาก PartnerCtx ของ Optimizer ซึ่งบน main ไม่มี)

กติกาเรียกรถ (--disposal):
  dedicated  รถของ partner มารับทุกวันที่มีรอบรับและมีของรอ คิดค่าเที่ยวเต็มทุกครั้ง (= วิธีที่ Optimizer บน main คิดต้นทุน:
             decision ของ partner วันนี้ = รถมาวันนี้) เรียกรถหลังปิดร้าน เก็บทั้งของที่ดึงออกตอนเช้าและของหมดอายุคืนนั้น
  bins       ถังสะสม: เรียกรถเมื่อถังถึงปริมาณที่คุ้ม หรือของรอนานจนจะเกินเพดานเวลา (เหมือน backtest 22 ต.ค. ทุกตัวเลข)

โลกจำลอง (เหมือนกันทุกนโยบาย):
  - สต็อกวันแรก = lot_daily.csv วันเริ่ม, ของเข้าร้าน = lot_outcomes.csv (วันรับ / วันหมดอายุ / จำนวน)
  - ลูกค้า = product_daily.latent_demand (ความต้องการจริงที่ราคาเต็ม ไม่ใช่ค่าพยากรณ์)
  - ลดราคา: ยอดเพิ่ม x TRUE_LIFT (ค่าที่ตัวสร้างข้อมูล simulate.py ใช้จริง) ไม่ใช่ค่าที่ Forecaster ประมาณ
  - แบ่งลูกค้าให้ lot แบบเดียวกับตัวสร้างข้อมูล: lot ลดราคาได้ก่อน, 40% หยิบ lot ใหม่สุด, ที่เหลือ FIFO
  - ของหมดอายุขายไม่ได้ (ประกาศ สธ. 367) แต่ยังอยู่ในร้านจนกว่าจะมีคนเอาออก
"""
from __future__ import annotations

import itertools
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
AI_DIR = HERE.parent
MOCK = AI_DIR / "risk_forecaster" / "data" / "mock_v3"
# ข้อมูล partner / สินค้า / สูตร จาก Supabase 22 ต.ค. 2026 (ชุดเดียวกับ backtest ของ optimizer-update)
# fixture ของ main (ai_engine/tests/fixtures) ยังเป็นค่า partner ชุดเก่า (min_kg 100) จึงไม่ใช้ตัวนั้น
SNAPSHOT = HERE / "data" / "supabase_2026-10-22.json"
TRUE_LIFT = {0: 1.0, 20: 1.12, 30: 1.20, 50: 1.35}  # server/scripts/forecast_data/simulate.py MARKDOWN_LIFT
NEWEST_SHARE = 0.40                                 # simulate.py PICK_NEWEST_SHARE
LANDFILL = "P-LDF-01"
MAX_HOLD_DAYS = 2.0                                 # เพดานเวลาที่ของรอในถังได้ (ค่าเดียวกับ backtest 22 ต.ค.)
DISPOSAL_MODES = ("dedicated", "bins")
EPS = 1e-9
METHOD_TH = {"SELL_REGULAR": "ขายราคาปกติ", "MARKDOWN": "ขายลดราคา", "KITCHEN": "เข้าครัว", "DONATION": "บริจาค",
             "ANIMAL_FEED": "อาหารสัตว์", "COMPOSTING": "ปุ๋ยหมัก", "ANAEROBIC_DIGESTION": "ก๊าซชีวภาพ",
             "LANDFILL": "ฝังกลบ"}


def true_lift(pct: float) -> float:
    return float(np.interp(min(max(pct, 0.0), 50.0), list(TRUE_LIFT), list(TRUE_LIFT.values())))


def kg_per_unit(p: dict) -> float:
    size, unit = p.get("net_content_value"), str(p.get("net_content_unit") or "").upper()
    return float(size) * (1000 if unit in ("KG", "L") else 1) / 1000 if size else 0.0


# ---------------------------------------------------------------- lot / ถัง / บัญชี
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
    status: str = "IDLE"            # นโยบาย 3: IDLE (รอสแกน) / PROCESSING (สแกนแล้วรอ Optimizer) / CHECKED (มี task)
    eol_partner: str | None = None  # นโยบาย 3: ของที่เหลือตอนหมดอายุคืนนี้ไป partner นี้ (decision END_OF_LIFE)
    scans: int = 0                  # นโยบาย 3: ถูกสแกนกี่ครั้ง
    deferrals: int = 0              # นโยบาย 3: ได้แผนกำจัดชั่วคราว (ไม่มี decision) กี่วัน

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

    def units_out(self) -> int:
        """หน่วยที่ออกจากร้านแล้วทั้งหมด (ขาย / ครัว / กำจัด / วัตถุดิบครัวจากสต็อกปกติ) ใช้ตรวจว่าของไม่หายระหว่างทาง"""
        return sum(self.units.values()) + self.notes["kitchen_regular_stock_units"]


# ---------------------------------------------------------------- partner: ค่าเที่ยวและกติกาเรียกรถ
@dataclass
class PartnerRule:
    partner_id: str
    partner_type: str
    name: str
    categories: set
    pickup_days: set              # 1 = จันทร์ ... 7 = อาทิตย์
    trip_cost: float              # fixed + travel ต่อครั้ง (DONATION คิดแค่ fixed)
    handling: float               # ต่อ kg (DONATION ไม่มี)
    buyback: float                # ต่อ kg
    min_kg: float
    cap_kg: float
    mode: str = "DEDICATED"       # DEDICATED = เรียกทุกวันที่มีรอบรับและมีของ | BIN = รอถังถึงปริมาณที่คุ้ม
    expected_kg: float = 0.0      # BIN: ปริมาณที่คุ้มที่สุดภายในเพดานเวลา
    max_wait_days: float = math.inf


def max_pickup_gap(days) -> int:
    """ระยะห่างมากสุด (วัน) ระหว่างวันรับที่เรียงกันแบบวนสัปดาห์"""
    days = list(days)
    return max((b - a) % 7 or 7 for a, b in zip(days, days[1:] + days[:1]))


def calls_per_week(pickup_days, max_gap_days: float) -> int:
    """จำนวนครั้งที่ต้องเรียกรถต่อสัปดาห์น้อยที่สุด โดยระยะห่างระหว่างวันที่เรียกไม่เกินเพดาน (หรือระยะของตารางรับเอง)"""
    days = sorted(pickup_days)
    if not days:
        return 0
    limit = max(max_gap_days, max_pickup_gap(days))
    for n in range(1, len(days) + 1):
        if any(max_pickup_gap(combo) <= limit + EPS for combo in itertools.combinations(days, n)):
            return n
    return len(days)


def partner_rules(partners: list, kg_per_day: dict, disposal: str) -> dict:
    """ค่าเที่ยว / handling / buyback จากข้อมูล partner + โหมดถัง (สูตรเดียวกับ context._partner_mode ของ optimizer-update)"""
    out = {}
    for p in partners:
        if not p.get("is_active", True):
            continue
        ptype = p["partner_type"]
        fixed, travel = float(p.get("fixed_cost_per_trip") or 0), float(p.get("travel_cost_per_trip") or 0)
        cap = p.get("max_capacity_kg_per_pickup")
        r = PartnerRule(p["partner_id"], ptype, p.get("name", p["partner_id"]), set(p.get("accepted_categories") or []),
                        {int(x) for x in p.get("pickup_days") or []},
                        trip_cost=fixed if ptype == "DONATION" else fixed + travel,
                        handling=0.0 if ptype == "DONATION" else float(p.get("handling_fee_per_kg") or 0),
                        buyback=float(p.get("buyback_price_per_kg") or 0), min_kg=float(p.get("min_kg_per_pickup") or 0),
                        cap_kg=float(cap) if cap is not None else math.inf)
        if disposal == "bins":
            _bin_mode(r, kg_per_day)
        out[r.partner_id] = r
    return out


def _bin_mode(r: PartnerRule, kg_per_day: dict) -> None:
    daily = sum(kg_per_day.get(c, 0.0) for c in r.categories)
    if not r.pickup_days or daily <= 0:
        return                                                    # ไม่มีตารางรับ / ไม่มีประวัติของทิ้ง -> DEDICATED
    calls = calls_per_week(r.pickup_days, MAX_HOLD_DAYS) if r.trip_cost > 0 else len(r.pickup_days)
    economic = min(r.cap_kg, daily * 7.0 / calls)
    if economic <= 0 or economic + EPS < r.min_kg:
        r.expected_kg = economic                                  # ถังไม่ถึงขั้นต่ำภายในเพดานเวลา -> DEDICATED
        return
    r.mode, r.expected_kg = "BIN", economic
    r.max_wait_days = max(MAX_HOLD_DAYS, float(max_pickup_gap(sorted(r.pickup_days))))


# ---------------------------------------------------------------- โลก
class World:
    def __init__(self, start: date, days: int, disposal: str = "dedicated"):
        if disposal not in DISPOSAL_MODES:
            raise ValueError(f"disposal ต้องเป็น {DISPOSAL_MODES}")
        self.start, self.end, self.disposal = start, start + timedelta(days=days - 1), disposal
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

    @property
    def units_in_total(self) -> int:
        return sum(r[4] for r in self.initial) + sum(r[4] for rows in self.deliveries.values() for r in rows)

    def new_lot(self, row) -> Lot:
        uid, pid, rec, exp, qty = row
        p = self.products[pid]
        return Lot(uid, pid, rec, exp, qty, float(p["base_cost"]), float(p["regular_price"]), float(p["regular_price"]))

    def waste_history(self, d: date, days: int = 28) -> dict:
        """ของทิ้งเฉลี่ยต่อวันแยกหมวด (kg) ย้อนหลัง 28 วันถึงเมื่อวาน (สูตรเดียวกับ server ของ optimizer-update)"""
        part = self.pdy[(self.pdy.sale_date >= d - timedelta(days=days)) & (self.pdy.sale_date < d)]
        n = part.sale_date.nunique()
        kg = defaultdict(float)
        for r in part.itertuples():
            kg[self.products[r.product_id]["category"]] += r.waste_qty * self.kg[r.product_id]
        return {"from": (d - timedelta(days=days)).isoformat(), "to": (d - timedelta(days=1)).isoformat(),
                "days": n, "kg_per_day": {c: v / n for c, v in kg.items()} if n else {}}

    def rules(self, d: date) -> dict:
        """กติกาเรียกรถของแต่ละ partner วันนั้น (bins: ปริมาณที่คุ้มขึ้นกับของทิ้งเฉลี่ย 28 วันก่อนหน้า)"""
        return partner_rules(self.partners, self.waste_history(d)["kg_per_day"], self.disposal)

    def partner_type(self, pid: str) -> str:
        return next(p["partner_type"] for p in self.partners if p["partner_id"] == pid)


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


def run_pickups(bins: dict, rules: dict, d: date, led: Ledger, flush: bool = False) -> None:
    """เรียกรถตามกติกา: วันที่ partner มีรอบรับ, DEDICATED เรียกทุกครั้งที่มีของ, BIN เรียกเมื่อถังถึงปริมาณที่คุ้ม
    หรือรอรอบหน้าแล้วจะเกินเพดานเวลา, flush = ปิดรอบ backtest เก็บถังที่เหลือ"""
    for pid, b in bins.items():
        if not b.items:
            continue
        r = rules[pid]
        if not flush and d.isoweekday() not in r.pickup_days:
            continue
        kg = b.kg
        call = flush or r.mode == "DEDICATED"
        if not call:
            nxt = next(d + timedelta(days=i) for i in range(1, 8) if (d + timedelta(days=i)).isoweekday() in r.pickup_days)
            oldest = min(t for _, t in b.items)
            call = kg >= r.expected_kg - EPS or (nxt - oldest).days > r.max_wait_days + EPS
        if call:
            led.money["trip_fee"] += r.trip_cost
            led.money["handling"] += r.handling * kg
            led.money["buyback"] += r.buyback * kg
            led.calls[pid] += 1
            led.calls_below_min += kg < r.min_kg - EPS
            b.items.clear()


def expire(world: World, lots: list, bins: dict, d: date, led: Ledger, auto_landfill: bool = True) -> None:
    """ปิดร้านวันหมดอายุ: ของที่เหลือไป partner ของ decision END_OF_LIFE
    auto_landfill=True (นโยบาย 1-2 และวิธีของ optimizer-update): ไม่มี decision = ทิ้ง landfill เอง
    auto_landfill=False (นโยบาย 3 แบบ main): ไม่มี decision = ของหมดอายุค้างในร้าน รอรอบสแกนพรุ่งนี้ออก decision ให้"""
    for l in lots:                                  # <= : ของที่หมดอายุก่อนวันนี้ (มีได้ใน one-shot) ก็ทิ้งด้วย
        if l.expiry <= d and l.qty > 0 and (l.eol_partner or auto_landfill):
            pid = l.eol_partner or LANDFILL
            to_bin(world, bins, pid, l, l.qty, d, led, world.partner_type(pid))


def end_of_day_pickups(bins: dict, rules: dict, d: date, led: Ledger, world: World, lots: list,
                       auto_landfill: bool = True) -> None:
    """ลำดับหลังขาย: bins = เรียกรถก่อนแล้วของหมดอายุคืนนี้เข้าถังรอรอบหน้า (เหมือน backtest 22 ต.ค.)
    dedicated = ของหมดอายุคืนนี้เข้าที่พักก่อน แล้วรถรอบเย็นเก็บทั้งหมดวันเดียวกัน (decision วันนี้ = รถมาวันนี้)"""
    if world.disposal == "bins":
        run_pickups(bins, rules, d, led)
        expire(world, lots, bins, d, led, auto_landfill)
    else:
        expire(world, lots, bins, d, led, auto_landfill)
        run_pickups(bins, rules, d, led)


# ---------------------------------------------------------------- นโยบาย 1, 2
# ส่วนลดตามวันที่เหลือขาย (>= 3 วัน, 2 วัน, 1 วัน, วันสุดท้าย) ช่วงตามที่ทีมกำหนด: 0-10 / 10-20 / 20-30 / 30-50%
FIXED_RULES = {"ต่ำ": (0, 10, 20, 30), "กลาง": (5, 15, 25, 40), "สูง": (10, 20, 30, 50)}


def apply_fixed_rule(world: World, lots: list, d: date, discounts: tuple) -> None:
    """ตั้งราคาตามจำนวนวันที่เหลือขาย (ไม่ต่ำกว่า min_allowed_price)"""
    for l in lots:
        if l.qty <= 0 or l.received > d or l.expiry < d:
            continue
        left = (l.expiry - d).days
        pct = discounts[0] if left >= 3 else discounts[1] if left == 2 else discounts[2] if left == 1 else discounts[3]
        price = round(l.regular * (1 - pct / 100), 2)
        floor = world.products[l.product_id].get("min_allowed_price")
        l.price = max(price, float(floor)) if floor is not None else price


def run_rule_policy(world: World, name: str, discounts: tuple | None) -> Ledger:
    led = Ledger(name)
    lots = [world.new_lot(r) for r in world.initial]
    bins = defaultdict(Bin)
    d, rules = world.start, None
    while d <= world.end:
        lots += [world.new_lot(r) for r in world.deliveries.get(d, [])]
        rules = world.rules(d)
        if discounts:
            apply_fixed_rule(world, lots, d, discounts)
        sell(world, lots, d, led)
        end_of_day_pickups(bins, rules, d, led, world, lots)
        lots = [l for l in lots if l.qty > 0 and l.expiry > d]
        led.daily.append(round(led.net, 2))
        d += timedelta(days=1)
    run_pickups(bins, rules, d, led, flush=True)
    led.daily[-1] = round(led.net, 2)
    led.notes["ending_units"] = sum(l.qty for l in lots)
    led.notes["ending_cost"] = round(sum(l.qty * l.cost for l in lots), 2)
    check_conservation(world, led, lots)
    return led


def check_conservation(world: World, led: Ledger, lots: list) -> None:
    """ของเข้า = ออก (ขาย / ครัว / กำจัด) + คงเหลือ ถ้าไม่เท่าแปลว่ามีของหาย / งอกระหว่างจำลอง"""
    stock = sum(l.qty for l in lots if l.qty > 0)
    if world.units_in_total != led.units_out() + stock:
        raise AssertionError(f"{led.name}: ของเข้า {world.units_in_total} != ออก {led.units_out()} + คงเหลือ {stock}")
