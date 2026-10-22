"""PART 2-4 — กฎตรวจสอบ (pure functions ไม่แตะ DB / HTTP / solver) ทุกกฎคืน "รหัสเหตุผล" ให้ RAG อธิบายได้

PART 2  ก่อนเริ่ม     A*  lot ไหนต้องจัดการ / ข้อมูลเก่าไหม
PART 2  Markdown     K*  วันหมดอายุ, อนุญาตลดไหม, ระดับที่อนุญาต, ราคาต่ำสุด, ยอดขายที่ forecaster คาด, คุ้มไหม
PART 3  Partner      P*  วันรับ, ช่วงเวลารับ, หมวดสินค้า, อายุคงเหลือ ณ วันรับ, kg ขั้นต่ำ/สูงสุด, flag ของสินค้า
PART 4  Kitchen      U*  (ประกอบใน context.py) ใช้ helper เวลา/ชั่วโมงครัวในไฟล์นี้

รหัสทั้งหมด
  A0_STATUS_<s>        lot ไม่ได้อยู่สถานะ PROCESSING (CHECKED = มี task แล้ว, IDLE = ถูกปล่อยกลับไปสแกนใหม่)
  A0_ALREADY_DECIDED   assessment นี้มี decision ในรอบนี้แล้ว (กันรันซ้ำแล้วบันทึกซ้ำ)
  A0_NO_STOCK          current_quantity = 0
  A0_UNKNOWN_PRODUCT   ไม่พบสินค้าใน products
  A1_STALE_*           จำนวน / วันหมดอายุ / ราคา เปลี่ยนไปหลัง Risk Scanner สแกน (เตือน ใช้ค่าปัจจุบัน)
  K0 หมดอายุแล้ว  K1 สินค้าห้ามลดราคา  K2 ราคาหลังลด < min_allowed_price  K3 ระดับไม่อยู่ในนโยบาย / forecaster ไม่ได้พยากรณ์
  K4 ราคาใน shelf ไม่ตรงราคาปัจจุบัน (คำนวณใหม่)  K5 ไม่เหลือเวลาขาย / ลดแล้วคาดว่าขายไม่ได้ (0% เก็บไว้ถ้ายังมีเวลาขาย)  K6 ลดมากขึ้นแต่ยอดขายที่คาดไม่เพิ่ม
  P1 flag allow_* ของสินค้า  P2 partner ไม่รับหมวดนี้  P3 ไม่ active / ไม่มีรอบรับใน max_pickup_wait_days
  P4 อายุคงเหลือ ณ วันรับ < min_days_before_expiry  P5 ของหมดอายุ (ห้ามบริจาคให้คนกิน)  P6 ความจุ partner ไม่พอ 1 หน่วย
  P7 (partner โหมด DEDICATED) รวมทุก lot ที่เข้าเกณฑ์ยังไม่ถึง min_kg_per_pickup  P8 ไม่มีน้ำหนักสินค้า
  P3/P4/P5 ของ partner โหมด BIN ตรวจที่เวลารับที่รวมเวลารอถังเต็มแล้ว (ช้าสุดที่คาด)
"""
from __future__ import annotations

import itertools
import math
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from ai_engine.optimizer.config import BKK
from ai_engine.optimizer.demand import expected_sold, survival_segments
from ai_engine.optimizer.models import FLAG_BY_TYPE

EPS = 1e-9


