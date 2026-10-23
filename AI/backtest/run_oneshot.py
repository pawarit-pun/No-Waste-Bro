"""กดรันครั้งเดียว วันเดียวจบ (one-shot) บน optimizer-update: lot ทั้ง 27 ของ demo วันที่ 2026-10-16

เหมือนกดปุ่ม Run demo 1 ครั้งตอนเปิดร้าน 08:00 แล้วดูว่าปิดร้านคืนนั้นในร้านเหลืออะไร:
  SCAN (Forecaster ตัวจริง + Risk Scanner) -> OPTIMIZE -> ทำตาม decision ทุกตัว (อนุมัติ 100%) -> ขาย 1 วัน -> ปิดร้าน
ไม่มีของเข้าร้าน ไม่มีรอบสแกนพรุ่งนี้ ไม่มีของในถัง partner จากวันอื่น (เหมือน demo_reset)

นโยบาย (lot ชุดเดียวกัน ลูกค้าชุดเดียวกัน):
  1  ร้านแบบเดิม             ขายราคาปกติ ของหมดอายุคืนนี้ทิ้ง landfill
  2  ลดราคาตามกฎตายตัว        ตามวันที่เหลือขาย (FIXED_RULES ของ run_backtest) เลือกช่วงที่กำไรวันนี้ดีที่สุด
  3A Optimizer ตามโค้ดจริง     ค่าเริ่มต้นของ optimizer-update: partner โหมด BIN / DEDICATED จาก waste_history 28 วัน,
                             แผนชั่วคราว (lot คืน IDLE ไม่มี task), ของเหลือจากการลดราคารอรอบหน้า
  3B Optimizer โหมดวันเดียว    ข้อมูลเดียวกันแต่ไม่ส่ง waste_history -> partner ทุกรายเป็น DEDICATED (เรียกรถเฉพาะ
                             จ่ายค่าเที่ยวเต็ม) จึงไม่มีแผนชั่วคราว ตัดสินใจ lot เสี่ยงให้จบในรอบนี้

ลูกค้า: mock_v3 จบ 15 ต.ค. ไม่มี latent_demand ของ 16 ต.ค. -> ค่าเฉลี่ยวันเดียวกันของ 4 สัปดาห์ก่อน (ไม่ใช่ค่าที่ Forecaster ทาย)
  การขาย / ลดราคา / ลำดับหยิบ lot ใช้ sell() ของ run_backtest (TRUE_LIFT, 40% หยิบ lot ใหม่สุด, ที่เหลือ FIFO)

ค่ารถ partner คิด 2 แบบ:
  A เรียกรถเฉพาะ (one-shot)   ทุก (partner, วันรับ) ที่มีของ = ค่าเที่ยวเต็ม 1 ครั้ง + handling - buyback   <- ใช้ในกำไรหลัก
  B เฉลี่ยต่อ kg แบบถัง (BIN)  ค่าเที่ยว / ปริมาณที่คุ้ม x kg (สมมติฐานของ Optimizer: รถขนรวมกับของทิ้งวันอื่น)

กำไรสุทธิวันนี้ = รายได้ขาย + มูลค่าเมนูครัว (ค่าคาดหมายจากแผน) + buyback - ค่ารถ - handling
              - ต้นทุนของทุกชิ้นที่ออกจากร้าน (ขาย / ครัว / partner) - ต้นทุนของหมดอายุที่ยังค้างในร้าน (ขายไม่ได้แล้ว)
สต็อกที่ยังขายได้ตอนปิดร้านคิดที่ต้นทุน (ไม่กำไรไม่ขาดทุน) รายงานแยกมูลค่าราคาขายไว้

ผลวันเดียวลงโทษการดึงของออกก่อนหมดอายุ (ต้นทุนถูกนับวันนี้ ของร้านเดิมไปเสียหายวันหลัง) รายงานจึงจำลองต่อ
"ปล่อยจนทุก lot หมดอายุ" ด้วย: ไม่มีรอบสแกนเพิ่ม ไม่มีของเข้าร้าน ของหมดอายุที่มี decision END_OF_LIFE ไป partner ตามแผน
ที่ไม่มี decision ร้านทิ้งเอง (landfill นับแยก) ลูกค้า = เฉลี่ยวันเดียวกัน 4 สัปดาห์ล่าสุดที่มีข้อมูล

ใช้งาน (โฟลเดอร์ AI/backtest, Python ที่มี lightgbm + scipy เช่น server/.venv):
    python run_oneshot.py                  # ~1 นาที -> output/oneshot_2026-10-16.html + .json
    python run_oneshot.py --render-only    # สร้าง HTML ใหม่จาก JSON เดิม
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import math
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from run_backtest import (BKK, CSS, FIXED_RULES, HERE, LANDFILL, METHOD_TH, MOCK, Forecaster, Ledger, Lot,
                          OptimizerConfig, World, baht, handoff, load_reference, rf_config, risk, run_optimizer, sell,
                          signed)

DEMO_DATE = date(2026, 10, 16)
RUN_AT = time(8, 0)                                   # กดปุ่มตอนเปิดร้าน
SENSITIVITY_TIMES = tuple(time(h) for h in (8, 10, 12, 14, 16, 18, 20))
DEMAND_SCALES = (0.8, 1.0, 1.2)
STORE_CLOSE = time(22, 0)
ACTION_TH = {"MARKDOWN": "ลดราคา", "KITCHEN_REPURPOSE": "เข้าครัว", "DONATE": "บริจาค", "ANIMAL_FEED": "อาหารสัตว์",
             "COMPOST": "ปุ๋ยหมัก", "ANAEROBIC_DIGESTION": "ก๊าซชีวภาพ", "LANDFILL": "ฝังกลบ", "DISCARD": "ทิ้งเองในร้าน"}
METHOD_ALL = {**METHOD_TH, "DISCARD": "ทิ้งเองในร้าน", "KITCHEN_INGREDIENT": "วัตถุดิบรองของครัว"}
PARTNER_METHODS = ("DONATION", "ANIMAL_FEED", "COMPOSTING", "ANAEROBIC_DIGESTION", "LANDFILL", "DISCARD")
# ของที่ยังอยู่ในร้านตอนปิด -> (ชื่อ, มี task / แผนครอบแล้วหรือยัง, สี)
LEFT_CLASSES = {
    "EXPIRED_UNHANDLED": ("หมดอายุแล้ว ค้างในร้าน ไม่มี task", False, "#c0392b"),
    "MARKDOWN_LEFT": ("ติดป้ายลดราคาแล้วขายไม่หมด (lot ใหม่ IDLE รอรอบหน้า)", False, "#e67e22"),
    "PROVISIONAL": ("เสี่ยง · แผนชั่วคราว คืน IDLE รอรอบพรุ่งนี้", False, "#f0a35e"),
    "RELEASED": ("เสี่ยง · คาดว่าขายราคาปกติได้ คืน IDLE ไม่มี task", False, "#f6c48f"),
    "SKIPPED": ("ส่งต่อ Optimizer แต่ถูกข้าม", False, "#d9a7a0"),
    "NOT_AT_RISK": ("ไม่เสี่ยง (LOW / MEDIUM) ระบบไม่แตะ", False, "#c9b8a6"),
    "SELL_ON": ("ขายต่อตามปกติ (ร้านไม่มีระบบ AI)", False, "#c9b8a6"),
    "CHECKED_OTHER": ("มี task ส่วนอื่นแล้ว ส่วนนี้ขายต่อ", True, "#7fb77e"),
    "EOL_PLANNED": ("มี task: ขายต่อ แล้วส่ง partner ตอนหมดอายุ", True, "#4f9a5a"),
    "IN_BIN_WAITING": ("ดึงออก / ทิ้งแล้ว รอรถ partner วันอื่น", True, "#2f6f3e"),
}
AT_RISK_NO_TASK = ("EXPIRED_UNHANDLED", "MARKDOWN_LEFT", "PROVISIONAL", "RELEASED", "SKIPPED")
POLICY_TH = {"p1": "1 · ร้านแบบเดิม", "p2": "2 · ลดราคาตามกฎตายตัว", "p3a": "3A · Optimizer ตามโค้ดจริง",
             "p3b": "3B · Optimizer โหมดวันเดียว"}


def root(uid: str) -> str:
    """lot ต้นทาง (lot ที่แยกตอนติดป้ายลดราคาใช้ชื่อ <lot>~md)"""
    return uid.split("~")[0]


def ts(value) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def hhmm(value) -> str:
    if not value:
        return "-"
    t = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return t.astimezone(BKK).strftime("%d/%m %H:%M")


# ---------------------------------------------------------------- lot / ลูกค้า / Forecaster ของวัน demo
def demo_lots(world: World) -> tuple[list, dict]:
    df = pd.read_csv(MOCK / "inventory_lots_demo.csv")
    lots = [Lot(r.lot_id, r.product_id, date.fromisoformat(r.received_date), date.fromisoformat(r.expiration_date),
                int(r.current_quantity), float(r.unit_cost), float(r.current_selling_price),
                float(world.products[r.product_id]["regular_price"]))
            for r in df.itertuples() if r.current_quantity > 0]
    return lots, {r.lot_id: (r.location_aisle, r.location_shelf) for r in df.itertuples()}


def proxy_demand(world: World, d: date, weeks: int = 4) -> tuple[dict, list]:
    """ลูกค้าแทนของจริง: latent_demand เฉลี่ยของวันเดียวกันใน 4 สัปดาห์ล่าสุดที่มีข้อมูลจริง (mock_v3 จบ 15 ต.ค.)"""
    last_real = world.pdy.sale_date.max()
    first = d - timedelta(days=7 * math.ceil(max(1, (d - last_real).days) / 7))
    same = [first - timedelta(days=7 * i) for i in range(weeks)]
    out = {}
    for pid in world.products:
        vals = [world.demand[(pid, x)] for x in same if (pid, x) in world.demand]
        if vals:
            out[pid] = sum(vals) / len(vals)
    return out, same


def set_demand(world: World, d: date, proxy: dict, scale: float) -> None:
    for pid, v in proxy.items():
        world.demand[(pid, d)] = int(round(v * scale))


class DemoScanner:
    """Forecaster ตัวจริงในเครื่อง (เทรนถึง 15 ต.ค. เหมือน run_scan.py) + Risk Scanner"""

    def __init__(self):
        self.fc = Forecaster.load()
        self.thresholds = rf_config.load_thresholds()
        ref_products, self.recipes = load_reference()
        self.products = {p["product_id"]: p for p in ref_products}
        self.prod_df = pd.DataFrame([{"product_id": p["product_id"], "category": p["category"],
                                      "shelf_life_days": p["shelf_life_days"]} for p in ref_products])
        self.pdy = pd.read_csv(MOCK / "product_daily.csv", dtype={"stockout_hour": "Int64"})
        self.ctx = pd.read_csv(MOCK / "daily_context.csv")

    def scan(self, lots: list, d: date) -> tuple[list, list, dict]:
        p = self.pdy
        keep = (p.sale_date >= (d - timedelta(days=rf_config.HISTORY_DAYS)).isoformat()) & (p.sale_date < d.isoformat())
        history = json.loads(p[keep].sort_values(["product_id", "sale_date"]).to_json(orient="records", force_ascii=False))
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
        mu = self.fc.predict_daily(history, ctx, self.prod_df, d, sorted(targets))
        demand = {(r.product_id, r.date.date()): float(r.mu) for r in mu.itertuples()}
        results = risk.assess(scan_lots, demand, self.fc.phi_for, d, self.thresholds, 0.0)
        recipe_rows = handoff.build(results, self.products, self.recipes, demand, self.fc.lifts, d, self.fc.phi_for)
        return results, recipe_rows, demand


def optimizer_inputs(world: World, lots: list, d: date, results: list, recipe_rows: list, locations: dict,
                     waste_history: dict) -> dict:
    """JSON แบบ GET /ai/optimize-inputs (days_ahead=1: ชั่วโมงครัววันนี้ + พรุ่งนี้, partner_bins ว่างเหมือนหลัง demo_reset)"""
    run_id = f"oneshot-{d.isoformat()}"
    by_uid = {l.uid: l for l in lots}
    at_risk = []
    for r in results:
        p = r["payload"]
        if p["risk_level"] not in rf_config.FORWARD_LEVELS:
            continue
        l = by_uid[p["lot_id"]]
        aisle, shelf = locations.get(l.uid, (None, None))
        at_risk.append({**{k: v for k, v in p.items() if k != "shelf"}, "assessment_id": f"{run_id}-{l.uid}",
                        "run_id": run_id, "shelf": p.get("shelf") or [],
                        "lot": {"lot_id": l.uid, "product_id": l.product_id, "current_quantity": l.qty,
                                "unit_cost": l.cost, "current_selling_price": l.price,
                                "expiration_date": l.expiry.isoformat(), "location_aisle": aisle,
                                "location_shelf": shelf, "ai_status": "PROCESSING"}})
    ingredient_ids = sorted({i["ingredient_product_id"] for r in world.recipes for i in r["ingredients"]})
    stock = [{"product_id": pid, "lots": [{"lot_id": l.uid, "current_quantity": l.qty, "expiration_date": l.expiry.isoformat()}
                                          for l in sorted(lots, key=lambda l: (l.expiry, l.uid))
                                          if l.product_id == pid and l.qty > 0 and l.expiry >= d]}
             for pid in ingredient_ids]
    kitchen = [{**k, "capacity_date": (d + timedelta(days=i)).isoformat()} for i in (0, 1) for k in world.kitchen_rows]
    return {"reference_date": d.isoformat(), "run_id": run_id, "at_risk_lots": at_risk,
            "recipe_demand": [{**r, "run_id": run_id} for r in recipe_rows], "products": world.opt_products,
            "recipes": world.recipes, "kitchen_capacity": kitchen, "donation_partners": world.partners,
            "ingredient_stock": stock, "waste_history": waste_history, "partner_bins": []}


# ---------------------------------------------------------------- 1 วันของแต่ละนโยบาย
@dataclass
class DayState:
    key: str
    lots: list
    money: Counter = field(default_factory=Counter)
    trace: dict = field(default_factory=lambda: defaultdict(Counter))   # lot ต้นทาง -> ชิ้นต่อเหตุการณ์
    disposals: list = field(default_factory=list)                        # ของที่ส่ง partner / ทิ้ง
    eol_plan: dict = field(default_factory=dict)                         # lot -> (partner, เวลารับ, วิธี) ของที่เหลือตอนหมดอายุ


def fresh(base: list) -> list:
    return [copy.copy(l) for l in base]


def sell_day(world: World, st: DayState, d: date) -> None:
    before = {id(l): l.qty for l in st.lots}
    sell(world, st.lots, d, Ledger(st.key))
    for l in st.lots:
        n = before[id(l)] - l.qty
        if n <= 0:
            continue
        md = l.disc > 0.5
        st.money["revenue_md" if md else "revenue_full"] += n * l.price
        st.money["discount_given"] += n * (l.regular - l.price) if md else 0.0
        st.money["cogs_sold"] += n * l.cost
        st.trace[root(l.uid)]["sold_md" if md else "sold_full"] += n


def dispose(world: World, st: DayState, lot: Lot, n: int, partner_id, pickup, timing: str, method: str) -> None:
    n = min(int(n), lot.qty)
    if n <= 0:
        return
    lot.qty -= n
    kg = n * world.kg[lot.product_id]
    st.money["cogs_disposed"] += n * lot.cost
    st.trace[root(lot.uid)][method] += n
    st.disposals.append({"lot_id": root(lot.uid), "uid": lot.uid, "product_id": lot.product_id, "method": method,
                         "partner_id": partner_id, "units": n, "kg": kg, "cogs": n * lot.cost,
                         "retail": n * lot.regular, "expiry": lot.expiry, "pickup_at": pickup, "timing": timing})


def first_slot_after(partner, after: datetime) -> datetime:
    """รอบรับแรกของ partner ที่เริ่มหลังเวลานี้"""
    for i in range(0, 9):
        day = after.date() + timedelta(days=i)
        if day.isoweekday() in partner.pickup_days:
            start = datetime.combine(day, partner.t_start or time(0), tzinfo=BKK)
            if start >= after:
                return start
    raise ValueError(f"{partner.partner_id} ไม่มีรอบรับ")


def run_rule_day(world: World, base: list, d: date, key: str, pctx: dict, discounts: tuple | None = None) -> DayState:
    st = DayState(key, fresh(base))
    if discounts:
        for l in st.lots:
            if l.expiry < d:
                continue
            left = (l.expiry - d).days
            pct = discounts[0] if left >= 3 else discounts[1] if left == 2 else discounts[2] if left == 1 else discounts[3]
            price = round(l.regular * (1 - pct / 100), 2)
            floor = world.products[l.product_id].get("min_allowed_price")
            l.price = max(price, float(floor)) if floor is not None else price
    sell_day(world, st, d)
    pickup = first_slot_after(pctx[LANDFILL].partner, datetime.combine(d, STORE_CLOSE, tzinfo=BKK))
    for l in st.lots:                                  # ร้านทิ้งของหมดอายุ (รวม lot ที่หมดอายุไปแล้ว) ตอนปิดร้าน
        if l.qty > 0 and l.expiry <= d:
            dispose(world, st, l, l.qty, LANDFILL, pickup, "EXPIRED_TONIGHT", "LANDFILL")
    return st


def run_optimizer_day(world: World, base: list, d: date, key: str, res: dict) -> DayState:
    """ทำตามแผน: ติดป้ายลดราคา (แยก lot ใหม่), ครัว, ดึงออกส่ง partner, END_OF_LIFE (เฉพาะที่ไม่ใช่แผนชั่วคราว)"""
    st = DayState(key, fresh(base))
    by_uid = {l.uid: l for l in st.lots}
    plan = res["plan"]
    for lo in plan["lots"]:
        l = by_uid[lo["lot_id"]]
        eol, eol_at = Counter(), {}
        for p in lo["portions"]:
            m, det, n = p["method"], p["details"], p["units"]
            if m == "MARKDOWN" and n > 0:              # ติดป้ายทุกชิ้นบนชั้น -> lot ใหม่ราคาลด (IDLE)
                take = min(n, l.qty)
                l.qty -= take
                st.lots.append(Lot(f"{l.uid}~md", l.product_id, l.received, l.expiry, take, l.cost,
                                   float(det["unit_price"]), l.regular))
                st.trace[l.uid]["tagged_md"] += take
            elif m in ("KITCHEN", "KITCHEN_INGREDIENT"):
                take = min(n, l.qty)
                l.qty -= take
                st.money["cogs_kitchen"] += take * l.cost
                st.trace[l.uid]["kitchen"] += take
            elif det.get("partner_id") and det.get("timing") == "NOW":
                dispose(world, st, l, n, det["partner_id"], ts(det["pickup_at"]), "NOW", m)
            elif det.get("partner_id") and det.get("timing") == "END_OF_LIFE" and not det.get("provisional"):
                eol[det["partner_id"]] += n
                eol_at[det["partner_id"]] = (ts(det["pickup_at"]), m)
            elif m == "UNRESOLVED" and det.get("timing") != "END_OF_LIFE":
                dispose(world, st, l, n, None, None, "NOW", "DISCARD")
        if eol:
            pid = eol.most_common(1)[0][0]
            st.eol_plan[l.uid] = (pid, *eol_at[pid])
    for j in plan["kitchen_jobs"]:                     # มูลค่าเมนู (ค่าคาดหมาย) - ค่าไฟน้ำ - วัตถุดิบปกติ
        st.money["kitchen_value"] += (j["revenue_thb"] - j["utility_cost_thb"]
                                      - j["primary_from_regular_stock_thb"] + j["secondary_credit_thb"])
        st.money["kitchen_menu_revenue"] += j["revenue_thb"]
        for x in j["inputs"]:
            if x["role"] != "ANCHOR" and not x.get("at_risk") and x["lot_id"] in by_uid:
                src = by_uid[x["lot_id"]]
                take = min(src.qty, math.ceil(x["units"] - 1e-9))  # DB ตัดเป็นหน่วยเต็ม ต้นทุนอยู่ในมูลค่าเมนูแล้ว
                src.qty -= take
                st.trace[src.uid]["kitchen_ingredient"] += take
    sell_day(world, st, d)
    for l in st.lots:                                  # ปิดร้าน: ของที่หมดอายุคืนนี้ไป partner เฉพาะที่มี decision
        if l.qty > 0 and l.expiry <= d and l.uid in st.eol_plan:
            pid, at, method = st.eol_plan[l.uid]
            dispose(world, st, l, l.qty, pid, at, "END_OF_LIFE", method)
    return st


def continue_until_expiry(world: World, st: DayState, d: date, proxies: dict, pctx: dict,
                          discounts: tuple | None = None) -> date:
    """หลังวัน one-shot: ร้านขายต่อทุกวันจนทุก lot หมดอายุ ไม่มีรอบสแกน / decision ใหม่ ไม่มีของเข้าร้าน
    ของหมดอายุ: มี decision END_OF_LIFE -> partner ตามแผน, ไม่มี -> ร้านทิ้งเอง (landfill, นับแยกเป็น "ไม่มี task")"""
    day = d + timedelta(days=1)
    last = max([l.expiry for l in st.lots if l.qty > 0], default=d)
    while day <= last:
        set_demand(world, day, proxies[day], 1.0)
        if discounts:
            for l in st.lots:
                if l.qty > 0 and l.expiry >= day:
                    left = (l.expiry - day).days
                    pct = discounts[0] if left >= 3 else discounts[1] if left == 2 else discounts[2] if left == 1 else discounts[3]
                    price = round(l.regular * (1 - pct / 100), 2)
                    floor = world.products[l.product_id].get("min_allowed_price")
                    l.price = max(price, float(floor)) if floor is not None else price
        sell_day(world, st, day)
        close = datetime.combine(day, STORE_CLOSE, tzinfo=BKK)
        for l in st.lots:
            if l.qty <= 0 or l.expiry > day:
                continue
            if l.uid in st.eol_plan:
                pid, at, method = st.eol_plan[l.uid]
                dispose(world, st, l, l.qty, pid, max(at, close), "END_OF_LIFE", method)
            else:
                st.money["unplanned_units"] += l.qty
                st.money["unplanned_cogs"] += l.qty * l.cost
                st.trace[root(l.uid)]["unplanned"] += l.qty
                dispose(world, st, l, l.qty, LANDFILL, first_slot_after(pctx[LANDFILL].partner, close),
                        "STORE_THROWS", "LANDFILL")
        day += timedelta(days=1)
    return last


def horizon_summary(world: World, st: DayState, base: list, d: date, last: date, pctx: dict) -> dict:
    """ผลรวมตั้งแต่เช้าวัน one-shot จนทุก lot หมดอายุ (ทุกชิ้นออกจากร้านแล้ว)"""
    if any(l.qty > 0 for l in st.lots):
        raise AssertionError(f"{st.key}: ยังมีของเหลือหลังวันหมดอายุสุดท้าย")
    costs = disposal_costs(st, pctx, last)
    m = st.money
    gross = m["revenue_full"] + m["revenue_md"] + m["kitchen_value"]
    cogs = m["cogs_sold"] + m["cogs_kitchen"] + m["cogs_disposed"]
    units = Counter()
    for t in st.trace.values():
        units.update(t)
    net = lambda v: round(gross + v["buyback"] - v["trip"] - v["handling"] - cogs, 2)
    by_method = Counter()
    kg = Counter()
    for x in st.disposals:
        by_method[x["method"]] += x["units"]
        kg[x["method"]] += x["kg"]
    return {"days": (last - d).days + 1, "last_day": last.isoformat(), "net_profit": net(costs["a"]),
            "net_profit_bin": net(costs["b"]), "revenue_full": round(m["revenue_full"], 2),
            "revenue_md": round(m["revenue_md"], 2), "kitchen_value": round(m["kitchen_value"], 2),
            "disposal_a": costs["a"], "disposal_b": costs["b"], "calls": len(costs["trips"]),
            "calls_by_partner": dict(Counter(t["partner_id"] for t in costs["trips"])),
            "sold_full": units["sold_full"], "sold_md": units["sold_md"],
            "kitchen_units": units["kitchen"] + units["kitchen_ingredient"],
            "disposed_by_method": dict(by_method), "disposed_kg": round(sum(kg.values()), 2),
            "landfill_kg": round(kg["LANDFILL"], 2), "unplanned_units": int(m["unplanned_units"]),
            "unplanned_cogs": round(m["unplanned_cogs"], 2), "waste_cogs": round(m["cogs_disposed"], 2),
            "trace": {k: dict(v) for k, v in st.trace.items()}}


# ---------------------------------------------------------------- สรุปผลของวัน
def classify(st: DayState, d: date, opt: dict | None) -> list:
    """ของที่ยังอยู่ในร้านตอนปิด (บนชั้น + ถังที่รอรถวันอื่น) แยกประเภท"""
    rows = []
    plan_lots = released = provisional = skipped = set()
    if opt:
        plan = opt["result"]["plan"]
        plan_lots = {lo["lot_id"] for lo in plan["lots"]}
        released = set(opt["result"]["lots_to_release"])
        provisional = {lo["lot_id"] for lo in plan["lots"] if any(p["details"].get("provisional") for p in lo["portions"])}
        skipped = set(plan["skipped_lots"])
    for l in st.lots:
        if l.qty <= 0:
            continue
        r = root(l.uid)
        if l.expiry <= d:
            c = "EXPIRED_UNHANDLED"
        elif opt is None:
            c = "SELL_ON"
        elif l.uid != r:
            c = "MARKDOWN_LEFT"
        elif r in skipped:
            c = "SKIPPED"
        elif r not in plan_lots:
            c = "NOT_AT_RISK"
        elif r in st.eol_plan:
            c = "EOL_PLANNED"
        elif r in released:
            c = "PROVISIONAL" if r in provisional else "RELEASED"
        else:
            c = "CHECKED_OTHER"
        rows.append({"lot_id": r, "uid": l.uid, "product_id": l.product_id, "class": c, "units": l.qty,
                     "expiry": l.expiry.isoformat(), "days_left": (l.expiry - d).days, "price": l.price,
                     "cost": round(l.qty * l.cost, 2), "retail_now": round(l.qty * l.price, 2),
                     "retail_regular": round(l.qty * l.regular, 2), "on_shelf": True})
    for x in st.disposals:
        if x["pickup_at"] and x["pickup_at"].date() > d:
            rows.append({"lot_id": x["lot_id"], "uid": x["uid"], "product_id": x["product_id"], "class": "IN_BIN_WAITING",
                         "units": x["units"], "expiry": None, "days_left": None, "price": None,
                         "cost": round(x["cogs"], 2), "retail_now": 0.0, "retail_regular": 0.0, "on_shelf": False,
                         "partner_id": x["partner_id"], "pickup_at": x["pickup_at"].isoformat(), "kg": round(x["kg"], 3)})
    return rows


def disposal_costs(st: DayState, pctx: dict, d: date) -> dict:
    """A = เรียกรถเฉพาะ 1 ครั้งต่อ (partner, วันรับ)
    B = โหมด BIN: ค่าเที่ยวเฉลี่ยต่อ kg แต่ไม่เกินค่าเรียกรถ 1 ครั้งต่อ (partner, วันรับ) (เพดานเที่ยวเต็มของ Optimizer)
        DEDICATED จ่ายเต็มเหมือน A"""
    groups = defaultdict(lambda: {"kg": 0.0, "units": 0, "lots": set(), "methods": set()})
    for x in st.disposals:
        if not x["partner_id"]:
            continue
        g = groups[(x["partner_id"], x["pickup_at"].date())]
        g["kg"] += x["kg"]
        g["units"] += x["units"]
        g["lots"].add(x["lot_id"])
        g["methods"].add(x["timing"])
    trips, a, b = [], Counter(), Counter()
    for (pid, day), g in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        pc = pctx[pid]
        handling, buyback = pc.handling * g["kg"], pc.partner.buyback * g["kg"]
        trip_b = min(pc.fee_per_kg * g["kg"], pc.trip_cost) if pc.mode == "BIN" else pc.trip_cost
        a.update({"trip": pc.trip_cost, "handling": handling, "buyback": buyback})
        b.update({"trip": trip_b, "handling": handling, "buyback": buyback})
        trips.append({"partner_id": pid, "partner_type": pc.partner.partner_type, "pickup_date": day.isoformat(),
                      "picked_up_today": day <= d, "kg": round(g["kg"], 3), "units": g["units"], "lots": sorted(g["lots"]),
                      "timing": sorted(g["methods"]), "min_kg": pc.min_kg, "capacity_kg": pc.cap_kg,
                      "below_min": g["kg"] < pc.min_kg - 1e-9, "mode_in_optimizer": pc.mode,
                      "trip_cost_a": round(pc.trip_cost, 2), "trip_cost_b": round(trip_b, 2),
                      "fee_per_kg": round(pc.fee_per_kg, 2), "handling": round(handling, 2), "buyback": round(buyback, 2),
                      "net_a": round(buyback - handling - pc.trip_cost, 2), "net_b": round(buyback - handling - trip_b, 2)})
    return {"trips": trips, "a": {k: round(v, 2) for k, v in a.items()}, "b": {k: round(v, 2) for k, v in b.items()}}


def summarize_day(world: World, st: DayState, base: list, d: date, pctx: dict, opt: dict | None = None) -> dict:
    left = classify(st, d, opt)
    costs = disposal_costs(st, pctx, d)
    m = st.money
    on_shelf = [r for r in left if r["on_shelf"]]
    expired = [r for r in on_shelf if r["class"] == "EXPIRED_UNHANDLED"]
    write_off = round(sum(r["cost"] for r in expired), 2)
    units = Counter()
    for t in st.trace.values():
        units.update(t)
    units_in = sum(l.qty for l in base)
    units_out = (units["sold_full"] + units["sold_md"] + units["kitchen"] + units["kitchen_ingredient"]
                 + sum(units[k] for k in PARTNER_METHODS))
    if units_in != units_out + sum(r["units"] for r in on_shelf):   # ของไม่หาย / ไม่งอกระหว่างวัน
        raise AssertionError(f"{st.key}: ของเช้า {units_in} != ออก {units_out} + คงเหลือ {sum(r['units'] for r in on_shelf)}")
    cogs_out = m["cogs_sold"] + m["cogs_kitchen"] + m["cogs_disposed"]
    gross = m["revenue_full"] + m["revenue_md"] + m["kitchen_value"]

    def net(v):
        return round(gross + v["buyback"] - v["trip"] - v["handling"] - cogs_out - write_off, 2)

    by_class = defaultdict(lambda: {"units": 0, "cost": 0.0, "retail_now": 0.0, "retail_regular": 0.0, "lots": set()})
    for r in left:
        c = by_class[r["class"]]
        c["units"] += r["units"]
        c["cost"] += r["cost"]
        c["retail_now"] += r["retail_now"]
        c["retail_regular"] += r["retail_regular"]
        c["lots"].add(r["lot_id"])
    by_class = {k: {"units": v["units"], "cost": round(v["cost"], 2), "retail_now": round(v["retail_now"], 2),
                    "retail_regular": round(v["retail_regular"], 2), "lots": len(v["lots"])} for k, v in by_class.items()}
    no_task = [r for r in left if not LEFT_CLASSES[r["class"]][1]]
    risk_no_task = [r for r in left if r["class"] in AT_RISK_NO_TASK]
    ldf = pctx[LANDFILL]
    expired_kg = sum(r["units"] * world.kg[r["product_id"]] for r in expired)
    early = defaultdict(lambda: {"units": 0, "cogs": 0.0, "retail": 0.0, "kg": 0.0, "methods": set()})
    for x in st.disposals:                             # ดึงออกจากชั้นทั้งที่ยังขายได้ (หมดอายุวันอื่น)
        if x["timing"] == "NOW" and x["expiry"] > d:
            r = early[x["lot_id"]]
            r["units"] += x["units"]
            r["cogs"] += x["cogs"]
            r["retail"] += x["retail"]
            r["kg"] += x["kg"]
            r["methods"].add(x["method"])
    early = {k: {"units": v["units"], "cogs": round(v["cogs"], 2), "retail": round(v["retail"], 2),
                 "kg": round(v["kg"], 3), "methods": sorted(v["methods"])} for k, v in early.items()}
    return {
        "key": st.key, "net_profit": net(costs["a"]), "net_profit_bin": net(costs["b"]),
        "revenue_full": round(m["revenue_full"], 2), "revenue_md": round(m["revenue_md"], 2),
        "revenue": round(m["revenue_full"] + m["revenue_md"], 2), "discount_given": round(m["discount_given"], 2),
        "kitchen_value": round(m["kitchen_value"], 2), "kitchen_menu_revenue": round(m["kitchen_menu_revenue"], 2),
        "cogs_sold": round(m["cogs_sold"], 2), "cogs_kitchen": round(m["cogs_kitchen"], 2),
        "cogs_disposed": round(m["cogs_disposed"], 2), "write_off_expired": write_off,
        "disposal_a": costs["a"], "disposal_b": costs["b"], "trips": costs["trips"],
        "units_in": units_in, "cost_in": round(sum(l.qty * l.cost for l in base), 2),
        "units": {k: int(v) for k, v in units.items()},
        "sold_units": units["sold_full"] + units["sold_md"], "kitchen_units": units["kitchen"] + units["kitchen_ingredient"],
        "disposed_units": sum(units[k] for k in PARTNER_METHODS),
        "disposed_kg": round(sum(x["kg"] for x in st.disposals), 3),
        "left": left, "left_by_class": by_class,
        "left_units": sum(r["units"] for r in left), "left_on_shelf_units": sum(r["units"] for r in on_shelf),
        "left_cost": round(sum(r["cost"] for r in left), 2),
        "left_retail_now": round(sum(r["retail_now"] for r in on_shelf), 2),
        "left_retail_regular": round(sum(r["retail_regular"] for r in on_shelf), 2),
        "no_task_units": sum(r["units"] for r in no_task), "no_task_cost": round(sum(r["cost"] for r in no_task), 2),
        "risk_no_task_units": sum(r["units"] for r in risk_no_task),
        "risk_no_task_cost": round(sum(r["cost"] for r in risk_no_task), 2),
        "risk_no_task_lots": len({r["lot_id"] for r in risk_no_task}),
        "expired_left_units": sum(r["units"] for r in expired), "expired_left_lots": len({r["lot_id"] for r in expired}),
        "expired_left_kg": round(expired_kg, 3),
        "expired_left_disposal_estimate": round(ldf.trip_cost + ldf.handling * expired_kg, 2) if expired else 0.0,
        "early_removals": early, "early_removal_cogs": round(sum(v["cogs"] for v in early.values()), 2),
        "early_removal_units": sum(v["units"] for v in early.values()),
        "trace": {k: dict(v) for k, v in st.trace.items()},
    }


# ---------------------------------------------------------------- มุมมองของ Optimizer สำหรับรายงาน
def optimizer_view(res: dict, names: dict) -> dict:
    plan = res["plan"]
    by_assessment = {lo["assessment_id"]: lo for lo in plan["lots"]}
    decisions = []
    for x in res["payload"]["decisions"]:
        lo = by_assessment[x["assessment_id"]]
        decisions.append({"lot_id": lo["lot_id"], "name": lo["name"], "risk": lo["risk_level"],
                          "days_to_expiry": lo["days_to_expiry"], "action": x["action_type"],
                          "quantity": x["action_quantity"], "lot_quantity": lo["quantity"],
                          "discount_pct": x.get("discount_pct"), "price": x.get("new_recommended_price"),
                          "partner": x.get("target_partner_id"), "recipe": x.get("target_recipe_id"),
                          "batches": x.get("batch_count"), "due_by": x.get("due_by"),
                          "expected_thb": x["expected_profit_impact"], "score": x.get("decision_score")})
    provisional = [{"lot_id": lo["lot_id"], "name": lo["name"], "method": p["method"], "units": p["units"],
                    "kg": p["weight_kg"], "pickup_at": p["details"].get("pickup_at"), "mode": p["details"].get("mode"),
                    "net_thb": p["net_profit_thb"]}
                   for lo in plan["lots"] for p in lo["portions"] if p["details"].get("provisional") and p["units"] > 0]
    lots = []
    for lo in plan["lots"]:
        parts = []
        for p in lo["portions"]:
            det = p["details"]
            extra = (f" @{det['unit_price']:,.2f}" if p["method"] in ("SELL_REGULAR", "MARKDOWN") else
                     f" → {det.get('partner_id')} {hhmm(det.get('pickup_at'))}" if det.get("partner_id") else
                     f" {det.get('recipe_id')}" if det.get("recipe_id") else "")
            tag = " (ชั่วคราว)" if det.get("provisional") else ""
            parts.append(f"{METHOD_ALL.get(p['method'], p['method'])} {p['units']}{extra}{tag}")
        md = next((p for p in lo["portions"] if p["method"] == "MARKDOWN"), None)
        lots.append({"lot_id": lo["lot_id"], "name": lo["name"], "quantity": lo["quantity"], "risk": lo["risk_level"],
                     "days_to_expiry": lo["days_to_expiry"], "portions": parts, "net_thb": lo["net_profit_thb"],
                     "md_expected_leftover": md["details"]["expected_leftover"] if md else None,
                     "excluded": {k: v for k, v in lo["explain"]["excluded"].items()},
                     "released": lo["lot_id"] in res["lots_to_release"]})
    return {"decisions": decisions, "provisional": provisional, "released": res["lots_to_release"], "lots": lots,
            "trips": plan["trips"], "partner_bins": plan["partner_bins"], "kitchen_jobs": plan["kitchen_jobs"],
            "kitchen_usage": plan["kitchen_usage"], "summary": plan["summary"], "baselines": plan.get("baselines") or {},
            "warnings": plan["warnings"], "skipped": plan["skipped_lots"], "solver": plan["solver"],
            "violations": res["violations"], "payload_errors": res["payload_errors"],
            "action_counts": dict(Counter(x["action"] for x in decisions))}


def plan_brief(res: dict) -> dict:
    plan = res["plan"]
    acts = Counter(x["action_type"] for x in res["payload"]["decisions"])
    units = Counter()
    for lo in plan["lots"]:
        for p in lo["portions"]:
            units[p["method"]] += p["units"]
    return {"decisions": len(res["payload"]["decisions"]), "actions": dict(acts),
            "expected_net": plan["summary"]["net_profit_thb"],
            "provisional_lots": len({lo["lot_id"] for lo in plan["lots"]
                                     if any(p["details"].get("provisional") for p in lo["portions"])}),
            "released_lots": len(res["lots_to_release"]), "kitchen_jobs": len(plan["kitchen_jobs"]),
            "markdown_units": units["MARKDOWN"], "sell_regular_units": units["SELL_REGULAR"],
            "partner_units": sum(units[k] for k in ("DONATION", "ANIMAL_FEED", "COMPOSTING", "ANAEROBIC_DIGESTION", "LANDFILL")),
            "unresolved_units": units["UNRESOLVED"], "violations": len(res["violations"]) + len(res["payload_errors"]),
            "warnings_a2": sum(w.startswith("A2_") for w in plan["warnings"])}


# ---------------------------------------------------------------- รายงาน HTML
EXTRA_CSS = """
.page{max-width:1320px}
.kpis{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.scroll{overflow-x:auto;border-radius:14px;box-shadow:0 1px 3px rgba(120,70,20,.14);background:var(--card);margin-bottom:14px}
.scroll table{box-shadow:none;border-radius:0;min-width:640px}
td.num-neg{color:var(--bad)} .muted{color:var(--muted)} .small{font-size:13px}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700;color:#fff;white-space:nowrap}
.stack{display:flex;height:38px;border-radius:9px;overflow:hidden;background:var(--soft);margin:4px 0 14px}
.stack div{display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff;
  white-space:nowrap;overflow:hidden;min-width:2px}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:13px;margin:6px 0 16px}
