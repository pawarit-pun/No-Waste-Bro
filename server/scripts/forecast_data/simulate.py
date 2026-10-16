"""สร้างข้อมูล daily_context + product_daily สำหรับ No-Waste-Bro (prototype)

- อากาศ: Open-Meteo จริง (archive 12 ก.ค.–15 ต.ค. / forecast 16–25 ต.ค.) พิกัด 13.75, 100.50
- วันหยุด / วันเงินเดือน: ประกาศจริง (ดู CONFIG) ส่วนที่เป็น ASSUMPTION ระบุไว้
- ยอดขาย: simulate รายชั่วโมงภายใน แล้วสรุปเป็นรายวัน
- ยอดคงเหลือวันที่ 15 ต.ค. ล็อกให้ตรงกับ inventory_lots (lot ที่ใช้ demo)

รัน: python3 simulate.py  -> data/daily_context.csv, data/product_daily.csv
"""
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

SEED = 20261016
rng = np.random.default_rng(SEED)

HIST_START, HIST_END = date(2026, 7, 12), date(2026, 10, 15)
CTX_END = date(2026, 10, 25)
WARMUP_START = date(2026, 6, 28)          # simulate ก่อนเพื่อให้มีสต็อกตั้งต้นสมจริง (ไม่บันทึก)
OPEN_HOURS = list(range(8, 22))            # 08:00-22:00 -> ชั่วโมงที่ 8..21

# ---------------------------------------------------------------- calendar (ข้อมูลจริง)
HOLIDAYS = {
    date(2026, 7, 28): "วันเฉลิมพระชนมพรรษา ร.10",
    date(2026, 7, 29): "วันอาสาฬหบูชา",
    date(2026, 7, 30): "วันเข้าพรรษา",
    date(2026, 8, 12): "วันแม่แห่งชาติ",
    date(2026, 9, 28): "วันหยุดราชการพิเศษ (อุทกภัย กทม.)",
    date(2026, 9, 29): "วันหยุดราชการพิเศษ (อุทกภัย กทม.)",
    date(2026, 10, 13): "วันนวมินทรมหาราช",
    date(2026, 10, 23): "วันปิยมหาราช",
}
GOV_PAYDAYS = [date(2026, 6, 16), date(2026, 6, 25), date(2026, 7, 16), date(2026, 7, 23),
               date(2026, 8, 14), date(2026, 8, 26), date(2026, 9, 16), date(2026, 9, 25),
               date(2026, 10, 16), date(2026, 10, 27)]
PENSION_DAYS = [date(2026, 6, 23), date(2026, 7, 21), date(2026, 8, 24), date(2026, 9, 23),
                date(2026, 10, 22)]


def is_off(d):
    return d.weekday() >= 5 or d in HOLIDAYS


def last_working_day(y, m):
    d = date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)
    while is_off(d):
        d -= timedelta(days=1)
    return d


PRIVATE_PAYDAYS = [last_working_day(2026, m) for m in (6, 7, 8, 9, 10)]   # ASSUMPTION
ALL_PAYDAYS = sorted(set(GOV_PAYDAYS + PENSION_DAYS + PRIVATE_PAYDAYS))


def off_run_length(d):
    """ความยาวช่วงวันหยุดต่อเนื่องที่ d อยู่ (0 ถ้าเป็นวันทำงาน)"""
    if not is_off(d):
        return 0
    a = b = d
    while is_off(a - timedelta(days=1)):
        a -= timedelta(days=1)
    while is_off(b + timedelta(days=1)):
        b += timedelta(days=1)
    return (b - a).days + 1


# ---------------------------------------------------------------- weather (ข้อมูลจริง)
def load_weather():
    out = {}
    for fn in ("data/weather_archive.json", "data/weather_forecast.json"):
        w = json.load(open(fn))
        eve = defaultdict(float)
        for t, v in zip(w["hourly"]["time"], w["hourly"]["precipitation"]):
            if 16 <= int(t[11:13]) < 20:
                eve[t[:10]] += v or 0.0
        dd = w["daily"]
        for t, tmax, tmin, p in zip(dd["time"], dd["temperature_2m_max"], dd["temperature_2m_min"], dd["precipitation_sum"]):
            out[date.fromisoformat(t)] = dict(rain_mm=round(p, 1), rain_mm_16_20=round(eve[t], 1),
                                              temp_max_c=tmax, temp_min_c=tmin)
    return out


