"""สร้างข้อมูล daily_context + product_daily สำหรับ No-Waste-Bro (prototype)

- อากาศ: Open-Meteo จริง (data/weather_archive.json + data/weather_forecast.json) พิกัด 13.75, 100.50
  ช่วงประวัติเริ่มตามไฟล์ archive (ยาวสุด 365 วันก่อน HIST_END) ดึงใหม่ด้วย python3 fetch_weather.py
- วันหยุด / วันเงินเดือน: ประกาศจริง (ดู CONFIG) ส่วนที่เป็น ASSUMPTION ระบุไว้
- ยอดขาย: simulate รายชั่วโมงภายใน แล้วสรุปเป็นรายวัน
- ยอดคงเหลือวันที่ 15 ต.ค. ล็อกให้ตรงกับ lot demo (data/inventory_lots_demo.csv)
- คอลัมน์ทุกตัวตรงกับตารางใน Supabase (product_daily, daily_context, inventory_lots)

v2 (ให้ข้อมูลพอเทรน Forecaster):
- ทดลองลดราคาแบบสุ่ม (MARKDOWN_TEST_*) ไม่ขึ้นกับยอดขายวันนั้น ทำให้วัดผลของการลด 20/30/50% ได้จากข้อมูลรายวัน
- RTE ผลิตพอขึ้น (safety stock สูงขึ้น) และลดราคาเมื่อเหลือเยอะจริง: ของหมดชั้น / วันลดราคาลดลง
- ตัดผลน้ำท่วมฝั่ง demand ออก (ไม่มีคอลัมน์ให้โมเดลเห็น) คงไว้แค่ฝั่ง supply ที่เห็นได้จาก received_qty / is_stockout
- lot demo มีครบทุกระดับความเสี่ยง รวม lot หมดอายุที่ยังค้างชั้น

v3.1:
- RTE รอบผลิตสุดท้ายผลิตพอถึง 20:00 (RTE_LAST_COVER_UNTIL) ของเสีย RTE 20.3% -> 11.3% ใกล้ deli ของ FMI (8.7%)
- ล็อต demo 004 / 007 / 009 มีของเหลือช่วงกลาง ให้ score กระจาย ไม่ใช่ 0 หรือ 40+ อย่างเดียว

รัน: python3 simulate.py  -> data/daily_context.csv, data/product_daily.csv, data/inventory_lots_demo.csv
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

HIST_END = date(2026, 10, 15)
CTX_END = date(2026, 10, 25)
MAX_HISTORY_DAYS = 365
OPEN_HOURS = list(range(8, 22))            # 08:00-22:00 -> ชั่วโมงที่ 8..21

# ---------------------------------------------------------------- calendar (ข้อมูลจริง)
HOLIDAYS = {
    # ต.ค. 2568 - มิ.ย. 2569: ปฏิทินวันหยุดราชการ (ตรงกับ python-holidays, Thailand)
    date(2025, 10, 13): "วันนวมินทรมหาราช",
    date(2025, 10, 23): "วันปิยมหาราช",
    date(2025, 12, 5): "วันพ่อแห่งชาติ",
    date(2025, 12, 10): "วันรัฐธรรมนูญ",
    date(2025, 12, 31): "วันสิ้นปี",
    date(2026, 1, 1): "วันขึ้นปีใหม่",
    date(2026, 1, 2): "วันหยุดพิเศษ (เพิ่มเติม)",
    date(2026, 3, 3): "วันมาฆบูชา",
    date(2026, 4, 6): "วันจักรี",
    date(2026, 4, 13): "วันสงกรานต์",
    date(2026, 4, 14): "วันสงกรานต์",
    date(2026, 4, 15): "วันสงกรานต์",
    date(2026, 5, 1): "วันแรงงานแห่งชาติ",
    date(2026, 5, 4): "วันฉัตรมงคล",
    date(2026, 6, 1): "ชดเชยวันวิสาขบูชา",
    date(2026, 6, 3): "วันเฉลิมพระชนมพรรษา พระราชินี",
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
REAL_PAY_CALENDAR_FROM = date(2026, 6, 1)   # ก่อนหน้านี้ไม่มีปฏิทินกรมบัญชีกลางในมือ ใช้กฎด้านล่างแทน


def is_off(d):
    return d.weekday() >= 5 or d in HOLIDAYS


def working_day_on_or_before(d):
    while is_off(d):
        d -= timedelta(days=1)
    return d


def last_working_day(y, m):
    d = date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)
    return working_day_on_or_before(d)


def months_between(a, b):
    y, m = a.year, a.month
    while (y, m) <= (b.year, b.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


PAY_MONTHS = list(months_between(date(2025, 9, 1), date(2026, 10, 1)))
for _y, _m in PAY_MONTHS:
    if date(_y, _m, 1) < REAL_PAY_CALENDAR_FROM:
        # ASSUMPTION: ข้าราชการรอบ 1 วันที่ 16, รอบ 2 วันที่ 25, บำนาญวันที่ 23 (เลื่อนเป็นวันทำการก่อนหน้า)
        GOV_PAYDAYS += [working_day_on_or_before(date(_y, _m, 16)), working_day_on_or_before(date(_y, _m, 25))]
        PENSION_DAYS.append(working_day_on_or_before(date(_y, _m, 23)))
GOV_PAYDAYS.sort()
PENSION_DAYS.sort()
PRIVATE_PAYDAYS = [last_working_day(y, m) for y, m in PAY_MONTHS]   # ASSUMPTION
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
DRY = dict(rain_mm=0.0, rain_mm_16_20=0.0, temp_max_c=33.0, temp_min_c=25.0)   # ใช้เฉพาะช่วง warmup ก่อนข้อมูลอากาศ

# ประวัติเริ่มวันแรกที่มีอากาศจริง (ไม่เกิน 365 วัน) warmup 14 วันก่อนหน้าไม่บันทึก
HIST_START = max(min(WEATHER), HIST_END - timedelta(days=MAX_HISTORY_DAYS - 1))
WARMUP_START = HIST_START - timedelta(days=14)   # simulate ก่อนเพื่อให้มีสต็อกตั้งต้นสมจริง (ไม่บันทึก)


def build_context():
    rows = []
    d = HIST_START
    while d <= CTX_END:
        last_pay = max(p for p in ALL_PAYDAYS if p <= d)
        w = WEATHER[d]
        rows.append(dict(
            context_date=d.isoformat(), dow=d.isoweekday(), is_weekend=d.weekday() >= 5,
            is_public_holiday=d in HOLIDAYS,      # ชื่อวันหยุดอยู่ใน HOLIDAYS (ไม่มีคอลัมน์ใน daily_context)
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
    Product("SEA-001", "SEAFOOD", 115.50, 2, 8.8, "SUPPLIER", DAILY, 5),        # ปลาสดส่งทุกวัน (อายุ 2 วัน)
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

# lot ใน inventory_lots ที่ demo ใช้ (วัน demo = 16 ต.ค.) ออกแบบให้ Risk Scanner ได้ครบทุกระดับ
# จำนวนคงเหลือเทียบกับยอดขายคาดการณ์ถึงวันหมดอายุ (ระดับที่คาดไว้ในวงเล็บ)
# (product, lot_id, received, initial, current)
TRACKED = [
    ("SEA-001", "LOT-000006", date(2026, 10, 14), 30, 20),     # หมดอายุวันนี้ ของเหลือเยอะ (HIGH/CRITICAL)
    ("DAI-002", "LOT-000003", date(2026, 9, 19), 200, 45),     # (LOW)
    # v3.1: 004 / 007 / 009 เพิ่มของคงเหลือให้ score อยู่ช่วงกลาง (เดิมขายหมด score 0 ทุกตัว)
    ("MEA-001", "LOT-000004", date(2026, 10, 13), 80, 58),     # เหลือราว 1 ใน 4 (score ~25)
    ("PRO-001", "LOT-000007", date(2026, 10, 12), 100, 50),    # เหลือราว 1 ใน 5 (score ~15-20)
    ("MEA-002", "LOT-000005", date(2026, 10, 11), 40, 24),     # (MEDIUM)
    ("BAK-002", "LOT-000010", date(2026, 10, 14), 26, 22),     # (MEDIUM)
    ("BAK-001", "LOT-000009", date(2026, 10, 13), 100, 70),    # เหลือราว 1 ใน 3 (score ~30-35)
    ("PRO-002", "LOT-000008", date(2026, 10, 14), 120, 90),    # (HIGH)
    ("DAI-001", "LOT-000001", date(2026, 10, 9), 220, 150),    # หมดอายุก่อน ได้ demand ก่อนแบบ FIFO (MEDIUM)
    ("DAI-001", "LOT-000002", date(2026, 10, 15), 180, 172),   # (LOW)
    ("BAK-003", "LOT-000011", date(2026, 10, 14), 70, 55),     # ขนมปังพุดดิ้งจากครัว (HIGH)
    ("RTE-002", "LOT-000012", date(2026, 10, 15), 40, 30),     # สลัดอกไก่ หมดอายุวันนี้ (HIGH/CRITICAL)
    ("BAK-001", "LOT-000013", date(2026, 10, 11), 60, 8),      # หมดอายุ 15 ต.ค. แต่ยังค้างชั้น (CRITICAL, ช่องทางกำจัด)
]
# lot หมดอายุที่ยังไม่ถูกเก็บออกจากชั้น (ไม่นับเป็น waste ใน product_daily) ใช้ demo ช่องทางอาหารสัตว์/ปุ๋ยหมัก
EXPIRED_ON_SHELF = {"LOT-000013"}
# ตำแหน่งชั้นของ lot (lot เดิมตรงกับ inventory_lots)
LOT_LOCATION = {
    "LOT-000001": ("CHILL-A", "A-01"), "LOT-000002": ("CHILL-A", "A-01"), "LOT-000003": ("CHILL-A", "A-03"),
    "LOT-000004": ("MEAT-B", "B-01"), "LOT-000005": ("MEAT-B", "B-02"), "LOT-000006": ("SEAFOOD-C", "C-01"),
    "LOT-000007": ("PRODUCE-D", "D-04"), "LOT-000008": ("PRODUCE-D", "D-02"), "LOT-000009": ("BAKERY-E", "E-01"),
    "LOT-000010": ("BAKERY-E", "E-05"), "LOT-000011": ("BAKERY-E", "E-03"), "LOT-000012": ("DELI-F", "F-02"),
    "LOT-000013": ("BAKERY-E", "E-01"),
}
BASE_COST = {"DAI-001": 38.95, "DAI-002": 11.89, "MEA-001": 33.38, "MEA-002": 97.50, "SEA-001": 83.16,
             "PRO-001": 24.50, "PRO-002": 16.63, "BAK-001": 32.00, "BAK-002": 65.19, "BAK-003": 11.99,
             "RTE-001": 59.04, "RTE-002": 20.80, "RTE-003": 36.46, "RTE-004": 22.80}   # = products.base_cost

# ---------------------------------------------------------------- demand model (ASSUMPTION ทั้งหมด ยกเว้นที่ระบุ)
# สัดส่วนลูกค้ารายชั่วโมง 08..21 พีคบ่ายถึงค่ำ 15:00-20:00
HOUR_PROFILE = np.array([.03, .05, .06, .07, .08, .07, .06, .07, .08, .10, .11, .10, .07, .05])
HOUR_PROFILE /= HOUR_PROFILE.sum()
EVENING = [h for h in OPEN_HOURS if 16 <= h < 20]

# วันในสัปดาห์: วัดจาก sales_history เดิม (จ-พฤ ~13.5, ศ 13.9, ส 16.2, อา 16.7)
DOW_FACTOR = {1: 1.00, 2: 0.99, 3: 0.99, 4: 1.01, 5: 1.03, 6: 1.20, 7: 1.23}
DOW_FACTOR_RTE = {1: 1.00, 2: 1.00, 3: 1.00, 4: 1.00, 5: 1.02, 6: 1.08, 7: 1.10}   # เดลี่พึ่งคนทำงาน
NB_VAR_TO_MEAN = 1.5          # วัดจากข้อมูลเดิม (1.0-2.3)
# ยอดขายเพิ่มขึ้นกี่เท่าในชั่วโมงที่ลดราคา: ความยืดหยุ่นต่อราคา 0.6 / 0.67 / 0.7
# อยู่ในช่วงที่งานทบทวน 160 การศึกษารายงาน (0.27-0.81, เนื้อสัตว์ 0.7-0.8: Andreyeva et al. 2010, AJPH)
MARKDOWN_LIFT = {20: 1.12, 30: 1.20, 50: 1.35}
PICK_NEWEST_SHARE = 0.40     # ลูกค้าบางส่วนเลือกหยิบของที่ใหม่กว่า (ASSUMPTION) ทำให้ lot เก่าค้างและหมดอายุได้

# ทดลองลดราคา (ASSUMPTION): บางวันสุ่มลดของทั้งชั้นตั้งแต่เปิดร้าน ต่อเนื่อง 1-3 วัน ไม่ขึ้นกับยอดขาย
# เป็นการทดลองแบบที่ห้างทำจริง (A/B test ราคา) ทำให้วัดผล "ลดทั้งวัน" ของแต่ละระดับได้โดยตรง
MARKDOWN_TEST_START_RATE = 0.06    # โอกาสเริ่มรอบทดลองในแต่ละวัน (เฉลี่ย 2 วัน/รอบ -> ราว 12% ของวัน)
MARKDOWN_TEST_DAYS = (1, 2, 3)
MARKDOWN_TEST_DEPTHS = (20, 30, 50)
# RTE ลดราคาเป็นขั้นตามของที่เหลือ เทียบกับยอดที่คาดว่าจะขายได้ถึงปิดร้าน (ห้างจริงลดเป็นขั้น หนักขึ้นช่วงค่ำ)
# (ชั่วโมง, % ลด, เริ่มลดเมื่อของเหลือ > สัดส่วนนี้ของยอดที่คาดว่าจะขายได้ที่เหลือ)
RTE_CLEARANCE_STAGES = ((20, 50, 0.5), (18, 30, 0.8), (16, 20, 1.2))
OTHER_CLEARANCE = (18, 30, 0.6)    # หมวดอื่น: ลด 30% หลัง 18:00 ถ้าของที่หมดอายุวันนี้ยังเหลือเยอะ
# ครัวผลิต RTE หลายรอบต่อวัน: แต่ละรอบผลิตพอถึงรอบถัดไป ตามยอดที่ขายไปจริง (ลดทั้งของขาดและของทิ้ง)
RTE_TOPUP_HOURS = (11, 14, 17)
# v3.1: รอบสุดท้าย (17:00) ผลิตพอถึง 20:00 เท่านั้น หลังจากนั้นขายของที่เหลือ + ลดราคาเคลียร์ (ไม่ผลิตเพิ่มช่วงก่อนปิดร้าน)
# เดิมผลิตพอถึงปิดร้าน -> safety stock ของรอบสุดท้ายกลายเป็นของทิ้งเกือบทุกวัน (ของเสีย RTE 20.3% vs deli 8.7% ของ FMI)
# ผล (seed เดิม): ของเสีย RTE 20.3% -> 11.3%, ความต้องการที่ขายไม่ได้เพราะของหมด 2.8% -> 5.8% (ส่วนใหญ่หลัง 19:00)
# สินค้าขายวันละ 8-16 ชิ้นอายุ 0 วัน: ลดของทิ้งต่ำกว่านี้ต้องยอมให้ของหมดชั้นเพิ่มมาก (newsvendor trade-off)
RTE_LAST_COVER_UNTIL = 20
# safety stock (z x SD ของ NB) ปรับให้ของหมดชั้นราว 5-10% ใกล้ค่าเฉลี่ยค้าปลีกราว 8% (Gruen & Corsten)
# RTE ขายวันละ 9-16 ชิ้น อายุ 0-1 วัน: ลดของขาดได้เท่าไรของทิ้งก็เพิ่มเท่านั้น เลือกจุดกลาง (หมดชั้น ~20%, ทิ้ง ~20%)
IN_HOUSE_Z = {"READY_TO_EAT": 1.5, "BAKERY": 0.5}
SUPPLIER_Z = {"DAIRY": 0.5, "MEAT": 0.4, "PRODUCE": 0.3, "BAKERY": 0.8, "SEAFOOD": 1.6}
# ของเสียจากความเสียหาย/คุณภาพ (waste_qty = หมดอายุ + เสียหาย) ต่อวัน ต่อหน่วยที่อยู่บนชั้น (ASSUMPTION)
# ปรับให้ของทิ้งรวมใกล้ shrink รายแผนกของ FMI (bakery 8.5%, seafood 7.6%, meat 5.7%) ซึ่งรวมการขโมยด้วย จึงตั้งต่ำกว่าเล็กน้อย
DAMAGE_RATE = {"PRODUCE": 0.030, "BAKERY": 0.020, "MEAT": 0.025, "SEAFOOD": 0.020, "DAIRY": 0.010,
               "READY_TO_EAT": 0.0}

DISPLAY_DAYS = {"BAK-002": 1.5, "BAKERY": 3.5, "PRODUCE": 1.5, "MEAT": 2.5, "SEAFOOD": 1.5}   # สต็อกขั้นต่ำบนชั้น = กี่วันของยอดขาย
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
    uid: str = ""         # รหัสภายใน (บันทึกผลรายล็อตใน lot_daily.csv)
    received: date = None


LOT_DAILY = []            # ล็อต x วัน: ของคงเหลือตอนเปิดร้าน (ใช้ปรับเกณฑ์ risk ไม่โหลดเข้า Supabase)
LOT_OUTCOME = {}          # ล็อต: รับเข้า / ขายได้ / เสียหาย / หมดอายุทิ้ง


def _new_lot(p, qty, d, counter):
    counter[0] += 1
    uid = f"{p.pid}-{counter[0]:05d}"
    LOT_OUTCOME[uid] = dict(lot_uid=uid, product_id=p.pid, received_date=d.isoformat(),
                            expiration_date=(d + timedelta(p.shelf)).isoformat(), initial_qty=qty,
                            sold_qty=0, damage_qty=0, expired_qty=0)
    return Lot(qty, d + timedelta(p.shelf), "", uid, d)


def _sell(lot, n, out_key="sold_qty"):
    if lot.uid:
        LOT_OUTCOME[lot.uid][out_key] += n


def clearance_depth(p, h, left, rest):
    """% ลดของล็อตที่หมดอายุวันนี้ ตามชั่วโมงและของที่เหลือเทียบกับยอดที่คาดว่าจะขายได้ถึงปิดร้าน"""
    if left <= 0:
        return 0
    stages = RTE_CLEARANCE_STAGES if p.category == "READY_TO_EAT" else (OTHER_CLEARANCE,)
    for hour, depth, ratio in stages:              # เรียงจากค่ำไปบ่าย: ใช้ขั้นที่ลึกที่สุดที่เข้าเงื่อนไข
        if h >= hour and left > ratio * rest:
            return depth
    return 0


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

    rte = p.category == "READY_TO_EAT"
    morning_share = HOUR_PROFILE[:OPEN_HOURS.index(RTE_TOPUP_HOURS[0])].sum()
    counter = [0]
    lots: list[Lot] = []
    rows = []
    forecast_error = 0.0
    test_left, test_depth = 0, 0
    d = WARMUP_START
    while d <= HIST_END:
        opening = sum(l.qty for l in lots)
        received = 0
        free_period = t0 is None or d < t0 - timedelta(3)      # ช่วงที่ไม่มี lot demo บนชั้น
        # ---- วันทดลองลดราคา: สุ่มก่อนรู้ยอดขาย ไม่ทดลองช่วงที่ lot demo อยู่บนชั้น
        test_md = 0
        if not rte and free_period:
            if test_left == 0 and rng.random() < MARKDOWN_TEST_START_RATE:
                test_left = int(rng.choice(MARKDOWN_TEST_DAYS))
                test_depth = int(rng.choice(MARKDOWN_TEST_DEPTHS))
            if test_left:
                test_md, test_left = test_depth, test_left - 1
        else:
            test_left = 0
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
            need = sum(expected_demand(p, d + timedelta(i)) for i in range((horizon_end - d).days + 1))
            if t0 is not None:
                need -= sum(sum(quota[d + timedelta(i)].values()) for i in range((horizon_end - d).days + 1))
            if rte and free_period:
                need *= morning_share                  # รอบเช้าผลิตพอถึงบ่าย ที่เหลือเติมตอน 14:00
            if test_md:
                need *= MARKDOWN_LIFT[test_md] + 0.1   # วันลดราคา: สั่งเผื่อ (ห้างสต็อกเพิ่มก่อนโปรโมชัน)
            usable = sum(l.qty for l in lots if not l.tracked and l.expiry >= horizon_end)
            usable += sum(l.qty for l in lots if not l.tracked and d <= l.expiry < horizon_end) * 0.5
            # order-up-to: ค่าคาดการณ์ + safety stock (z x SD ของ NB) กันของขาด แลกกับของเหลือทิ้งบ้าง
            z = IN_HOUSE_Z.get(p.category, 0.25) if p.supply == "IN_HOUSE" else SUPPLIER_Z[p.category]
            target = need + z * math.sqrt(max(need, 0) * NB_VAR_TO_MEAN)
            # ชั้นต้องดูเต็ม (presentation stock) เป็นสาเหตุหลักของของเหลือทิ้งในของสด (ASSUMPTION)
            disp = DISPLAY_DAYS.get(p.pid, DISPLAY_DAYS.get(p.category, 0)) if p.supply == "SUPPLIER" else 1.5 if p.category == "BAKERY" else 0
            if t0 is None or d < t0 - timedelta(2):
                target = max(target, disp * expected_demand(p, d))
            if t0 is not None and d >= t0:
                target = need * 1.0                    # ช่วงท้าย: สั่งพอดี ให้ lot นอก inventory_lots หมดก่อนวัน demo
            if p.supply == "SUPPLIER":
                usable -= forecast_error               # สั่งล่วงหน้า 1 วัน: ยังไม่รู้ยอดขายจริงของเมื่อวาน
            q = max(0, int(round(target - usable)))
            if q and p.case_pack > 1:
                q = int(math.ceil(q / p.case_pack) * p.case_pack)
            q = int(round(q * IN_HOUSE_CUT.get(d, 1.0))) if p.supply == "IN_HOUSE" else q
            if q > 0:
                lots.append(_new_lot(p, q, d, counter))
                received += q
        lots.sort(key=lambda l: l.expiry)
        if d >= HIST_START:
            for l in lots:
                if l.uid and l.qty:
                    LOT_DAILY.append(dict(lot_uid=l.uid, product_id=p.pid, date=d.isoformat(),
                                          opening_qty=l.qty, expiration_date=l.expiry.isoformat()))

        # ---- demand & sales (hourly)
        hourly, mu = draw_hourly(p, d)
        weights = hour_weights(d)
        dq = dict(quota[d])
        hq = {lid: rng.multinomial(v, HOUR_PROFILE) for lid, v in dq.items()}
        md_pct = 0
        full = md = 0
        rev = 0.0
        latent = 0
        stockout_hour = None
        for i, h in enumerate(OPEN_HOURS):
            rest = mu * weights[i:].sum() / weights.sum()          # ยอดที่คาดว่าจะขายได้ตั้งแต่ชั่วโมงนี้ถึงปิดร้าน
            if rte and free_period and h in RTE_TOPUP_HOURS and p.supply == "IN_HOUSE":
                # ผลิตพอถึงรอบถัดไป (รอบสุดท้าย: ถึงปิดร้าน)
                later = [x for x in RTE_TOPUP_HOURS if x > h]
                end = OPEN_HOURS.index(later[0]) if later else OPEN_HOURS.index(RTE_LAST_COVER_UNTIL)
                window = mu * weights[i:end].sum() / weights.sum()
                stock = sum(l.qty for l in lots if not l.tracked)
                z = IN_HOUSE_Z[p.category]
                q = int(round((window + z * math.sqrt(window * NB_VAR_TO_MEAN) - stock) * IN_HOUSE_CUT.get(d, 1.0)))
                if q > 0:
                    lots.append(_new_lot(p, q, d, counter))
                    received += q
                    lots.sort(key=lambda l: l.expiry)
            want = int(hourly[i])
            tq = {lid: int(v[i]) for lid, v in hq.items()}
            want = max(want, sum(tq.values()))
            expiring = sum(l.qty for l in lots if not l.tracked and l.expiry == d)
            clear = clearance_depth(p, h, expiring, rest) if not test_md else 0
            has_stock = any(not l.tracked and l.qty for l in lots)
            depth = test_md if (test_md and has_stock) else clear
            if depth:
                want = int(round(want * MARKDOWN_LIFT[depth] + rng.random() - 0.5))
                md_pct = max(md_pct, depth)
            latent += want
            # tracked quota first
            for l in lots:
                if l.tracked and tq.get(l.tracked):
                    take = min(l.qty, tq[l.tracked])
                    l.qty -= take
                    want -= take
                    full += take
                    rev += take * p.price
            # untracked: ล็อตที่ลดราคาก่อน (ป้ายลดราคาดึงลูกค้า) แล้ว FIFO
            untracked = [l for l in lots if not l.tracked and l.qty]
            discounted = (lambda l: True) if test_md else (lambda l: bool(clear) and l.expiry == d)
            if depth:
                order = sorted(untracked, key=lambda l: not discounted(l))
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
                rev += take * p.price
                _sell(nl, take)
            for l in order:
                if want <= 0:
                    break
                take = min(l.qty, want)
                l.qty -= take
                want -= take
                _sell(l, take)
                if depth and discounted(l):
                    md += take
                    rev += take * p.price * (1 - depth / 100)
                else:
                    full += take
                    rev += take * p.price
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
                    rev += take * p.price
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
                    rev += l.qty * p.price * 0.7
                    latent += l.qty
                    _sell(l, l.qty)
                    l.qty = 0
                    md_pct = max(md_pct, 30)
            sold = full + md
        # ---- waste at close: เสียหาย (สุ่มตามหมวด) + หมดอายุ
        waste = 0
        rate = DAMAGE_RATE.get(p.category, 0.0)
        for l in lots:
            if l.tracked or not l.qty:
                continue
            if rate and l.expiry > d:
                dmg = int(rng.binomial(l.qty, rate))
                if dmg:
                    l.qty -= dmg
                    waste += dmg
                    _sell(l, dmg, "damage_qty")
        for l in lots:
            if l.expiry <= d and l.qty:
                if l.tracked in EXPIRED_ON_SHELF:
                    continue                  # ยังไม่ถูกเก็บออกจากชั้น: ยังอยู่ใน inventory_lots
                assert not l.tracked or l.expiry > HIST_END, (p.pid, d)
                waste += l.qty
                _sell(l, l.qty, "expired_qty")
                l.qty = 0
        lots = [l for l in lots if l.qty > 0]
        closing = sum(l.qty for l in lots)
        if d >= HIST_START:
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


def demo_lots():
    """lot demo ในรูปแบบคอลัมน์ของ inventory_lots (ใช้แทนแถวเดิมตอนโหลดข้อมูลเข้า Supabase)"""
    shelf = {p.pid: p.shelf for p in PRODUCTS}
    price = {p.pid: p.price for p in PRODUCTS}
    rows = []
    for pid, lot_id, rec, init, cur in sorted(TRACKED, key=lambda t: t[1]):
        aisle, slot = LOT_LOCATION[lot_id]
        rows.append(dict(lot_id=lot_id, product_id=pid, received_date=rec.isoformat(),
                         expiration_date=(rec + timedelta(shelf[pid])).isoformat(),
                         initial_quantity=init, current_quantity=cur, unit_cost=f"{BASE_COST[pid]:.2f}",
                         location_aisle=aisle, location_shelf=slot,
                         current_selling_price=f"{price[pid]:.2f}", ai_status="IDLE"))
    return rows


def main():
    ctx = build_context()
    rows = [r for p in PRODUCTS for r in simulate_product(p)]
    print(f"history {HIST_START} -> {HIST_END}")
    outcome = [o for o in LOT_OUTCOME.values() if o["received_date"] >= (HIST_START - timedelta(days=30)).isoformat()]
    for fn, data in (("data/daily_context.csv", ctx), ("data/product_daily.csv", rows),
                     ("data/inventory_lots_demo.csv", demo_lots()),
                     ("data/lot_daily.csv", LOT_DAILY), ("data/lot_outcomes.csv", outcome)):
        with open(fn, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)
    print(f"daily_context {len(ctx)} rows, product_daily {len(rows)} rows, lot_daily {len(LOT_DAILY)} rows")


if __name__ == "__main__":
    main()