# ---------------------------------------------------------------- ทั่วไป
def money(x: float) -> float:
    """ปัดเป็นสตางค์แบบ half-up"""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def tier_price(price: float, discount_pct: float) -> float:
    """ราคาหลังลด = ราคาปัจจุบันของ lot x (1 - d/100) ปัดสตางค์ half-up"""
    exact = Decimal(str(price)) * (Decimal(100) - Decimal(str(discount_pct))) / Decimal(100)
    return float(exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def clean_pct(d: float):
    return int(d) if float(d).is_integer() else float(d)


def expiry_dt(expiration_date: date, cfg) -> datetime:
    return datetime.combine(expiration_date, cfg.expiry_cutoff, tzinfo=BKK)


def is_expired(lot, now: datetime, cfg) -> bool:
    return now > expiry_dt(lot.expiration_date, cfg)


def days_to_expiry(lot, on: date) -> int:
    return (lot.expiration_date - on).days


# ---------------------------------------------------------------- PART 2: ก่อนเริ่ม
def lot_skip_reasons(lot, product, decided: set, cfg) -> list:
    reasons = []
    if product is None:
        reasons.append("A0_UNKNOWN_PRODUCT")
    if lot.ai_status not in cfg.process_ai_statuses:
        reasons.append(f"A0_STATUS_{lot.ai_status}")
    if lot.assessment_id in decided:
        reasons.append("A0_ALREADY_DECIDED")
    if lot.quantity <= 0:
        reasons.append("A0_NO_STOCK")
    return reasons


def stale_notes(lot, reference_date: date) -> list:
    notes = []
    if lot.quantity != lot.quantity_assessed:
        notes.append(f"A1_STALE_QTY {lot.quantity_assessed}->{lot.quantity}")
    if days_to_expiry(lot, reference_date) != lot.days_to_expiry_assessed:
        notes.append(f"A1_STALE_EXPIRY assessed {lot.days_to_expiry_assessed}d, now "
                     f"{days_to_expiry(lot, reference_date)}d (DEMO_DATE ของ server ตรงกับวันที่สแกนไหม?)")
    return notes


# ---------------------------------------------------------------- PART 2: Markdown
def sell_end(lot, cfg) -> datetime:
    """เวลาที่หมดโอกาสขาย = ร้านปิดของวันหมดอายุ (ไม่เกินเวลาหมดอายุ) ของที่เหลือหลังจากนี้ไปทางกำจัด end-of-life"""
    close = datetime.combine(lot.expiration_date, cfg.store_close, tzinfo=BKK)
    return min(close, expiry_dt(lot.expiration_date, cfg))


def markdown_tiers(lot, product, rows: list, now: datetime, cfg) -> tuple[list, dict, list]:
    """แปลงแถว demand (demand.lot_curve) เป็นระดับราคาที่เลือกได้ -> (tiers, excluded, notes)
    1 lot มีราคาเดียว: tier 0 = ขายราคาปัจจุบัน, tier d > 0 = ลด d%
    segments = [(ความกว้าง, โอกาสขายออก)] จาก quantile P10/P50/P90 (demand.survival_segments) ตัดไม่เกินจำนวนใน lot
    expected_sold = ยอดที่คาดว่าขายได้ถ้าวางทั้ง lot บนชั้นที่ราคานั้น"""
    if is_expired(lot, now, cfg):
        return [], {"MARKDOWN:ALL": ["K0_EXPIRED"]}, []
    tiers, excluded, notes, best = [], {}, [], 0.0
    for row in sorted(rows, key=lambda r: r["discount_pct"]):
        d = clean_pct(row["discount_pct"])
        key, reasons = f"MARKDOWN:{d}", []
        price = tier_price(lot.price, d)
        if abs(price - row["price"]) > 0.011:
            notes.append(f"K4_PRICE_CHANGED {d}%: shelf {row['price']} -> {price}")
        if d > 0 and not product.allow_markdown:
            reasons.append("K1_MARKDOWN_NOT_ALLOWED")
        if d > 0 and d not in cfg.allowed_discounts:
            reasons.append("K3_LEVEL_NOT_IN_POLICY")
        if d > 0 and product.min_price is not None and price < product.min_price - EPS:
            reasons.append("K2_BELOW_MIN_PRICE")
        segments = survival_segments(row["expected"], row["low"], row["high"], limit=float(lot.quantity))
        sold = expected_sold(segments, lot.quantity)
        # ราคาปัจจุบัน (0%) ไม่ตัดทิ้งตราบที่ยังมีเวลาขาย: วางไว้บนชั้นไม่มีต้นทุนเพิ่ม ของเหลือไปทาง end-of-life
        # ไม่งั้น solver ไม่มีทางเลือก "วางขายต่อ" ต้องดึงของออกตอนเช้าทั้งที่ยังขายเกินที่คาดได้ (หรือถูกบังคับให้ลดราคา)
        if sold < 0.05 and (d > 0 or now >= sell_end(lot, cfg)):
            reasons.append("K5_NO_SALES_EXPECTED")
        if reasons:
            excluded[key] = reasons
            continue
        if tiers and sold <= best + 0.05:
            excluded[key] = [f"K6_NO_EXTRA_SALES expected {sold:.2f} <= {best:.2f}"]
            continue
        best = sold
        # รายได้ที่ล็อตอื่นเสีย (เต็มราคา: ต้นทุนจมแล้ว) ค่ากำจัดของที่เหลือเพิ่มบวกใน context เมื่อรู้ทาง end-of-life
        lost = row["lost_sales"] if d > 0 else 0.0
        tiers.append({"discount_pct": d, "price": price, "segments": segments, "expected_sold": round(sold, 3),
                      "expected": round(row["expected"], 2), "low": round(row["low"], 2), "high": round(row["high"], 2),
                      "lost_units": round(lost, 3),
                      "lost_sales_cost": round(lost * product.regular_price * cfg.lost_sales_factor, 2)})
    for d in cfg.allowed_discounts:
        if f"MARKDOWN:{d}" not in excluded and all(t["discount_pct"] != d for t in tiers):
            excluded[f"MARKDOWN:{d}"] = ["K3_NOT_FORECAST"]
    return tiers, excluded, notes


# ---------------------------------------------------------------- PART 3: Partner
def next_pickup(partner, now: datetime, cfg, wait_days: float = 0.0,
                max_wait_days: Optional[float] = None) -> Optional[datetime]:
    """รอบรับของเร็วสุดสำหรับของที่ดึงออกตอนนี้: ต้องเตรียมของ lead_time_minutes ก่อน
    partner โหมด BIN: รอถังถึงปริมาณที่คุ้ม (wait_days) แต่ไม่เกินเพดานเวลา (max_wait_days) ดู bin_pickup"""
    return bin_pickup(partner, now + timedelta(minutes=cfg.lead_time_minutes), wait_days, max_wait_days, cfg)


def ceil_minute(t: datetime) -> datetime:
    """ปัดขึ้นเป็นนาทีเต็ม (เวลารอถังเต็มเป็นเศษวัน)"""
    exact = t.replace(second=0, microsecond=0)
    return exact if exact == t else exact + timedelta(minutes=1)


def eol_pickup(partner, lot, now: datetime, cfg, wait_days: float = 0.0,
               max_wait_days: Optional[float] = None) -> Optional[datetime]:
    """รอบรับของที่ขายไม่หมด: รอบแรกที่เริ่มได้หลังหมดเวลาขาย (sell_end + eol_lead_minutes) และไม่ก่อนรอบเตรียมของตอนนี้
    (โหมด BIN: + รอถังถึงปริมาณที่คุ้ม ไม่เกินเพดานเวลา)"""
    ready = max(sell_end(lot, cfg) + timedelta(minutes=cfg.eol_lead_minutes),
                now + timedelta(minutes=cfg.lead_time_minutes))
    return bin_pickup(partner, ready, wait_days, max_wait_days, cfg)


def bin_pickup(partner, ready: datetime, wait_days: float, max_wait_days: Optional[float], cfg) -> Optional[datetime]:
    """รอบรับของที่เข้าถังเวลา ready: รอบแรกหลังรอ wait_days (ถังถึงปริมาณที่คุ้ม)
    ถ้ารอบนั้นเกินเพดานเวลา (ready + max_wait_days) ใช้รอบสุดท้ายที่ยังไม่เกินเพดานแทน (เรียกรถก่อนของเกินเพดาน)"""
    slot = first_slot(partner, ceil_minute(ready + timedelta(days=wait_days)), cfg)
    if max_wait_days is None or not math.isfinite(max_wait_days):
        return slot
    deadline = ready + timedelta(days=max_wait_days)
    if slot is None or slot > deadline:
        slot = last_slot_by(partner, ready, deadline, cfg) or slot
    return slot


def last_slot_by(partner, ready: datetime, deadline: datetime, cfg) -> Optional[datetime]:
    """รอบรับช้าสุดที่ไม่ก่อน ready และไม่เกิน deadline (ไม่มี = None)"""
    best, slot = None, first_slot(partner, ready, cfg)
    while slot is not None and slot <= deadline:
        best = slot
        next_day = datetime.combine(slot.date() + timedelta(days=1), time(0, 0), tzinfo=BKK)
        slot = first_slot(partner, next_day, cfg)
    return best


def calls_per_week(pickup_days, max_gap_days: float) -> int:
    """จำนวนครั้งที่ต้องเรียกรถต่อสัปดาห์น้อยที่สุด: เรียกได้เฉพาะวันที่ partner มารับ และระยะห่างระหว่างวันที่เรียก
    (วนรอบสัปดาห์) ต้องไม่เกิน max_gap_days ถ้าตารางรับของ partner ห่างกว่านั้นอยู่แล้ว ใช้ระยะของตารางแทน"""
    days = sorted(pickup_days)
    if not days:
        return 0
    limit = max(max_gap_days, max_pickup_gap(days))
    for n in range(1, len(days) + 1):
        if any(max_pickup_gap(combo) <= limit + EPS for combo in itertools.combinations(days, n)):
            return n
    return len(days)


def max_pickup_gap(days) -> int:
    """ระยะห่างมากสุด (วัน) ระหว่างวันที่เรียงกันแบบวนสัปดาห์ (1 = จันทร์ .. 7 = อาทิตย์)"""
    days = list(days)
    return max((b - a) % 7 or 7 for a, b in zip(days, days[1:] + days[:1]))


def first_slot(partner, ready: datetime, cfg) -> Optional[datetime]:
    """รอบรับแรกที่ >= ready: วันต้องอยู่ใน pickup_days (1 = จันทร์ .. 7 = อาทิตย์) และเวลาอยู่ใน pickup_time_start-end
    ถ้าวันนั้นเลยช่วงแล้วเลื่อนไปวันรับถัดไป (ไม่เกิน max_pickup_wait_days)"""
    if partner.t_start is None or partner.t_end is None or not partner.pickup_days:
        return None
    for offset in range(cfg.max_pickup_wait_days + 1):
        day = ready.date() + timedelta(days=offset)
        if day.isoweekday() not in partner.pickup_days:
            continue
        start = datetime.combine(day, partner.t_start, tzinfo=BKK)
        end = datetime.combine(day, partner.t_end, tzinfo=BKK)
        if end < ready:
            continue
        return max(start, ready)
    return None


def partner_trip_cost(partner, cfg=None) -> float:
    """ต้นทุนต่อเที่ยว: Fixed Cost + Distance & Variable Cost (travel_cost_per_trip)
    DONATION ไม่มีค่าเดินทาง คิดแค่ fixed_cost_per_trip; trip_cost_mode = "scheduled" -> 0 (รถวิ่งรอบประจำอยู่แล้ว)"""
    if cfg is not None and cfg.trip_cost_mode == "scheduled":
        return 0.0
    return partner.fixed if partner.partner_type == "DONATION" else partner.fixed + partner.travel


def partner_min_kg(partner, cfg=None) -> float:
    """ขั้นต่ำต่อเที่ยว (scheduled: ของรอบนี้รวมกับขยะอื่นของร้านในเที่ยวประจำ ไม่บังคับขั้นต่ำ)"""
    if cfg is not None and cfg.trip_cost_mode == "scheduled":
        return 0.0
    return partner.min_kg


def partner_handling_per_kg(partner) -> float:
    """Weight x Handling Fee (DONATION ไม่มี)"""
    return 0.0 if partner.partner_type == "DONATION" else partner.handling


def partner_reasons(lot, product, partner, pickup: Optional[datetime], cap_kg: float, cfg, now: datetime) -> list:
    reasons = []
    flag = product.disposal.get(partner.partner_type)
    if flag is None and cfg.missing_flag_policy != "allow":
        reasons.append(f"P1_FLAG_MISSING_{FLAG_BY_TYPE[partner.partner_type].upper()}")
    elif flag is False:
        reasons.append(f"P1_FLAG_{FLAG_BY_TYPE[partner.partner_type].upper()}_FALSE")
    if product.category not in partner.categories:
        reasons.append(f"P2_CATEGORY_{product.category}_NOT_ACCEPTED")
    if not partner.active:
        reasons.append("P3_PARTNER_INACTIVE")
    if pickup is None:
        reasons.append("P3_NO_PICKUP_SLOT")
    else:
        left = (lot.expiration_date - pickup.date()).days
        if partner.min_days > 0 and left < partner.min_days:
            reasons.append(f"P4_MIN_DAYS {left}d at pickup < {partner.min_days}d")
        if partner.partner_type == "DONATION" and (is_expired(lot, now, cfg) or pickup > expiry_dt(lot.expiration_date, cfg)):
            reasons.append("P5_EXPIRED_FOR_HUMAN_USE")
    weight = product.weight_kg
    if weight is None:
        reasons.append("P8_NO_WEIGHT")
    elif cap_kg < weight - EPS:
        reasons.append("P6_NO_CAPACITY")
    return reasons


# ---------------------------------------------------------------- PART 4: Kitchen helper
def kitchen_due(day: date, cfg) -> datetime:
    """เวลาที่งานครัวของวันนั้นต้องเสร็จ = due_by (วันที่ของ due_by = วันที่ server จองชั่วโมงครัว)"""
    return datetime.combine(day, cfg.kitchen_due_time, tzinfo=BKK)


def kitchen_start(day: date, now: datetime, cfg) -> datetime:
    """เวลาที่ครัวเริ่มงานได้: วันนี้ = ตอนนี้ + kitchen_lead_minutes (ไม่ก่อนร้านเปิด), วันอื่น = store_open"""
    opening = datetime.combine(day, cfg.store_open, tzinfo=BKK)
    if day == now.date():
        return max(opening, now + timedelta(minutes=cfg.kitchen_lead_minutes))
    return opening


def kitchen_hours_budget(remaining_hrs: float, status: Optional[str], day: date, now: datetime, cfg) -> float:
    """ชั่วโมงครัวที่ใช้ได้จริง: FULL = 0, วันนี้จำกัดด้วยเวลาที่เหลือก่อน kitchen_due_time"""
    hours = 0.0 if status == "FULL" else max(0.0, remaining_hrs)
    if day == now.date():
        window = (kitchen_due(day, cfg) - (now + timedelta(minutes=cfg.kitchen_lead_minutes))).total_seconds() / 3600
        hours = min(hours, max(0.0, window))
    return 0.0 if day < now.date() else hours