WEATHER = load_weather()
DRY = dict(rain_mm=0.0, rain_mm_16_20=0.0, temp_max_c=33.0, temp_min_c=25.0)   # ใช้เฉพาะช่วง warmup ก่อน 12 ก.ค.


def build_context():
    rows = []
    d = HIST_START
    while d <= CTX_END:
        last_pay = max(p for p in ALL_PAYDAYS if p <= d)
        w = WEATHER[d]
        rows.append(dict(
            context_date=d.isoformat(), dow=d.isoweekday(), is_weekend=d.weekday() >= 5,
            is_public_holiday=d in HOLIDAYS, holiday_name=HOLIDAYS.get(d, ""),
            is_long_weekend_day=off_run_length(d) >= 3,
            is_pension_day=d in PENSION_DAYS, is_private_payday=d in PRIVATE_PAYDAYS,
            days_since_any_payday=(d - last_pay).days, **w))
        d += timedelta(days=1)
    return rows


# ---------------------------------------------------------------- products
@dataclass
class Product:
    pid: str
    category: str
    price: float
    shelf: int            # shelf_life_days
    mean_daily: float     # ค่าเฉลี่ยยอดขายทั้งวันจาก sales_history เดิม (วันที่ไม่ลดราคา)
    supply: str           # SUPPLIER / IN_HOUSE
    delivery_dow: tuple   # ISO dow ที่รับของ
    case_pack: int = 1    # สั่งได้ทีละลัง (ASSUMPTION)


DAILY = (1, 2, 3, 4, 5, 6, 7)
PRODUCTS = [
    Product("DAI-001", "DAIRY", 47.50, 9, 31.4, "SUPPLIER", (2, 5), 12),
    Product("DAI-002", "DAIRY", 14.50, 28, 27.5, "SUPPLIER", (2, 5), 24),
    Product("MEA-001", "MEAT", 44.50, 4, 22.0, "SUPPLIER", DAILY, 10),
    Product("MEA-002", "MEAT", 130.00, 6, 6.6, "SUPPLIER", (1, 3, 5), 5),
    Product("SEA-001", "SEAFOOD", 115.50, 2, 8.8, "SUPPLIER", (1, 3, 5), 5),
    Product("PRO-001", "PRODUCE", 35.00, 5, 18.7, "SUPPLIER", DAILY, 10),
    Product("PRO-002", "PRODUCE", 23.75, 4, 13.1, "SUPPLIER", DAILY, 12),
    Product("BAK-001", "BAKERY", 40.00, 4, 23.0, "SUPPLIER", DAILY, 12),
    Product("BAK-002", "BAKERY", 179.00, 3, 5.7, "SUPPLIER", DAILY, 4),
    Product("BAK-003", "BAKERY", 35.00, 3, 10.6, "IN_HOUSE", DAILY),
    Product("RTE-001", "READY_TO_EAT", 169.00, 0, 8.0, "IN_HOUSE", DAILY),
    Product("RTE-002", "READY_TO_EAT", 59.00, 1, 16.4, "IN_HOUSE", DAILY),
    Product("RTE-003", "READY_TO_EAT", 109.00, 0, 11.0, "IN_HOUSE", DAILY),
    Product("RTE-004", "READY_TO_EAT", 65.00, 0, 12.9, "IN_HOUSE", DAILY),
]

