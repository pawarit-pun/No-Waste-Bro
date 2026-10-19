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
  K4 ราคาใน shelf ไม่ตรงราคาปัจจุบัน (คำนวณใหม่)  K5 ไม่เหลือเวลาขายวันนี้  K6 ลดมากขึ้นแต่ขายไม่เพิ่ม (ไม่คุ้ม)
  P1 flag allow_* ของสินค้า  P2 partner ไม่รับหมวดนี้  P3 ไม่ active / ไม่มีรอบรับใน max_pickup_wait_days
  P4 อายุคงเหลือ ณ วันรับ < min_days_before_expiry  P5 ของหมดอายุ (ห้ามบริจาคให้คนกิน)  P6 ความจุ partner ไม่พอ 1 หน่วย
  P7 รวมทุก lot ที่เข้าเกณฑ์ยังไม่ถึง min_kg_per_pickup  P8 ไม่มีน้ำหนักสินค้า
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from ai_engine.optimizer.config import BKK
from ai_engine.optimizer.demand import conservative
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
def markdown_tiers(lot, product, rows: list, now: datetime, cfg) -> tuple[list, dict, list]:
    """แปลงแถว demand (demand.lot_curve) เป็นระดับราคาที่เลือกได้ -> (tiers, excluded, notes)
    1 lot มีราคาเดียว: tier 0 = ขายราคาปัจจุบัน, tier d > 0 = ลด d%
    cap = ยอดที่คาดว่าขายได้ที่ราคานั้นแบบระวัง (demand_kappa) ใช้เป็นเพดาน"""
    if is_expired(lot, now, cfg):
        return [], {"MARKDOWN:ALL": ["K0_EXPIRED"]}, []
    tiers, excluded, notes, best_cap = [], {}, [], -1
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
        cap = int(math.floor(min(lot.quantity, conservative(row["expected"], row["low"], cfg.demand_kappa)) + EPS))
        if cap <= 0:
            reasons.append("K5_NO_SALES_EXPECTED")
        if reasons:
            excluded[key] = reasons
            continue
        if cap <= best_cap:
            excluded[key] = [f"K6_NO_EXTRA_SALES cap {cap} <= {best_cap}"]
            continue
        best_cap = cap
        lost_cost = row["lost_sales"] * product.margin * cfg.lost_sales_margin_factor if d > 0 else 0.0
        tiers.append({"discount_pct": d, "price": price, "cap": cap, "expected": round(row["expected"], 2),
                      "low": round(row["low"], 2), "high": round(row["high"], 2),
                      "lost_sales_cost": round(lost_cost, 2)})
    for d in cfg.allowed_discounts:
        if f"MARKDOWN:{d}" not in excluded and all(t["discount_pct"] != d for t in tiers):
            excluded[f"MARKDOWN:{d}"] = ["K3_NOT_FORECAST"]
    return tiers, excluded, notes


# ---------------------------------------------------------------- PART 3: Partner
def next_pickup(partner, now: datetime, cfg) -> Optional[datetime]:
    """รอบรับของเร็วสุด: วันต้องอยู่ใน pickup_days (1 = จันทร์ .. 7 = อาทิตย์) และเวลาอยู่ใน pickup_time_start-end
    ต้องเตรียมของ lead_time_minutes ก่อน ถ้าวันนี้เลยช่วงแล้วเลื่อนไปวันรับถัดไป"""
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
    """ต้นทุนต่อเที่ยว: Fixed Cost + Distance & Variable Cost (travel_cost_per_trip)
    DONATION ไม่มีค่าเดินทาง คิดแค่ fixed_cost_per_trip"""
    return partner.fixed if partner.partner_type == "DONATION" else partner.fixed + partner.travel


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


def kitchen_hours_budget(remaining_hrs: float, status: Optional[str], day: date, now: datetime, cfg) -> float:
    """ชั่วโมงครัวที่ใช้ได้จริง: FULL = 0, วันนี้จำกัดด้วยเวลาที่เหลือก่อน kitchen_due_time"""
    hours = 0.0 if status == "FULL" else max(0.0, remaining_hrs)
    if day == now.date():
        window = (kitchen_due(day, cfg) - (now + timedelta(minutes=cfg.kitchen_lead_minutes))).total_seconds() / 3600
        hours = min(hours, max(0.0, window))
    return 0.0 if day < now.date() else hours