"""PART 2a — ความต้องการซื้อ (demand) จาก Risk Scanner + Forecaster จริง ใช้ตัดสินว่าลดราคา / ทำเมนู "คุ้มไหม"

แหล่งข้อมูล (บันทึกโดย AI/risk_forecaster/run_scan.py -> POST /risk-assessments, อ่านผ่าน GET /ai/optimize-inputs):
  at_risk_lots[].shelf  (lot_shelf_forecasts)      ลด x% ตั้งแต่เปิดร้านวันนี้จนหมดอายุ ล็อตนี้ขายได้กี่หน่วย
                                                    expected_qty / low_qty (10%) / high_qty (90%) / lost_sales_other_lots
  recipe_demand         (recipe_demand_forecasts)  เมนูแต่ละสูตรควรผลิตเพิ่มกี่ชิ้นในช่วง window_from..window_to
                                                    (menu_qty = gross_demand - current_stock) ใช้ "รวมทั้งช่วง" ตามที่ทีมตกลง

ไม่มีการเดายอดขายเอง (ตัดโมเดลความยืดหยุ่นราคาแบบ mock เดิมทิ้งแล้ว):
  - shelf ว่าง + ยังไม่หมดอายุ (สินค้าห้ามลดราคา) -> ระดับ 0% จาก predicted_units_sold_before_expiry ของ assessment
  - shelf ว่าง + หมดอายุแล้ว -> ขายไม่ได้ เหลือแค่ช่องทางกำจัด
ปรับตามเวลาที่รัน: forecaster คิดยอด "เต็มวันตั้งแต่เปิดร้าน" ถ้ารันตอนบ่าย ชั่วโมงขายที่เหลือน้อยลง
  ยอดที่ใช้ = ยอดของ forecaster x ชั่วโมงร้านเปิดที่เหลือ / ชั่วโมงร้านเปิดทั้งช่วง (ASSUMPTION: ยอดกระจายเท่ากันทุกชั่วโมง)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ai_engine.optimizer.config import BKK


def open_hours(start: datetime, end_date: date, cfg) -> float:
    """ชั่วโมงร้านเปิด (store_open-store_close) ตั้งแต่ start ถึงสิ้นวัน end_date"""
    total, day = 0.0, start.date()
    while day <= end_date:
        o = datetime.combine(day, cfg.store_open, tzinfo=BKK)
        c = datetime.combine(day, cfg.store_close, tzinfo=BKK)
        total += max(0.0, (c - max(o, start)).total_seconds() / 3600.0)
        day += timedelta(days=1)
    return total


def full_hours(first: date, last: date, cfg) -> float:
    days = (last - first).days + 1
    per_day = (datetime.combine(first, cfg.store_close) - datetime.combine(first, cfg.store_open)).total_seconds() / 3600
    return max(0, days) * per_day


def remaining_fraction(start: datetime, first: date, last: date, cfg) -> float:
    """สัดส่วนชั่วโมงขายที่ยังเหลือ (0-1) ของช่วง first..last นับจาก start"""
    if not cfg.scale_by_open_hours:
        return 1.0 if start.date() <= last else 0.0
    whole = full_hours(first, last, cfg)
    return 0.0 if whole <= 0 else min(1.0, max(0.0, open_hours(start, last, cfg) / whole))


def lot_curve(lot, now: datetime, reference_date: date, cfg) -> tuple[list, float, str]:
    """แถว demand ของ lot หลังปรับเวลา -> (rows, fraction, source)
    rows = [{discount_pct, price, expected, low, high, lost_sales}] ยังไม่ผ่านกฎ (กฎอยู่ใน rules.markdown_tiers)"""
    frac = remaining_fraction(now, reference_date, lot.expiration_date, cfg)
    if lot.shelf:
        rows = [{"discount_pct": s.discount_pct, "price": s.price, "expected": s.expected_qty * frac,
                 "low": s.low_qty * frac, "high": s.high_qty * frac, "lost_sales": s.lost_sales_other_lots * frac}
                for s in lot.shelf]
        return rows, frac, "lot_shelf_forecasts"
    if lot.expiration_date < now.date():
        return [], frac, "expired"
    base = lot.predicted_sold * frac
    return [{"discount_pct": 0.0, "price": lot.price, "expected": base, "low": base, "high": base,
             "lost_sales": 0.0}], frac, "lot_risk_assessments.predicted_units_sold_before_expiry"


def menu_cap(rd, sale_start: datetime, cfg) -> tuple[float, float, float]:
    """ความต้องการเมนูที่เหลือขายได้ ถ้าของออกจากครัวเวลา sale_start -> (expected, low, fraction)
    ไม่มีข้อมูลของช่วงนั้น (sale_start เลย window_to) -> 0"""
    if rd is None or sale_start.date() > rd.window_to:
        return 0.0, 0.0, 0.0
    frac = remaining_fraction(max(sale_start, datetime.combine(rd.window_from, cfg.store_open, tzinfo=BKK)),
                              rd.window_from, rd.window_to, cfg)
    return rd.menu_qty * frac, min(rd.low_qty, rd.menu_qty) * frac, frac


def conservative(expected: float, low: float, kappa: float) -> float:
    """ยอดแบบระวัง: expected - kappa x (expected - low)"""
    return max(0.0, expected - kappa * max(0.0, expected - low))


def demand_from_optimize_inputs(inputs: dict) -> dict:
    """ตัวแปลงที่ทีม Risk Scanner เสนอ (เก็บไว้ให้ทีมอื่นเรียกดูข้อมูลดิบแบบเดียวกัน ไม่ได้ใช้ในการคำนวณหลัก)
    คืน {"curves": {lot_id: [...]}, "menu_daily_demand": {recipe_id: menu_qty / จำนวนวันของ window}}"""
    curves = {
        r["lot_id"]: [{"discount_pct": s["discount_pct"], "expected_qty": s["expected_qty"],
                    "low": s["low_qty"], "high": s["high_qty"]} for s in r.get("shelf") or []]
        for r in inputs.get("at_risk_lots", []) if r.get("shelf")
    }
    menu = {}
    for r in inputs.get("recipe_demand", []):
        days = (date.fromisoformat(str(r["window_to"])[:10]) - date.fromisoformat(str(r["window_from"])[:10])).days + 1
        menu[r["recipe_id"]] = float(r["menu_qty"]) / days
    return {"curves": curves, "menu_daily_demand": menu}