# lot ใน inventory_lots ที่ demo ใช้ (วันที่หลังแก้ใน A5: วัน demo = 16 ต.ค.)
# (product, lot_id, received, initial, current)
TRACKED = [
    ("SEA-001", "LOT-000006", date(2026, 10, 14), 30, 12),
    ("DAI-002", "LOT-000003", date(2026, 9, 19), 200, 45),
    ("MEA-001", "LOT-000004", date(2026, 10, 13), 60, 18),
    ("PRO-001", "LOT-000007", date(2026, 10, 12), 100, 32),
    ("MEA-002", "LOT-000005", date(2026, 10, 11), 30, 14),
    ("BAK-002", "LOT-000010", date(2026, 10, 14), 16, 11),
    ("BAK-001", "LOT-000009", date(2026, 10, 13), 100, 42),
    ("PRO-002", "LOT-000008", date(2026, 10, 14), 60, 36),
    ("DAI-001", "LOT-000001", date(2026, 10, 9), 180, 85),
    ("DAI-001", "LOT-000002", date(2026, 10, 15), 180, 172),
]

# ---------------------------------------------------------------- demand model (ASSUMPTION ทั้งหมด ยกเว้นที่ระบุ)
# สัดส่วนลูกค้ารายชั่วโมง 08..21 พีคบ่ายถึงค่ำ 15:00-20:00
HOUR_PROFILE = np.array([.03, .05, .06, .07, .08, .07, .06, .07, .08, .10, .11, .10, .07, .05])
HOUR_PROFILE /= HOUR_PROFILE.sum()
EVENING = [h for h in OPEN_HOURS if 16 <= h < 20]

# วันในสัปดาห์: วัดจาก sales_history เดิม (จ-พฤ ~13.5, ศ 13.9, ส 16.2, อา 16.7)
DOW_FACTOR = {1: 1.00, 2: 0.99, 3: 0.99, 4: 1.01, 5: 1.03, 6: 1.20, 7: 1.23}
DOW_FACTOR_RTE = {1: 1.00, 2: 1.00, 3: 1.00, 4: 1.00, 5: 1.02, 6: 1.08, 7: 1.10}   # เดลี่พึ่งคนทำงาน
NB_VAR_TO_MEAN = 1.5          # วัดจากข้อมูลเดิม (1.0-2.3)
MARKDOWN_LIFT = {30: 1.30, 50: 1.70}   # วัดจากข้อมูลเดิม: ลด 20-30% ยอดทั้งวัน x1.15-1.35, ลด 50% x1.4-1.9
PICK_NEWEST_SHARE = 0.40     # ลูกค้าบางส่วนเลือกหยิบของที่ใหม่กว่า (ASSUMPTION) ทำให้ lot เก่าค้างและหมดอายุได้

FLOOD = {   # ข่าวน้ำท่วม กทม. 25-28 ก.ย. 2569: คนเร่งซื้อของเข้าบ้าน, ถนนน้ำท่วม
    date(2026, 9, 24): {"DAIRY": 1.10, "BAKERY": 1.10, "PRODUCE": 1.10},
    date(2026, 9, 26): {"DAIRY": 1.20, "BAKERY": 1.20, "PRODUCE": 1.15, "MEAT": 0.90, "SEAFOOD": 0.85, "READY_TO_EAT": 0.75},
    date(2026, 9, 27): {"DAIRY": 1.35, "BAKERY": 1.35, "PRODUCE": 1.25, "MEAT": 1.00, "SEAFOOD": 0.85, "READY_TO_EAT": 0.75},
    date(2026, 9, 28): {"DAIRY": 1.10, "BAKERY": 1.10, "PRODUCE": 1.10, "READY_TO_EAT": 0.85},
}
DISPLAY_DAYS = {"BAK-002": 1.5, "BAKERY": 3.0, "PRODUCE": 2.5, "MEAT": 1.8}   # สต็อกขั้นต่ำบนชั้น = กี่วันของยอดขาย
NO_SUPPLIER_DELIVERY = {date(2026, 9, 26), date(2026, 9, 27)}   # รถส่งของเข้าไม่ได้ (ASSUMPTION จากข่าวถนนน้ำท่วม)
IN_HOUSE_CUT = {date(2026, 9, 26): 0.7, date(2026, 9, 27): 0.7}


