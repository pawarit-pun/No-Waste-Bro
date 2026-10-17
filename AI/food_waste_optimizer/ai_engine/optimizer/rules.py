"""PART 2–4 — กฎตรวจสอบ (pure functions ไม่แตะ DB / solver)

PART 2  Markdown   : รหัส K*  (วันหมดอายุ, ราคาต่ำสุด, demand)
PART 3  Partner    : รหัส P*  (วันรับ, เวลารับ, หมวดสินค้า, อายุคงเหลือ, kg ขั้นต่ำ/สูงสุด, flag)
PART 4  Kitchen    : ฟังก์ชันช่วยเวลา/ชั่วโมงครัว (รหัส U* อยู่ใน context.py)

ทุกฟังก์ชันคืน "เหตุผลที่ถูกตัดออก" เป็นรหัสข้อความ เพื่อให้ RAG/ทีมอ่านแล้วรู้ว่าทำไม lot นี้ใช้วิธีนั้นไม่ได้
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from ai_engine.clock import BKK
from ai_engine.optimizer.models import FLAG_BY_TYPE

EPS = 1e-9


# ---------------------------------------------------------------- ช่วยทั่วไป
def money(x: float) -> float:
    """ปัดเศษเป็นสตางค์แบบ half-up (ไม่ใช้ banker's rounding)"""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def tier_price(price: float, discount_pct: float) -> float:
    """ราคาหลังลด = ราคาปัจจุบันของ lot × (1 − d/100) ตรงกับสูตรที่ server ใช้"""
    exact = Decimal(str(price)) * (Decimal(100) - Decimal(str(discount_pct))) / Decimal(100)
    return float(exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def expiry_dt(lot, cfg) -> datetime:
    return datetime.combine(lot.expiration_date, cfg.expiry_cutoff, tzinfo=BKK)


def days_to_expiry(lot, now: datetime) -> int:
    return (lot.expiration_date - now.date()).days


def is_expired(lot, now: datetime, cfg) -> bool:
    return now > expiry_dt(lot, cfg)


# ---------------------------------------------------------------- PART 2: Markdown
def markdown_tiers(lot, product, curve: list, now: datetime, cfg) -> tuple[list, dict]:
    """คืน (tier ที่ใช้ได้, เหตุผลที่ตัดออก)

    1 lot มีราคาเดียว -> เลือกได้ tier เดียว: tier 0 = ราคาปกติ, tier d>0 = ลด d%
    cap = จำนวนที่คาดว่าขายได้ที่ราคานั้น (ปรับด้วย kappa) ใช้เป็นเพดานการขาย
      K0 หมดอายุแล้ว                     K1 สินค้าไม่อนุญาต markdown
      K2 ราคาหลังลด < min_allowed_price   K3 ไม่มี demand ของระดับนี้
      K6 ขายได้ไม่มากกว่าระดับที่ลดน้อยกว่า (ลดแล้วไม่คุ้ม — โดนครอบงำ)
    """
    excluded: dict = {}
    if is_expired(lot, now, cfg):
        return [], {"MARKDOWN:ALL": ["K0_EXPIRED"]}
    by_discount = {c["discount_pct"]: c for c in curve}
    tiers, best_cap = [], -1
    for d in sorted(cfg.markdown_levels):
        reasons = []
        price = tier_price(lot.price, d)
        if d > 0 and not product.allow_markdown:
            reasons.append("K1_MARKDOWN_NOT_ALLOWED")
        if d > 0 and product.min_price is not None and price < product.min_price - EPS:
            reasons.append("K2_BELOW_MIN_PRICE")
        c = by_discount.get(d)
        if c is None:
            reasons.append("K3_NO_DEMAND_CURVE")
        if reasons:
            excluded[f"MARKDOWN:{d}"] = reasons
            continue
        expected = c["expected_qty"]
        low = c.get("low", expected)
        cap = int(min(lot.quantity, max(0, math.floor(expected - cfg.demand_kappa * (expected - low) + EPS))))
        if cap <= best_cap:
            excluded[f"MARKDOWN:{d}"] = ["K6_DOMINATED_NO_EXTRA_DEMAND"]
            continue
        best_cap = cap
        high = c.get("high", expected)
        tiers.append({"discount_pct": d, "price": price, "cap": cap,
                      "band_ratio": round((high - low) / expected, 3) if expected > 0 else 0.0})
    return tiers, excluded


# ---------------------------------------------------------------- PART 3: Partner
def next_pickup(partner, now: datetime, cfg) -> Optional[datetime]:
    """เวลารับของที่เร็วที่สุด: วันต้องอยู่ใน pickup_days (1=จันทร์..7=อาทิตย์) และอยู่ในช่วง
    pickup_time_start–end; ถ้าวันนี้หมดช่วงแล้วเลื่อนไปวันที่ partner เปิดรับถัดไป"""
    if partner.t_start is None or partner.t_end is None or not partner.pickup_days:
        return None
    ready = now + timedelta(minutes=cfg.lead_time_minutes)
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


def partner_trip_cost(partner) -> float:
    """Total Cost = Fixed + Distance/Variable(travel_cost_per_trip) + Weight × Handling
    ส่วนที่ต่อ 'เที่ยว' คือ Fixed + Travel; DONATION มีแค่ fixed_cost_per_trip (ไม่มีค่าเดินทาง)"""
    if partner.partner_type == "DONATION":
        return partner.fixed
    return partner.fixed + partner.travel


def partner_handling_per_kg(partner) -> float:
    """ค่า handling ต่อ kg (DONATION คิดแค่ fixed ตามคำสั่งงาน)"""
    return 0.0 if partner.partner_type == "DONATION" else partner.handling


def partner_reasons(lot, product, partner, pickup: Optional[datetime], cap_kg: float, cfg, now: datetime) -> list:
    """เหตุผลที่ lot นี้ส่งให้ partner นี้ไม่ได้ (ว่าง = ส่งได้)
      P1 flag ของสินค้า (allow_*)           P2 partner ไม่รับหมวดสินค้านี้
      P3 partner ไม่ active / ไม่มีรอบรับ    P4 อายุคงเหลือ ณ วันรับ < min_days_before_expiry
      P5 ของหมดอายุแล้ว (เฉพาะ DONATION)      P6 ความจุ partner ไม่พอแม้ 1 หน่วย
      P8 ไม่มีข้อมูลน้ำหนักสินค้า
    """
    reasons = []
    flag = product.disposal.get(partner.partner_type)
    if flag is None:
        if cfg.missing_flag_policy != "allow":
            reasons.append(f"P1_FLAG_UNKNOWN_{FLAG_BY_TYPE[partner.partner_type].upper()}")
    elif not flag:
        reasons.append(f"P1_FLAG_{FLAG_BY_TYPE[partner.partner_type].upper()}")
    if product.category not in partner.categories:
        reasons.append("P2_CATEGORY_NOT_ACCEPTED")
    if not partner.active:
        reasons.append("P3_PARTNER_INACTIVE")
    if pickup is None:
        reasons.append("P3_NO_PICKUP_SLOT")
    else:
        left = (lot.expiration_date - pickup.date()).days
        # min_days_before_expiry = NULL/0 คือ "ไม่มีเกณฑ์" (partner กำจัดขยะรับของหมดอายุได้) จึงตรวจเฉพาะเมื่อ > 0
        if partner.min_days > 0 and left < partner.min_days:
            reasons.append(f"P4_MIN_DAYS_{left}D_LEFT_NEED_{partner.min_days}")
        if partner.partner_type == "DONATION" and (is_expired(lot, now, cfg) or pickup > expiry_dt(lot, cfg)):
            reasons.append("P5_EXPIRED_FOR_HUMAN_USE")
    weight = product.weight_kg
    if weight is None:
        reasons.append("P8_NO_WEIGHT_DATA")
    elif cap_kg < weight - EPS:
        reasons.append("P6_NO_CAPACITY")
    return reasons


# ---------------------------------------------------------------- PART 4: Kitchen
def kitchen_due(day, cfg) -> datetime:
    """เวลาที่งานครัวของวันนั้นต้องเสร็จ (ใช้เป็น due_by; วันที่ของ due_by = วันจองครัว)"""
    return datetime.combine(day, cfg.kitchen_due_time, tzinfo=BKK)


def kitchen_hours_budget(remaining_hrs: float, status: Optional[str], day, now: datetime, cfg) -> float:
    """ชั่วโมงครัวที่ใช้ได้จริง: FULL = 0; วันนี้จำกัดด้วยเวลาที่เหลือก่อน kitchen_due_time"""
    hours = 0.0 if status == "FULL" else max(0.0, remaining_hrs)
    if day == now.date():
        window = (kitchen_due(day, cfg) - (now + timedelta(minutes=cfg.kitchen_lead_minutes))).total_seconds() / 3600.0
        hours = min(hours, max(0.0, window))
    return hours