.legend span{display:inline-flex;align-items:center;gap:6px} .legend i{width:12px;height:12px;border-radius:3px;display:inline-block}
.find{background:#fff;border-left:6px solid var(--accent);border-radius:12px;padding:14px 20px;margin:16px 0;
  box-shadow:0 1px 3px rgba(120,70,20,.14);line-height:1.75}
.find h3{margin:0 0 6px;color:var(--accent-dark);font-size:17px} .find ol{margin:0;padding-left:22px}
details{background:#fff;border-radius:12px;padding:10px 16px;margin:10px 0;box-shadow:0 1px 3px rgba(120,70,20,.14)}
summary{cursor:pointer;font-weight:700;color:var(--accent-dark)}
tr.sub td{background:#fffaf4;font-size:13px} tr.total td{font-weight:700;background:var(--soft2)}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 0} .toc a{background:#fff;border-radius:999px;padding:5px 12px;
  font-size:13px;color:var(--accent-dark);text-decoration:none;box-shadow:0 1px 2px rgba(120,70,20,.12)}
@media (max-width:860px){.page{padding:18px 16px}.kpis{grid-template-columns:1fr 1fr}.two,.three{grid-template-columns:1fr}
  h1{font-size:23px}.kpi-value{font-size:23px}}
"""


class Raw(str):
    """เซลล์ที่เป็น HTML แล้ว (ไม่ escape)"""


def cell(v, left: bool = False, neg: bool = False) -> str:
    cls = " class='l'" if left else (" class='num-neg'" if neg else "")
    return f"<td{cls}>{v if isinstance(v, Raw) else html.escape(str(v))}</td>"


def table(head: list, rows: list, left: int = 1, row_cls: list | None = None) -> str:
    """left = จำนวนคอลัมน์ซ้ายที่เป็นข้อความ (ชิดซ้าย)"""
    th = "".join(f"<th{' class=l' if i < left else ''}>{html.escape(h)}</th>" for i, h in enumerate(head))
    body = "".join(f"<tr{f' class={row_cls[i]}' if row_cls and row_cls[i] else ''}>"
                   + "".join(cell(v, j < left) for j, v in enumerate(r)) + "</tr>" for i, r in enumerate(rows))
    if not rows:
        body = f"<tr><td class='l muted' colspan={len(head)}>ไม่มี</td></tr>"
    return f"<div class='scroll'><table><tr>{th}</tr>{body}</table></div>"


def b2(x) -> str:
    return "-" if x is None else f"{x:,.2f}"


def badge(cls_key: str) -> Raw:
    label, _, color = LEFT_CLASSES[cls_key]
    return Raw(f"<span class='badge' style='background:{color}'>{html.escape(label)}</span>")


def stack(p: dict) -> str:
    total = p["units_in"]
    order = ["SOLD", "KITCHEN", "PICKED"] + list(LEFT_CLASSES)
    seg = {"SOLD": (p["sold_units"], "ขายได้", "#8a5a2b"), "KITCHEN": (p["kitchen_units"], "เข้าครัว", "#b07a3f"),
           "PICKED": (p["disposed_units"] - p["left_by_class"].get("IN_BIN_WAITING", {}).get("units", 0),
                      "partner รับไปแล้ววันนี้", "#5d8aa8")}
    for k, (label, _, color) in LEFT_CLASSES.items():
        seg[k] = (p["left_by_class"].get(k, {}).get("units", 0), label, color)
    parts = []
    for k in order:
        n, label, color = seg[k]
        if n > 0:
            w = n / total * 100
            parts.append(f"<div style='width:{w:.2f}%;background:{color}' title='{html.escape(label)}: {n:,} ชิ้น'>"
                         f"{f'{n:,}' if w >= 4 else ''}</div>")
    return f"<div class='stack'>{''.join(parts)}</div>"


def legend() -> str:
    items = [("ขายได้", "#8a5a2b"), ("เข้าครัว", "#b07a3f"), ("partner รับไปแล้ววันนี้", "#5d8aa8")]
    items += [(v[0], v[2]) for v in LEFT_CLASSES.values()]
    return "<div class='legend'>" + "".join(f"<span><i style='background:{c}'></i>{html.escape(t)}</span>"
                                            for t, c in items) + "</div>"


def render_html(res: dict) -> str:
    e = html.escape
    P = res["policies"]
    p1, p2, a, b = P["p1"], P["p2"], P["p3a"], P["p3b"]
    order = [("p1", p1), ("p2", p2), ("p3a", a), ("p3b", b)]
    pname = lambda k: POLICY_TH[k] + (f" (ช่วง{res['policy2_variant']})" if k == "p2" else "")
    names, scan = res["names"], res["scan"]
    va, vb = res["optimizer"]["p3a"], res["optimizer"]["p3b"]

    def kpi(label, value, sub="", tone=""):
        return (f'<div class="kpi {tone}"><div class="kpi-label">{e(label)}</div>'
                f'<div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>')

    # ---- ข้อค้นพบหลัก (คำนวณจากผล)
    u = lambda p, k: p["left_by_class"].get(k, {}).get("units", 0)
    H = res["horizon"]
    ldf = next(x for x in res["partners"] if x["partner_id"] == LANDFILL)
    expired_lots = lambda p: ", ".join(sorted({f"{r['lot_id']} {names[r['product_id']]} ({scan['lots'][r['lot_id']]['risk_level']})"
                                               for r in p["left"] if r["class"] == "EXPIRED_UNHANDLED"})) or "ไม่มี"
    s08, s_last = res["time_sensitivity"][0], res["time_sensitivity"][-1]
    findings = [
        f"<b>กำไรวันนี้วันเดียว</b> (ค่ารถเรียกเฉพาะ): ร้านเดิม {baht(p1['net_profit'])} · กฎตายตัว {baht(p2['net_profit'])} · "
        f"3A <b>{baht(a['net_profit'])}</b> · 3B {baht(b['net_profit'])} บาท · 3A ดูแย่สุดเพราะ<b>ดึงของที่ยังขายได้ออกวันนี้</b> "
        f"{a['early_removal_units']:,} ชิ้น (ต้นทุน {baht(a['early_removal_cogs'])} บาท) ต้นทุนนี้ถูกนับทันที "
        f"ส่วนร้านเดิมเก็บของชุดเดียวกันไว้เป็นสต็อกที่ราคาทุน ความเสียหายของร้านเดิมจึงไปเกิดในวันถัด ๆ ไป ซึ่งอยู่นอกกรอบวันเดียว",
        f"<b>ถ้าปล่อยต่อจนทุก lot หมดอายุ</b> ({H['p1']['last_day']}, ไม่มีรอบสแกนเพิ่ม): ร้านเดิม {baht(H['p1']['net_profit'])} · "
        f"กฎตายตัว {baht(H['p2']['net_profit'])} · 3A <b>{baht(H['p3a']['net_profit'])}</b> · 3B {baht(H['p3b']['net_profit'])} บาท "
        f"→ 3A ดีกว่าร้านเดิม <b>{signed(H['p3a']['net_profit'] - H['p1']['net_profit'])} บาท</b> "
        f"(ตัวเลขบนจอ demo วันเดียวจะไม่เห็นข้อนี้)",
        f"ปิดร้านคืนนี้ 3A ยังมีของในร้าน <b>{a['left_units']:,} ชิ้น</b> (ต้นทุน {baht(a['left_cost'])} บาท) จากของเช้า "
        f"{a['units_in']:,} ชิ้น ในนั้น <b>{a['no_task_units']:,} ชิ้นไม่มี task ครอบ</b> "
        f"({a['no_task_units'] / a['units_in'] * 100:.1f}%) ส่วนใหญ่เป็น lot ที่ไม่เสี่ยง ({u(a, 'NOT_AT_RISK'):,} ชิ้น) "
        f"ที่เหลือมี task แล้ว: ขายต่อแล้วส่ง partner ตอนหมดอายุ {u(a, 'EOL_PLANNED'):,} · รอรถ {u(a, 'IN_BIN_WAITING'):,}",
        f"<b>lot เสี่ยงที่ไม่มี task</b> 3A {a['risk_no_task_units']:,} ชิ้น ({a['risk_no_task_lots']} lot, ต้นทุน "
        f"{baht(a['risk_no_task_cost'])} บาท) = ป้ายลดราคาขายไม่หมด {u(a, 'MARKDOWN_LEFT'):,} + หมดอายุค้างร้าน "
        f"{u(a, 'EXPIRED_UNHANDLED'):,} + แผนชั่วคราว {u(a, 'PROVISIONAL'):,} + คืน IDLE {u(a, 'RELEASED'):,} · "
        f"3B {b['risk_no_task_units']:,} ชิ้น (ป้ายลดราคาขายไม่หมด {u(b, 'MARKDOWN_LEFT'):,}) ระบบจริงรอรอบสแกนพรุ่งนี้ "
        f"แต่ one-shot ไม่มีพรุ่งนี้",
        f"<b>ของหมดอายุค้างร้านคืนนี้</b> 3A {a['expired_left_units']} ชิ้น: {e(expired_lots(a))} · 3B {b['expired_left_units']} ชิ้น: "
        f"{e(expired_lots(b))} · Risk Scanner ให้ระดับ MEDIUM จึงไม่ส่งต่อ Optimizer ของที่ขายไม่หมดจึงไม่มีใครมีแผนจัดการ "
        f"(ร้านเดิม / กฎตายตัวทิ้งเองตอนปิดร้านตามนิสัย จึงเป็น 0) · ใน 3B แย่ลงอีกเพราะ Optimizer ลดราคา lot สินค้าเดียวกัน "
        f"ลูกค้าหยิบของลดราคาก่อน lot ที่หมดอายุวันนี้จึงขายไม่ออก (ดูหัวข้อ \"ทุก lot\")",
        (f"3A <b>ไม่มีแผนชั่วคราวเลย</b>ในข้อมูลนี้: ของทิ้งในประวัติแค่ {ldf['daily_kg']:.2f} kg/วัน → ปริมาณที่คุ้มของถังฝังกลบ "
         f"{ldf['economic_kg']:.1f} kg ค่ารถเฉลี่ย {ldf['fee_per_kg']:.0f} บาท/kg ทุก lot ที่ขายราคาปกติแล้วหมดอายุวันอื่น "
         f"มีของเหลือที่เข้าเที่ยวเต็ม (เกินปริมาณที่คุ้ม) หรือมี decision อื่นด้วย (ครัว / ดึงออก) จึงต้องออก decision รอบนี้ · "
         f"ค่า {ldf['fee_per_kg']:.0f} บาท/kg นี้ยังทำให้ Optimizer เลือกบริจาคของที่ยังขายได้ตั้งแต่เช้า"
         if s08["provisional_lots"] == 0 else
         f"3A มีแผนชั่วคราว {s08['provisional_lots']} lot (คืน IDLE ไม่มี task) ค่ารถเฉลี่ยของถังฝังกลบ {ldf['fee_per_kg']:.0f} บาท/kg"),
        f"<b>เวลาที่กดปุ่มเปลี่ยนแผน</b>: 08:00 ได้ {s08['decisions']} decision ({e(', '.join(f'{ACTION_TH.get(k, k)} {v}' for k, v in s08['actions'].items()))}) "
        f"ส่วน {s_last['at']} เหลือ {s_last['decisions']} decision ({e(', '.join(f'{ACTION_TH.get(k, k)} {v}' for k, v in s_last['actions'].items()))}) "
        f"ซ้อม demo กับ pitch จริงคนละเวลาจะเห็นแผนคนละแบบ",
    ]

    # ---- ตารางเปรียบเทียบนโยบาย
    comp_rows = [[pname(k), baht(p["net_profit"]), baht(p["net_profit_bin"]), baht(p["revenue_full"]), baht(p["revenue_md"]),
                  baht(p["kitchen_value"]), baht(p["disposal_a"]["trip"] + p["disposal_a"]["handling"] - p["disposal_a"]["buyback"]),
                  baht(p["write_off_expired"]), f"{p['sold_units']:,}", f"{p['kitchen_units']:,}", f"{p['disposed_units']:,}",
                  f"{p['left_units']:,}", f"{p['no_task_units']:,}", f"{p['risk_no_task_units']:,}", f"{p['expired_left_units']:,}"]
                 for k, p in order]
    comp = table(["นโยบาย", "กำไรวันนี้ (A)", "กำไร ถ้าค่ารถแบบถัง (B)", "ขายราคาเต็ม", "ขายลดราคา", "มูลค่าเมนูครัว",
                  "ค่ากำจัดสุทธิ (A)", "ตัดต้นทุนของหมดอายุค้าง", "ขาย (ชิ้น)", "ครัว (ชิ้น)", "partner / ทิ้ง (ชิ้น)",
                  "เหลือในร้าน (ชิ้น)", "ไม่มี task", "lot เสี่ยงไม่มี task", "หมดอายุค้าง"],
                 comp_rows, row_cls=[None, None, "ours", None])

    # ---- เงินทีละบรรทัด
    def money_rows(p):
        A = p["disposal_a"]
        return [("รายได้ขายราคาเต็ม", p["revenue_full"]), ("รายได้ขายลดราคา", p["revenue_md"]),
                ("มูลค่าเมนูครัว (สุทธิค่าไฟน้ำ / วัตถุดิบปกติ)", p["kitchen_value"]), ("รับซื้อคืน (buyback)", A["buyback"]),
                ("ค่าเรียกรถ partner (A)", -A["trip"]), ("ค่า handling", -A["handling"]),
                ("ต้นทุนของที่ขาย", -p["cogs_sold"]), ("ต้นทุนของที่เข้าครัว", -p["cogs_kitchen"]),
                ("ต้นทุนของที่ส่ง partner / ทิ้ง", -p["cogs_disposed"]), ("ตัดต้นทุนของหมดอายุที่ค้างในร้าน", -p["write_off_expired"])]
    money_cell = lambda v: Raw(f"<span class='{'num-neg' if v < 0 else ''}'>{v:,.2f}</span>")
    labels = [r[0] for r in money_rows(p1)]
    mrows = [[lab] + [money_cell(money_rows(p)[i][1]) for _, p in order] for i, lab in enumerate(labels)]
    mrows.append(["กำไรสุทธิวันนี้ (A)"] + [b2(p["net_profit"]) for _, p in order])
    mrows.append(["ส่วนลดที่ให้ลูกค้า (ข้อมูล)"] + [b2(p["discount_given"]) for _, p in order])
    money = table(["รายการ (บาท)"] + [pname(k) for k, _ in order], mrows,
                  row_cls=[None] * (len(mrows) - 2) + ["total", "sub"])

    # ---- ของค้างในร้าน
    class_rows = []
    for k, (label, has_task, _) in LEFT_CLASSES.items():
        if not any(k in p["left_by_class"] for _, p in order):
            continue
        row = [badge(k), "มี" if has_task else "ไม่มี"]
        for _, p in order:
            x = p["left_by_class"].get(k)
            row.append(f"{x['units']:,} ชิ้น · {x['lots']} lot · {baht(x['cost'])} ฿" if x else "-")
        class_rows.append(row)
    class_rows.append([Raw("<b>รวมของที่ยังอยู่ในร้าน</b>"), ""]
                      + [f"{p['left_units']:,} ชิ้น · {baht(p['left_cost'])} ฿" for _, p in order])
    class_rows.append([Raw("<b>ในนั้นไม่มี task ครอบ</b>"), ""]
                      + [f"{p['no_task_units']:,} ชิ้น · {baht(p['no_task_cost'])} ฿" for _, p in order])
    class_tbl = table(["ประเภทของที่เหลือ", "task"] + [pname(k) for k, _ in order], class_rows, left=2,
                      row_cls=[None] * (len(class_rows) - 2) + ["total", "total"])
    stacks = "".join(f"<div class='bar-label'><b>{e(pname(k))}</b> · ของเช้า {p['units_in']:,} ชิ้น</div>{stack(p)}"
                     for k, p in order)

    def left_table(p, with_reason: bool):
        rows = []
        for r in sorted(p["left"], key=lambda r: (list(LEFT_CLASSES).index(r["class"]), r["lot_id"], r["uid"])):
            reason = ""
            if with_reason:
                lv = next((x for x in res["optimizer"][p["key"]]["lots"] if x["lot_id"] == r["lot_id"]), None)
                level = scan["lots"].get(r["lot_id"], {}).get("risk_level", "-")
                if r["class"] == "IN_BIN_WAITING":
                    reason = f"รอ {r['partner_id']} รับ {hhmm(r['pickup_at'])} · {r['kg']:.2f} kg"
                elif lv:
                    reason = " · ".join(lv["portions"])
                else:
                    reason = f"ระดับ {level}"
            rows.append([r["lot_id"] + (" (ป้ายลดราคา)" if r["uid"] != r["lot_id"] else ""), names[r["product_id"]],
                         badge(r["class"]), r["expiry"] or "-", "-" if r["days_left"] is None else r["days_left"],
                         f"{r['units']:,}", b2(r["price"]), b2(r["cost"]), b2(r["retail_now"]), reason])
        return table(["lot", "สินค้า", "ประเภท", "หมดอายุ", "เหลือ (วัน)", "ชิ้น", "ราคาบนชั้น", "ต้นทุน",
                      "มูลค่าที่ราคาบนชั้น", "แผนของ lot นี้ / ที่รอ"], rows, left=4)

    # ---- สแกน + Forecaster
    scan_rows = [[l["lot_id"], names[l["product_id"]], l["expiration_date"], l["days_to_expiry"], f"{l['quantity']:,}",
                  l["risk_level"], b2(l["risk_score"]), b2(l["forecast_daily_demand"]),
                  b2(l["predicted_units_sold_before_expiry"]), b2(l["predicted_leftover_units"]),
                  f"{l['sell_through_probability'] * 100:.1f}%", "ส่งต่อ" if l["risk_level"] in ("HIGH", "CRITICAL") else "-"]
                 for l in sorted(scan["lots"].values(), key=lambda x: (-x["risk_score"], x["lot_id"]))]
    scan_tbl = table(["lot", "สินค้า", "หมดอายุ", "เหลือ (วัน)", "ชิ้น", "ระดับ", "คะแนน", "ยอดขาย/วัน (ทาย)",
                      "คาดขายได้ก่อนหมดอายุ", "คาดเหลือ", "โอกาสขายหมด", "Optimizer"], scan_rows, left=3)
    fc_rows = [[pid, names[pid], b2(v["forecast_mu"]), f"{v['proxy']:.1f}", b2(v["forecast_mu"] - v["proxy"]),
                f"{v['stock_units']:,}", v["lots"]] for pid, v in sorted(res["demand"]["by_product"].items())]
    fc_tbl = table(["สินค้า", "ชื่อ", "Forecaster ทายวันนี้ (ราคาเต็ม)", "ลูกค้าที่ใช้จำลอง", "ทาย − จำลอง",
                    "สต็อกเช้า (ชิ้น)", "lot"], fc_rows, left=2)

    # ---- Optimizer
    def dec_table(v):
        rows = []
        for x in v["decisions"]:
            target = (f"{x['price']:,.2f} ฿ (−{x['discount_pct']:g}%)" if x["price"] else
                      f"{x['recipe']} × {x['batches']}" if x["recipe"] else x["partner"] or "-")
            rows.append([x["lot_id"], x["name"], x["risk"], x["days_to_expiry"], ACTION_TH.get(x["action"], x["action"]),
                         f"{x['quantity']:,} / {x['lot_quantity']:,}", target, hhmm(x["due_by"]), signed(x["expected_thb"]),
                         b2(x["score"])])
        return table(["lot", "สินค้า", "ระดับ", "เหลือ (วัน)", "ทำอะไร", "จำนวน / lot", "ราคาใหม่ / สูตร / partner",
                      "ทำภายใน", "กำไรที่คาด (฿)", "score"], rows, left=3)

    def lots_table(v):
        rows = [[x["lot_id"], x["name"], x["risk"], x["days_to_expiry"], f"{x['quantity']:,}", Raw("<br>".join(map(e, x["portions"]))),
                 "คืน IDLE" if x["released"] else "มี task", signed(x["net_thb"]),
                 "-" if x["md_expected_leftover"] is None else f"{x['md_expected_leftover']:.1f}"] for x in v["lots"]]
        return table(["lot", "สินค้า", "ระดับ", "เหลือ (วัน)", "ชิ้น", "แผน (ชิ้นต่อทาง)", "สถานะหลังรอบนี้",
                      "กำไรที่คาดของ lot", "ป้ายลดราคาคาดว่าเหลือ"], rows, left=3)

    def bins_table(v):
        rows = [[x["partner_id"], METHOD_TH.get(x["partner_type"], x["partner_type"]), x["mode"],
                 b2(x["waste_kg_per_day"]), x["calls_per_week"] or "-", b2(x["economic_call_kg"]), b2(x["trip_cost_thb"]),
                 b2(x["fee_per_kg_thb"]), b2(x["cost_per_kg_thb"]), b2(x["now_kg"]), b2(x["end_of_life_kg_later"]),
                 "เรียกได้เลย" if x["call_now"] else "รอ", x["call_reason"] or "-", hhmm(x["expected_call_at"])]
                for x in v["partner_bins"]]
        return table(["partner", "ประเภท", "โหมด", "ของทิ้ง kg/วัน (ประวัติ)", "เรียก/สัปดาห์", "ปริมาณที่คุ้ม kg",
                      "ค่าเรียกรถ", "ค่ารถเฉลี่ย ฿/kg", "ต้นทุนสุทธิ ฿/kg", "ดึงออกรอบนี้ kg", "ของเหลือหลังหมดเวลาขาย kg",
                      "เรียกรถ", "เหตุผล", "เรียกรถเมื่อ"], rows, left=3)

    def trips_table(p):
        rows = [[t["partner_id"], METHOD_TH.get(t["partner_type"], t["partner_type"]), t["pickup_date"],
                 "รับแล้ววันนี้" if t["picked_up_today"] else "ยังรอ", ", ".join(t["timing"]), f"{t['units']:,}",
                 b2(t["kg"]), f"{t['min_kg']:g}" + (" ⚠ ต่ำกว่าขั้นต่ำ" if t["below_min"] else ""), t["mode_in_optimizer"],
                 b2(t["trip_cost_a"]), b2(t["trip_cost_b"]), b2(t["handling"]), b2(t["buyback"]), ", ".join(t["lots"])]
                for t in p["trips"]]
        return table(["partner", "ประเภท", "วันรับ", "สถานะ", "ช่วง", "ชิ้น", "kg", "ขั้นต่ำ kg", "โหมดใน Optimizer",
                      "ค่ารถ A (เรียกเฉพาะ)", "ค่ารถ B (เฉลี่ยแบบถัง)", "handling", "buyback", "lot"], rows, left=5)

    def kitchen_table(v):
        rows = [[j["job_id"], j["name"], j["department_id"], j["date"], j["batches"], f"{j['anchor_units']:,}",
                 b2(j["output_units"]), b2(j["expected_sold_units"]), hhmm(j["start_at"]), hhmm(j["due_by"]),
                 b2(j["revenue_thb"]), b2(j["utility_cost_thb"]), signed(j["net_profit_thb"])] for j in v["kitchen_jobs"]]
        return table(["งาน", "เมนู", "ครัว", "วัน", "batch", "ใช้ lot หลัก (ชิ้น)", "ได้เมนู", "คาดขายเมนู", "เริ่ม",
                      "เสร็จ", "รายได้เมนู", "ค่าไฟน้ำ+วัตถุดิบรอง", "กำไรที่คาด"], rows, left=4)

    base_th = {"do_nothing_no_disposal_cost": "ไม่ทำอะไร (ไม่คิดค่ากำจัด)", "regular_price_then_landfill": "ขายราคาปกติแล้วฝังกลบ",
               "markdown_then_landfill": "ลดราคาแล้วฝังกลบ", "optimized": "ตามแผน Optimizer"}
    base_rows = lambda v: [[base_th[k], baht(x["net_profit_thb"])] for k, x in v["baselines"].items()
                           if k in base_th and isinstance(x, dict)]
    warn = lambda v: "".join(f"<li>{e(w)}</li>" for w in v["warnings"]) or "<li>ไม่มี</li>"

    # ---- ทุก lot ทีละบรรทัด (เทียบ 4 นโยบาย)
    def lot_cell(p, lot_id):
        t = p["trace"].get(lot_id, {})
        bits = []
        for k, lab in (("sold_full", "ขายเต็ม"), ("sold_md", "ขายลด"), ("kitchen", "ครัว"), ("kitchen_ingredient", "วัตถุดิบครัว")):
            if t.get(k):
                bits.append(f"{lab} {t[k]}")
        for k in PARTNER_METHODS:
            if t.get(k):
                bits.append(f"{METHOD_ALL[k]} {t[k]}")
        left = [r for r in p["left"] if r["lot_id"] == lot_id]
        for r in left:
            bits.append(f"<b style='color:{LEFT_CLASSES[r['class']][2]}'>เหลือ {r['units']} "
                        f"({e(LEFT_CLASSES[r['class']][0].split(' (')[0])})</b>")
        return Raw("<br>".join(bits) or "-")

    lot_rows = [[l["lot_id"], names[l["product_id"]], l["expiration_date"], f"{l['quantity']:,}", l["risk_level"]]
                + [lot_cell(p, l["lot_id"]) for _, p in order]
                for l in sorted(scan["lots"].values(), key=lambda x: x["lot_id"])]
    lot_tbl = table(["lot", "สินค้า", "หมดอายุ", "ชิ้นเช้า", "ระดับ"] + [pname(k) for k, _ in order], lot_rows, left=9)

    # ---- เวลาที่กด / ลูกค้ามากน้อย
    sens_rows = [[s["at"], s["decisions"], ", ".join(f"{ACTION_TH.get(k, k)} {v}" for k, v in sorted(s["actions"].items())) or "-",
                  f"{s['markdown_units']:,}", f"{s['partner_units']:,}", s["kitchen_jobs"], s["provisional_lots"],
                  s["released_lots"], f"{s['unresolved_units']:,}", signed(s["expected_net"]), s["violations"]]
                 for s in res["time_sensitivity"]]
    sens_tbl = table(["กดปุ่มเวลา", "decision", "แยกตาม action", "ชิ้นที่ลดราคา", "ชิ้นที่ส่ง partner", "งานครัว",
                      "lot แผนชั่วคราว", "lot คืน IDLE", "ไม่มีทางไป (ชิ้น)", "กำไรที่ Optimizer คาด", "หลุดกฎ"],
                     sens_rows, left=1)
    dem_rows = []
    for s in res["demand_scenarios"]:
        for k in ("p1", "p2", "p3a", "p3b"):
            p = s["policies"][k]
            dem_rows.append([f"× {s['scale']:g}" if k == "p1" else "", pname(k), baht(p["net_profit"]), baht(p["net_profit_bin"]),
                             f"{p['sold_units']:,}", f"{p['left_units']:,}", f"{p['no_task_units']:,}",
                             f"{p['risk_no_task_units']:,}", f"{p['expired_left_units']:,}"])
    dem_tbl = table(["ลูกค้า", "นโยบาย", "กำไร (A)", "กำไร (B)", "ขาย (ชิ้น)", "เหลือในร้าน", "ไม่มี task", "lot เสี่ยงไม่มี task",
                     "หมดอายุค้าง"], dem_rows, left=2,
                    row_cls=["ours" if i % 4 == 2 else None for i in range(len(dem_rows))])

    # ---- ดึงออกก่อนหมดอายุ (เหตุที่กำไรวันเดียวของ 3A ต่ำ)
    hp1 = H["p1"]["trace"]
    early_rows = []
    for lot_id, x in sorted(a["early_removals"].items()):
        l = scan["lots"][lot_id]
        t1 = hp1.get(lot_id, {})
        early_rows.append([lot_id, names[l["product_id"]], l["expiration_date"], f"{l['quantity']:,}",
                           ", ".join(METHOD_ALL.get(m, m) for m in x["methods"]), f"{x['units']:,}", b2(x["kg"]), b2(x["cogs"]),
                           b2(l["predicted_leftover_units"]),
                           f"{p1['trace'].get(lot_id, {}).get('sold_full', 0):,}",
                           f"{t1.get('sold_full', 0) + t1.get('sold_md', 0):,}", f"{t1.get('LANDFILL', 0):,}"])
    early_tbl = table(["lot", "สินค้า", "หมดอายุ", "ชิ้นเช้า", "3A ส่งไป", "ชิ้น", "kg", "ต้นทุนที่ 3A นับวันนี้",
                       "Risk Scanner คาดว่าเหลือ", "ร้านเดิม: ขายวันนี้", "ร้านเดิม: ขายรวมจนหมดอายุ",
                       "ร้านเดิม: ทิ้งรวม"], early_rows, left=3)

    # ---- ปล่อยต่อจนทุก lot หมดอายุ
    hz_rows = []
    for k, _ in order:
        h = H[k]
        dm = h["disposed_by_method"]
        hz_rows.append([pname(k), baht(h["net_profit"]), baht(h["net_profit_bin"]), signed(h["net_profit"] - H["p1"]["net_profit"]),
                        f"{h['sold_full']:,}", f"{h['sold_md']:,}", f"{h['kitchen_units']:,}",
                        ", ".join(f"{METHOD_ALL.get(m, m)} {n:,}" for m, n in sorted(dm.items())) or "-",
                        f"{h['unplanned_units']:,} · {baht(h['unplanned_cogs'])} ฿", baht(h["waste_cogs"]),
                        f"{h['calls']}", b2(h["landfill_kg"])])
    hz_tbl = table(["นโยบาย", "กำไรรวม (A)", "กำไรรวม (B)", "เทียบร้านเดิม", "ขายราคาเต็ม", "ขายลดราคา", "ครัว",
                    "partner / ทิ้ง (ชิ้น)", "ทิ้งเองตอนหมดอายุ ไม่มี decision", "ต้นทุนของที่ทิ้ง / ส่ง partner",
                    "เที่ยวรถ", "ฝังกลบ kg"], hz_rows, row_cls=[None, None, "ours", None])

    def hz_cell(k, lot_id):
        t = H[k]["trace"].get(lot_id, {})
        bits = [f"{lab} {t[key]}" for key, lab in (("sold_full", "ขายเต็ม"), ("sold_md", "ขายลด"), ("kitchen", "ครัว"),
                                                   ("kitchen_ingredient", "วัตถุดิบครัว")) if t.get(key)]
        bits += [f"{METHOD_ALL[m]} {t[m]}" for m in PARTNER_METHODS if t.get(m)]
        if t.get("unplanned"):
            bits.append(f"<b style='color:#c0392b'>ในนั้นทิ้งเองไม่มี decision {t['unplanned']}</b>")
        return Raw("<br>".join(bits) or "-")

    hz_lot_tbl = table(["lot", "สินค้า", "หมดอายุ", "ชิ้นเช้า"] + [pname(k) for k, _ in order],
                       [[l["lot_id"], names[l["product_id"]], l["expiration_date"], f"{l['quantity']:,}"]
                        + [hz_cell(k, l["lot_id"]) for k, _ in order]
                        for l in sorted(scan["lots"].values(), key=lambda x: x["lot_id"])], left=8)

    partners_rows = [[x["partner_id"], METHOD_TH.get(x["type"], x["type"]), x["mode"], b2(x["trip_cost"]), b2(x["handling"]),
                      b2(x["buyback"]), f"{x['min_kg']:g} / {x['cap_kg']:g}", ",".join(map(str, x["pickup_days"])),
                      x["window"], b2(x["daily_kg"]), b2(x["economic_kg"]), b2(x["fee_per_kg"])] for x in res["partners"]]
    partners_tbl = table(["partner", "ประเภท", "โหมด (3A)", "ค่าเรียกรถ/ครั้ง", "handling/kg", "buyback/kg",
                          "ขั้นต่ำ / ความจุ kg", "วันรับ (1=จ)", "เวลารับ", "ของทิ้ง kg/วัน", "ปริมาณที่คุ้ม kg",
                          "ค่ารถเฉลี่ย ฿/kg"], partners_rows, left=3)
    lv = " · ".join(f"{k} {v}" for k, v in sorted(scan["levels"].items()))
    weekday = "จันทร์ อังคาร พุธ พฤหัสบดี ศุกร์ เสาร์ อาทิตย์".split()[date.fromisoformat(res["date"]).weekday()]

    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>One-shot {res['date']}</title><style>{CSS}{EXTRA_CSS}</style></head><body><div class="page">
<h1>Backtest แบบกดรันครั้งเดียว วันเดียวจบ · {res['date']} ({weekday})</h1>
<div class="meta">{res['lots']} lot · {res['units']:,} ชิ้น · ต้นทุนสต็อกเช้า {baht(res['cost_in'])} บาท · กดปุ่มตอน {res['run_at']} ·
branch <b>{e(res['branch'])}</b> ({e(res['commit'])}) · Forecaster {e(res['forecaster'])} · หน่วยเงิน: บาท</div>
<div class="toc"><a href="#find">ข้อค้นพบ</a><a href="#compare">เทียบ 4 นโยบาย</a><a href="#left">ของค้างในร้าน</a>
<a href="#money">เงินทีละบรรทัด</a><a href="#early">ดึงออกก่อนหมดอายุ</a><a href="#horizon">ปล่อยจนหมดอายุ</a>
<a href="#trips">ค่ารถ partner</a><a href="#scan">ผลสแกน</a><a href="#opt">แผน Optimizer</a>
<a href="#lots">ทุก lot</a><a href="#time">กดปุ่มเวลาไหน</a><a href="#demand">ลูกค้ามาก/น้อย</a><a href="#method">วิธีคิด</a></div>

<div class="kpis">
{kpi("กำไรสุทธิวันนี้ · 3A", baht(a['net_profit']), f"ร้านเดิม {baht(p1['net_profit'])} · กฎตายตัว {baht(p2['net_profit'])} · 3B {baht(b['net_profit'])}", "" if a['net_profit'] >= p1['net_profit'] else "bad")}
{kpi("ผลจนทุก lot หมดอายุ · 3A", baht(H['p3a']['net_profit']), f"ร้านเดิม {baht(H['p1']['net_profit'])} · ต่าง {signed(H['p3a']['net_profit'] - H['p1']['net_profit'])} บาท", "" if H['p3a']['net_profit'] >= H['p1']['net_profit'] else "bad")}
{kpi("ของยังอยู่ในร้านตอนปิด · 3A", f"{a['left_units']:,} ชิ้น", f"ต้นทุน {baht(a['left_cost'])} บาท · ไม่มี task {a['no_task_units']:,} ชิ้น")}
{kpi("lot เสี่ยงที่ไม่มี task · 3A", f"{a['risk_no_task_units']:,} ชิ้น", f"{a['risk_no_task_lots']} lot · ต้นทุน {baht(a['risk_no_task_cost'])} บาท", "bad" if a['risk_no_task_units'] else "")}
{kpi("หมดอายุค้างร้านคืนนี้ · 3A", f"{a['expired_left_units']:,} ชิ้น", f"{a['expired_left_lots']} lot · ต้นทุน {baht(a['write_off_expired'])} บาท", "bad" if a['expired_left_units'] else "")}
</div>

<div class="find" id="find"><h3>ข้อค้นพบ</h3><ol>{''.join(f'<li>{x}</li>' for x in findings)}</ol></div>

<h2 id="compare">เทียบ 4 นโยบาย (ของเช้าชุดเดียวกัน ลูกค้าชุดเดียวกัน)</h2>
{comp}
<div class="note">A = ค่ารถแบบเรียกเฉพาะ 1 ครั้งต่อ (partner, วันรับ) ที่มีของ · B = ค่ารถเฉลี่ยต่อ kg แบบถังตามที่ Optimizer คิด
(รถขนรวมกับของทิ้งวันอื่น) · "ตัดต้นทุนของหมดอายุค้าง" = ของที่ขายไม่ได้แล้วแต่ยังไม่มีใครจัดการ นับเป็นขาดทุนวันนี้</div>

<h2 id="left">ของที่ยังค้างในร้านตอนปิดร้าน (และมี task ครอบหรือยัง)</h2>
{legend()}{stacks}
{class_tbl}
<details open><summary>3A · ของค้างทีละ lot ({a['left_units']:,} ชิ้น)</summary>{left_table(a, True)}</details>
<details><summary>3B · ของค้างทีละ lot ({b['left_units']:,} ชิ้น)</summary>{left_table(b, True)}</details>
<details><summary>1 · ร้านแบบเดิม ({p1['left_units']:,} ชิ้น)</summary>{left_table(p1, False)}</details>
<details><summary>2 · กฎตายตัว ({p2['left_units']:,} ชิ้น)</summary>{left_table(p2, False)}</details>

<h2 id="money">เงินทีละบรรทัด (วันเดียว)</h2>
{money}

<h2 id="early">ของที่ 3A ดึงออกทั้งที่ยังขายได้ (ทำไมกำไรวันเดียวของ 3A ต่ำ)</h2>
<div class="note">Optimizer ตัดสินจากผลทั้งอายุของ lot: ของที่คาดว่าขายไม่หมดต้องจ่ายค่ากำจัด
(ถังฝังกลบคิดเฉลี่ย {ldf['fee_per_kg']:.0f} บาท/kg) จึงส่งบริจาคตั้งแต่ตอนนี้ (เที่ยวละ 550 บาท) ขณะที่อายุยังพอ
ต้นทุนของส่วนนี้ถูกนับวันนี้ ส่วนร้านเดิมเห็นผลของ lot เดียวกันในวันถัด ๆ ไป (สองคอลัมน์ขวา)</div>
{early_tbl}

<h2 id="horizon">ถ้าปล่อยต่อจนทุก lot หมดอายุ (ไม่มีรอบสแกน / decision เพิ่ม)</h2>
<div class="note">ต่อจากวัน demo ทุกวันจนถึง {H['p1']['last_day']} ({H['p1']['days']} วัน): ร้านขายตามปกติ (ลูกค้า = เฉลี่ยวันเดียวกัน
4 สัปดาห์ล่าสุดที่มีข้อมูล) ไม่มีของเข้าร้าน · ของหมดอายุที่มี decision END_OF_LIFE ไป partner ตามแผน ที่ไม่มีร้านทิ้งเอง (landfill)
· กฎตายตัวปรับราคาทุกวัน · ไม่มีของใหม่มาแข่ง จึงขายได้มากกว่าความจริงเท่ากันทุกนโยบาย</div>
{hz_tbl}
<details><summary>ทุก lot: ผลรวมจนหมดอายุ</summary>{hz_lot_tbl}</details>

<h2 id="trips">ค่ารถ partner ทีละเที่ยว</h2>
<details open><summary>3A · Optimizer ตามโค้ดจริง</summary>{trips_table(a)}</details>
<details><summary>3B · Optimizer โหมดวันเดียว</summary>{trips_table(b)}</details>
<details><summary>1 · ร้านแบบเดิม / 2 · กฎตายตัว</summary>{trips_table(p1)}{trips_table(p2)}</details>
<h3>partner ในข้อมูล</h3>{partners_tbl}

<h2 id="scan">ผลสแกนความเสี่ยง (Forecaster + Risk Scanner)</h2>
<div class="note">ระดับความเสี่ยง: {e(lv)} · ส่งต่อ Optimizer เฉพาะ HIGH / CRITICAL ({scan['forwarded']} lot)</div>
{scan_tbl}
<h3>Forecaster ทายวันนี้ vs ลูกค้าที่ใช้จำลอง</h3>
<div class="note">ลูกค้าที่ใช้จำลอง = latent_demand เฉลี่ย{weekday} {len(res['demand']['proxy_dates'])} สัปดาห์ก่อน
({', '.join(res['demand']['proxy_dates'])}) เพราะ mock_v3 ไม่มีข้อมูลของ {res['date']} · ไม่ใช่ค่าที่ Forecaster ทาย</div>
{fc_tbl}

<h2 id="opt">แผนของ Optimizer</h2>
<h3>3A · decision ที่บันทึก ({len(va['decisions'])} ตัว: {e(', '.join(f'{ACTION_TH.get(k, k)} {v}' for k, v in va['action_counts'].items()))})</h3>
{dec_table(va)}
<h3>3A · แผนทุก lot ที่ส่งต่อ</h3>{lots_table(va)}
<div class="two">
<div><h3>3A · แผนชั่วคราว (ไม่มี task · lot คืน IDLE)</h3>
{table(["lot", "สินค้า", "วิธี", "ชิ้น", "kg", "รถมารับ (ถ้ารอบหน้ายังเหมือนเดิม)", "กำไรที่คาด"],
       [[x["lot_id"], x["name"], METHOD_ALL.get(x["method"], x["method"]), x["units"], b2(x["kg"]), hhmm(x["pickup_at"]),
         signed(x["net_thb"])] for x in va["provisional"]], left=3)}</div>
<div><h3>Optimizer ประเมินเอง (ทั้งอายุที่เหลือของ lot เสี่ยง)</h3>
{table(["ทางเลือก", "3A กำไรที่คาด"], base_rows(va))}
<div class="note">ตัวเลขนี้คิดยอดขายจนหมดอายุของ lot ที่ส่งต่อ ไม่ใช่ผลวันเดียวด้านบน</div></div>
</div>
<h3>3A · สถานะถัง partner (plan.partner_bins: ระบบจริงไม่ได้บันทึก / ไม่แสดงบน dashboard)</h3>{bins_table(va)}
<h3>3A · งานครัว</h3>{kitchen_table(va)}
<details><summary>3A · คำเตือนจาก Optimizer ({len(va['warnings'])})</summary><div class="note"><ul class="why">{warn(va)}</ul></div></details>
<details><summary>3B · decision ({len(vb['decisions'])} ตัว) + แผนทุก lot + ถัง partner + งานครัว</summary>
{dec_table(vb)}{lots_table(vb)}{bins_table(vb)}{kitchen_table(vb)}
<div class="note"><ul class="why">{warn(vb)}</ul></div></details>

<h2 id="lots">ทุก lot: แต่ละนโยบายทำอะไรกับมัน</h2>
{lot_tbl}

<h2 id="time">ถ้ากดปุ่มเวลาอื่น (ข้อมูลเดียวกัน · 3A)</h2>
<div class="note">ระบบจริงใช้เวลานาฬิกาตอนกดปุ่ม (DB demo ไม่ลดจำนวนตามยอดขายช่วงเช้า) ตารางนี้เทียบเฉพาะแผนที่ได้
ไม่ได้จำลองการขาย: ชั่วโมงขายที่เหลือน้อยลง งานครัวต้องเสร็จก่อน 17:00 รอบรับของ partner บางรอบผ่านไปแล้ว</div>
{sens_tbl}

<h2 id="demand">ถ้าลูกค้ามากหรือน้อยกว่าที่คาด (แผนเดิม)</h2>
{dem_tbl}

<h2 id="method">วิธีคิดและข้อจำกัด</h2>
<div class="note">
<b>ลำดับของวัน</b>: 08:00 สแกน 27 lot → Optimizer ตัดสินใจ → staff ทำตามทุก decision ทันที (ติดป้ายลดราคา = แยก lot ใหม่ราคาลด,
ครัวตัดของ, ดึงของออกส่ง partner) → ขายทั้งวันด้วยลูกค้าชุดเดียวกัน → 22:00 ปิดร้าน: ของหมดอายุคืนนี้ไป partner
เฉพาะที่มี decision END_OF_LIFE (3A / 3B) ส่วนร้านเดิม / กฎตายตัวทิ้งเอง (landfill)<br>
<b>ไม่มีวันพรุ่งนี้</b>: ของที่ระบบตั้งใจให้รอบหน้าจัดการ (แผนชั่วคราว, ป้ายลดราคาขายไม่หมด, lot ที่หมดอายุแล้วแต่ไม่มี decision)
จึงค้างในร้าน รายงานแยกไว้ในหัวข้อ "ของค้างในร้าน" · สต็อกที่ยังขายได้คิดที่ต้นทุน (ผลวันเดียวเข้าข้างการลดราคา:
ของที่ลดราคาวันนี้อาจขายราคาเต็มได้พรุ่งนี้ ดูมูลค่าราคาบนชั้นประกอบ)<br>
<b>มูลค่าเมนูครัว</b> ใช้ค่าคาดหมายจากแผนของ Optimizer (ไม่ได้จำลองลูกค้าเมนู) · งานครัวของพรุ่งนี้นับว่าทำแล้ว (decision ออกวันนี้)<br>
<b>ลูกค้า</b>: sell() ของ run_backtest (lot ลดราคาได้ก่อน × TRUE_LIFT, 40% หยิบ lot ใหม่สุด ที่เหลือ FIFO) ·
<b>Forecaster</b> ตัวจริงในเครื่อง (เทรนถึง 15 ต.ค.) · <b>partner / สินค้า / สูตร / ครัว</b>: fixture supabase_2026-10-16 ·
ข้ามขั้น LLM (decision 1 ตัว = task 1 ตัว อนุมัติทั้งหมด)
</div>
</div></body></html>"""


# ---------------------------------------------------------------- main
def git_info() -> tuple[str, str]:
    try:
        run = lambda *a: subprocess.run(["git", *a], cwd=HERE, capture_output=True, text=True, check=True).stdout.strip()
        return run("rev-parse", "--abbrev-ref", "HEAD"), run("log", "-1", "--format=%h %s")
    except (OSError, subprocess.CalledProcessError):
        return "-", "-"


def main():
    ap = argparse.ArgumentParser(description="Backtest แบบกดรันครั้งเดียว วันเดียวจบ (27 lot ของ demo)")
    ap.add_argument("--out", type=Path, default=HERE / "output")
    ap.add_argument("--render-only", action="store_true", help="สร้าง HTML ใหม่จาก JSON เดิม")
    args = ap.parse_args()
    d = DEMO_DATE
    stem = args.out / f"oneshot_{d.isoformat()}"
    if args.render_only:
        res = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
        stem.with_suffix(".html").write_text(render_html(res), encoding="utf-8")
        print(f"ไฟล์: {stem.with_suffix('.html')}")
        return

    world = World(d, 1)
    base, locations = demo_lots(world)
    proxy, proxy_dates = proxy_demand(world, d)
    pctx = world.partner_ctx(d)
    names = {pid: p["name"] for pid, p in world.products.items()}
    print(f"one-shot {d} | {len(base)} lot | {sum(l.qty for l in base):,} ชิ้น")

    scanner = DemoScanner()
    results, recipe_rows, demand = scanner.scan(base, d)
    levels = {r["payload"]["lot_id"]: r["payload"]["risk_level"] for r in results}
    history = world.waste_history(d)
    no_history = {"from": history["from"], "to": history["to"], "days": 0, "kg_per_day": {}}
    inputs_a = optimizer_inputs(world, base, d, results, recipe_rows, locations, history)
    inputs_b = optimizer_inputs(world, base, d, results, recipe_rows, locations, no_history)
    now = datetime.combine(d, RUN_AT, tzinfo=BKK)
    opt = {}
    for key, inputs in (("p3a", inputs_a), ("p3b", inputs_b)):
        res = run_optimizer(inputs, products_catalog=world.catalog, now=now, strict=False, with_baselines=True)
        opt[key] = {"result": res}
        print(f"  {key}: decision {len(res['payload']['decisions'])} | คืน IDLE {len(res['lots_to_release'])} | "
              f"หลุดกฎ {len(res['violations']) + len(res['payload_errors'])}")

    def run_all(scale: float, variant: str | None = None) -> tuple[dict, str, dict]:
        set_demand(world, d, proxy, scale)
        states = {"p1": run_rule_day(world, base, d, "p1", pctx)}
        p2_states = {k: run_rule_day(world, base, d, "p2", pctx, rule) for k, rule in FIXED_RULES.items()}
        variants = {k: summarize_day(world, s, base, d, pctx) for k, s in p2_states.items()}
        chosen = variant or max(variants, key=lambda k: variants[k]["net_profit"])
        states["p2"] = p2_states[chosen]
        out = {"p1": summarize_day(world, states["p1"], base, d, pctx), "p2": variants[chosen]}
        for key in ("p3a", "p3b"):
            states[key] = run_optimizer_day(world, base, d, key, opt[key]["result"])
            out[key] = summarize_day(world, states[key], base, d, pctx, opt[key])
        out["_variants"] = {k: {"net_profit": v["net_profit"], "left_units": v["left_units"]} for k, v in variants.items()}
        return out, chosen, states

    policies, variant, states = run_all(1.0)
    variants = policies.pop("_variants")
    last_expiry = max(l.expiry for l in base)
    proxies = {d + timedelta(days=i): proxy_demand(world, d + timedelta(days=i))[0]
               for i in range(1, (last_expiry - d).days + 1)}
    horizon = {}
    for key, st in states.items():
        last = continue_until_expiry(world, st, d, proxies, pctx, FIXED_RULES[variant] if key == "p2" else None)
        horizon[key] = horizon_summary(world, st, base, d, last, pctx)
    scenarios = []
    for s in DEMAND_SCALES:
        pol, _, _ = run_all(s, variant)
        pol.pop("_variants")
        scenarios.append({"scale": s, "policies": {k: {x: v[x] for x in ("net_profit", "net_profit_bin", "sold_units",
                                                                         "left_units", "no_task_units", "risk_no_task_units",
                                                                         "expired_left_units")}
                                                   for k, v in pol.items()}})
    set_demand(world, d, proxy, 1.0)

    sensitivity = []
    for t in SENSITIVITY_TIMES:
        r = run_optimizer(inputs_a, products_catalog=world.catalog, now=datetime.combine(d, t, tzinfo=BKK), strict=False,
                          with_baselines=False)
        sensitivity.append({"at": t.strftime("%H:%M"), **plan_brief(r)})
        print(f"  กดปุ่ม {t:%H:%M}: decision {sensitivity[-1]['decisions']} {sensitivity[-1]['actions']}")

    stock = Counter()
    lots_per_product = Counter()
    for l in base:
        stock[l.product_id] += l.qty
        lots_per_product[l.product_id] += 1
    scan_lots = {}
    for r in results:
        p = r["payload"]
        l = next(x for x in base if x.uid == p["lot_id"])
        scan_lots[p["lot_id"]] = {k: p[k] for k in ("lot_id", "days_to_expiry", "forecast_daily_demand",
                                                    "predicted_units_sold_before_expiry", "predicted_leftover_units",
                                                    "sell_through_probability", "risk_score", "risk_level")}
        scan_lots[p["lot_id"]].update(product_id=l.product_id, expiration_date=l.expiry.isoformat(), quantity=l.qty)
    fc_v = getattr(scanner.fc, "version", rf_config.MODEL_VERSION)
    branch, commit = git_info()
    partners = []
    for pid, pc in sorted(pctx.items()):
        p = pc.partner
        partners.append({"partner_id": pid, "type": p.partner_type, "mode": pc.mode, "trip_cost": pc.trip_cost,
                         "handling": pc.handling, "buyback": p.buyback, "min_kg": pc.min_kg, "cap_kg": pc.cap_kg,
                         "pickup_days": sorted(p.pickup_days),
                         "window": f"{p.t_start:%H:%M}-{p.t_end:%H:%M}" if p.t_start and p.t_end else "-",
                         "daily_kg": pc.daily_kg, "economic_kg": pc.expected_kg, "fee_per_kg": pc.fee_per_kg})
    res = {
        "date": d.isoformat(), "run_at": RUN_AT.strftime("%H:%M"), "branch": branch, "commit": commit,
        "forecaster": str(fc_v), "lots": len(base), "units": sum(l.qty for l in base),
        "cost_in": round(sum(l.qty * l.cost for l in base), 2), "names": names,
        "max_hold_days": OptimizerConfig().max_hold_days,
        "policies": policies, "policy2_variant": variant, "policy2_variants": variants,
        "optimizer": {k: optimizer_view(v["result"], names) for k, v in opt.items()},
        "scan": {"lots": scan_lots, "levels": dict(Counter(levels.values())),
                 "forwarded": sum(v in rf_config.FORWARD_LEVELS for v in levels.values())},
        "demand": {"proxy_dates": [x.isoformat() for x in proxy_dates],
                   "by_product": {pid: {"forecast_mu": demand.get((pid, d), 0.0), "proxy": proxy.get(pid, 0.0),
                                        "stock_units": stock[pid], "lots": lots_per_product[pid]} for pid in stock}},
        "partners": partners, "waste_history": history,
        "time_sensitivity": sensitivity, "demand_scenarios": scenarios, "horizon": horizon,
    }
    for k in ("p1", "p2", "p3a", "p3b"):
        p = policies[k]
        print(f"  {POLICY_TH[k]:<32} กำไร {p['net_profit']:>10,.2f} (ถัง {p['net_profit_bin']:>10,.2f}) | ขาย {p['sold_units']:>4} | "
              f"เหลือ {p['left_units']:>4} (ไม่มี task {p['no_task_units']:>4}, lot เสี่ยงไม่มี task {p['risk_no_task_units']:>3}) | "
              f"หมดอายุค้าง {p['expired_left_units']}")
    for k, h in horizon.items():
        print(f"  ถึง {h['last_day']} {POLICY_TH[k]:<32} กำไร {h['net_profit']:>10,.2f} (ถัง {h['net_profit_bin']:>10,.2f}) | "
              f"ขาย {h['sold_full'] + h['sold_md']:>4} | ทิ้ง/partner {h['disposed_by_method']} | ไม่มี task {h['unplanned_units']}")
    args.out.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    stem.with_suffix(".html").write_text(render_html(res), encoding="utf-8")
    print(f"ไฟล์: {stem.with_suffix('.html')}")


if __name__ == "__main__":
    main()