def day_factor(p, d):
    f = (DOW_FACTOR_RTE if p.category == "READY_TO_EAT" else DOW_FACTOR)[d.isoweekday()]
    if d in HOLIDAYS and d.weekday() < 5:
        f *= 1.15 if p.category != "READY_TO_EAT" else 0.95
    if off_run_length(d) >= 3:
        f *= 0.95                              # คนออกต่างจังหวัดช่วงหยุดยาว
    nxt = d + timedelta(days=1)
    if not is_off(d) and off_run_length(nxt) >= 3:
        f *= 1.08                              # ซื้อตุนก่อนหยุดยาว
    since = (d - max(x for x in ALL_PAYDAYS if x <= d)).days
    f *= {0: 1.10, 1: 1.07, 2: 1.04}.get(since, 1.0)
    if since >= 12:
        f *= 0.95                              # ปลายรอบเงินเดือน
    f *= FLOOD.get(d, {}).get(p.category, 1.0)
    w = WEATHER.get(d, DRY)
    if w["rain_mm"] >= 50:
        f *= 0.88                              # ฝนหนักทั้งวัน
    return f


def hour_weights(d):
    """ฝนช่วงเย็นลดลูกค้าช่วง 16-20 (ทิศทางอ้างอิงงานวิจัยซูเปอร์มาร์เก็ตไต้หวัน ขนาดเป็น ASSUMPTION)"""
    w = HOUR_PROFILE.copy()
    r = WEATHER.get(d, DRY)["rain_mm_16_20"]
    cut = 0.65 if r >= 15 else 0.80 if r >= 5 else 0.92 if r >= 1 else 1.0
    for i, h in enumerate(OPEN_HOURS):
        if h in EVENING:
            w[i] *= cut
    return w


def expected_demand(p, d):
    base = p.mean_daily / 1.07                    # แปลงค่าเฉลี่ยรวมสุดสัปดาห์ -> ระดับวันธรรมดา
    return base * day_factor(p, d) * hour_weights(d).sum()


def draw_hourly(p, d):
    mu = expected_demand(p, d)
    k = mu / (NB_VAR_TO_MEAN - 1)
    total = rng.negative_binomial(k, k / (k + mu))
    w = hour_weights(d)
    return rng.multinomial(total, w / w.sum()), mu


# ---------------------------------------------------------------- inventory engine
@dataclass
class Lot:
    qty: int
    expiry: date
    tracked: str = ""     # lot_id ถ้าเป็น lot ใน inventory_lots


def simulate_product(p):
    tracked = [t for t in TRACKED if t[0] == p.pid]
    t0 = min((t[2] for t in tracked), default=None)
    # โควตาขายต่อวันของ lot ที่ track (initial - current กระจายตามยอดคาดการณ์)
    quota = defaultdict(lambda: defaultdict(int))
    for _, lot_id, rec, init, cur in tracked:
        days = [rec + timedelta(i) for i in range((HIST_END - rec).days + 1)]
        exp = np.array([expected_demand(p, x) for x in days])
        share = exp / exp.sum() * (init - cur)
        q = np.floor(share).astype(int)
        for i in np.argsort(-(share - q))[: (init - cur) - q.sum()]:
            q[i] += 1
        for x, v in zip(days, q):
            quota[x][lot_id] = int(v)

    lots: list[Lot] = []
    rows = []
    forecast_error = 0.0
    d = WARMUP_START
    while d <= HIST_END:
        opening = sum(l.qty for l in lots)
        received = 0
        # ---- supply
        for _, lot_id, rec, init, _ in tracked:
            if rec == d:
                lots.append(Lot(init, d + timedelta(p.shelf), lot_id))
                received += init
        is_delivery = d.isoweekday() in p.delivery_dow and not (p.supply == "SUPPLIER" and d in NO_SUPPLIER_DELIVERY)
        if is_delivery:
            # วันส่งของถัดไป
            nd = d + timedelta(1)
            while nd.isoweekday() not in p.delivery_dow:
                nd += timedelta(1)
            horizon_end = min(nd - timedelta(1), d + timedelta(p.shelf))
            if t0 is not None and d >= t0:
                horizon_end = min(horizon_end, HIST_END)
            elif t0 is not None and horizon_end >= t0:
                horizon_end = t0 - timedelta(1)        # ก่อน lot ใน inventory_lots เข้า: สั่งให้พอแค่ถึงวันก่อนหน้า
            if t0 is None or d < t0 or d <= HIST_END:
                need = sum(expected_demand(p, d + timedelta(i)) for i in range((horizon_end - d).days + 1))
                if t0 is not None:
                    need -= sum(sum(quota[d + timedelta(i)].values()) for i in range((horizon_end - d).days + 1))
                usable = sum(l.qty for l in lots if not l.tracked and l.expiry >= horizon_end)
                usable += sum(l.qty for l in lots if not l.tracked and d <= l.expiry < horizon_end) * 0.5
                # order-up-to: ค่าคาดการณ์ + safety stock (z x SD ของ NB) กันของขาด แลกกับของเหลือทิ้งบ้าง
                z = 0.25 if p.supply == "IN_HOUSE" else 0.5 if p.shelf <= 2 else 1.65
                target = need + z * math.sqrt(max(need, 0) * NB_VAR_TO_MEAN)
                # ชั้นต้องดูเต็ม (presentation stock) เป็นสาเหตุหลักของของเหลือทิ้งในของสด (ASSUMPTION)
                disp = DISPLAY_DAYS.get(p.pid, DISPLAY_DAYS.get(p.category, 0)) if p.supply == "SUPPLIER" else 1.5 if p.category == "BAKERY" else 0
                if t0 is None or d < t0 - timedelta(2):
                    target = max(target, disp * expected_demand(p, d))
                if t0 is not None and d >= t0:
                    target = need * 1.0                # ช่วงท้าย: สั่งพอดี ให้ lot นอก inventory_lots หมดก่อนวัน demo
                if p.supply == "SUPPLIER":
                    usable -= forecast_error           # สั่งล่วงหน้า 1 วัน: ยังไม่รู้ยอดขายจริงของเมื่อวาน
                q = max(0, int(round(target - usable)))
                if q and p.case_pack > 1:
                    q = int(math.ceil(q / p.case_pack) * p.case_pack)
                q = int(round(q * IN_HOUSE_CUT.get(d, 1.0))) if p.supply == "IN_HOUSE" else q
                if q > 0:
                    lots.append(Lot(q, d + timedelta(p.shelf)))
                    received += q
        lots.sort(key=lambda l: l.expiry)

        # ---- demand & sales (hourly)
        hourly, mu = draw_hourly(p, d)
        dq = dict(quota[d])
        hq = {lid: rng.multinomial(v, HOUR_PROFILE) for lid, v in dq.items()}
        md_pct = 0
        expiring_untracked = sum(l.qty for l in lots if not l.tracked and l.expiry == d)
        rest_expected = mu * HOUR_PROFILE[OPEN_HOURS.index(18):].sum()
        if expiring_untracked > 0:
            if p.category == "READY_TO_EAT" or expiring_untracked > 0.6 * rest_expected:
                md_pct = 30
        full = md = 0
        latent = 0
        stockout_hour = None
        for i, h in enumerate(OPEN_HOURS):
            want = int(hourly[i])
            tq = {lid: int(v[i]) for lid, v in hq.items()}
            want = max(want, sum(tq.values()))
            cur_md = md_pct
            if p.category == "READY_TO_EAT" and md_pct and h >= 20:
                left = sum(l.qty for l in lots if not l.tracked and l.expiry == d)
                if left > 0.5 * mu * HOUR_PROFILE[i:].sum():
                    cur_md = 50
            md_active = cur_md and h >= 18 and any(l.expiry == d and not l.tracked and l.qty for l in lots)
            if md_active:
                want = int(round(want * MARKDOWN_LIFT[cur_md] + rng.random() - 0.5))
                md_pct = max(md_pct, cur_md)
            latent += want
            # tracked quota first
            for l in lots:
                if l.tracked and tq.get(l.tracked):
                    take = min(l.qty, tq[l.tracked])
                    l.qty -= take
                    want -= take
                    full += take
            # untracked: markdown lot first after 18:00 then FIFO
            untracked = [l for l in lots if not l.tracked and l.qty]
            if md_active:
                order = sorted(untracked, key=lambda l: l.expiry != d)       # ป้ายลดราคาดึงลูกค้าไปก่อน
                newest_n = 0
            else:
                order = untracked
                newest_n = int(rng.binomial(max(want, 0), PICK_NEWEST_SHARE)) if len(untracked) > 1 else 0
            if newest_n:
                nl = untracked[-1]
                take = min(nl.qty, newest_n)
                nl.qty -= take
                want -= take
                full += take
            for l in order:
                if want <= 0:
                    break
                take = min(l.qty, want)
                l.qty -= take
                want -= take
                if md_active and l.expiry == d:
                    md += take
                else:
                    full += take
            if want > 0:
                # lot อื่นหมดแล้วแต่ lot ที่ track ยังมีของ: ลูกค้าหยิบจาก lot นั้นแทน
                # แล้วหักออกจากโควตาวันท้ายๆ ให้ยอดรวมยังจบที่ current_quantity เท่าเดิม
                for l in lots:
                    if not l.tracked or want <= 0 or l.qty == 0:
                        continue
                    future = sorted((x for x in quota if x > d and quota[x].get(l.tracked)), reverse=True)
                    slack = sum(quota[x][l.tracked] for x in future)
                    take = min(want, l.qty, slack)
                    l.qty -= take
                    want -= take
                    full += take
                    for x in future:
                        if take == 0:
                            break
                        cut = min(take, quota[x][l.tracked])
                        quota[x][l.tracked] -= cut
                        take -= cut
            if want > 0:
                untracked_left = sum(l.qty for l in lots if not l.tracked)
                if untracked_left == 0 and not any(l.qty for l in lots):
                    if stockout_hour is None:
                        stockout_hour = h
                else:
                    latent -= want        # ยังมีของ (lot ที่ track) แต่โควตาครบแล้ว: ถือว่าไม่ใช่ demand ที่หาย
        sold = full + md
        forecast_error = sold - mu
        if stockout_hour is None:
            latent = sold
        # ---- 15 ต.ค.: lot นอก inventory_lots ที่ยังเหลือ -> ขายลดราคา 30% ช่วงค่ำ (เคลียร์ก่อนวัน demo)
        if d == HIST_END:
            for l in lots:
                if not l.tracked and l.qty and l.expiry > d:     # ของที่หมดอายุวันนี้ปล่อยให้เป็น waste ตามปกติ
                    md += l.qty
                    latent += l.qty
                    l.qty = 0
                    md_pct = max(md_pct, 30)
            sold = full + md
        # ---- waste at close
        waste = 0
        for l in lots:
            if l.expiry <= d and l.qty:
                assert not l.tracked or l.expiry > HIST_END, (p.pid, d)
                waste += l.qty
                l.qty = 0
        lots = [l for l in lots if l.qty > 0]
        closing = sum(l.qty for l in lots)
        if d >= HIST_START:
            rev = full * p.price + md * p.price * (1 - md_pct / 100)
            rows.append(dict(
                product_id=p.pid, sale_date=d.isoformat(), opening_qty=opening, received_qty=received,
                sold_qty=sold, sold_full_price_qty=full, markdown_sold_qty=md, waste_qty=waste,
                closing_qty=closing, is_stockout=stockout_hour is not None,
                stockout_hour=stockout_hour if stockout_hour is not None else "",
                markdown_pct=md_pct if md else 0, regular_price=f"{p.price:.2f}",
                avg_selling_price=f"{rev / sold:.2f}" if sold else "", latent_demand=max(latent, sold)))
        d += timedelta(1)

    # ---- ตรวจ lot ที่ track ตรงกับ inventory_lots
    end_tracked = {l.tracked: l.qty for l in lots if l.tracked}
    for _, lot_id, _, _, cur in tracked:
        assert end_tracked.get(lot_id) == cur, (p.pid, lot_id, end_tracked.get(lot_id), cur)
    assert all(l.tracked for l in lots), (p.pid, [l for l in lots if not l.tracked])
    return rows


def main():
    ctx = build_context()
    rows = [r for p in PRODUCTS for r in simulate_product(p)]
    for fn, data in (("data/daily_context.csv", ctx), ("data/product_daily.csv", rows)):
        with open(fn, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)
    print(f"daily_context {len(ctx)} rows, product_daily {len(rows)} rows")


if __name__ == "__main__":
    main()
