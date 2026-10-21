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

ยอดขายแบบความน่าจะเป็น (newsvendor / critical fractile, Arrow-Harris-Marschak 1951) แทน demand_kappa เดิม:
  forecaster ให้ quantile ของ demand D มาแล้ว  low_qty = P10, expected_qty = P50, high_qty = P90
  P(D >= k) ลากเส้นตรงระหว่างจุด (0, 1) (P10, 0.9) (P50, 0.5) (P90, 0.1) (P90 + (P90 - P50), 0)
  -> วางของบนชั้นเพิ่ม 1 หน่วยในช่วงไหน คาดว่าขายได้ = ค่าเฉลี่ย P(D >= k) ของช่วงนั้น (ประมาณ 0.95 / 0.7 / 0.3 / 0.05)
  ส่วนที่เหลือ (1 - p) ไปทางกำจัดหลังหมดเวลาขาย (end-of-life) solver จึงตัดสินเองว่าวางของไว้ขายต่อคุ้มกว่าดึงออกตอนนี้ไหม
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
    base = lot.predicted_sold * frac          # ไม่มี quantile -> ถือว่าแน่นอน (low = expected = high)
    return [{"discount_pct": 0.0, "price": lot.price, "expected": base, "low": base, "high": base,
             "lost_sales": 0.0}], frac, "lot_risk_assessments.predicted_units_sold_before_expiry"


def menu_segments(rd, sale_start: datetime, cfg) -> tuple[list, float, float]:
    """ความต้องการเมนูที่เหลือขายได้ ถ้าของออกจากครัวเวลา sale_start -> (segments, expected, fraction)
    ใช้ menu_qty (P50) / low_qty (P10) / high_qty (P90) ของ recipe_demand_forecasts ปรับด้วยชั่วโมงขายที่เหลือ
    ไม่มีข้อมูลของช่วงนั้น (sale_start เลย window_to) -> ไม่มีความต้องการ"""
    if rd is None or sale_start.date() > rd.window_to:
        return [], 0.0, 0.0
    frac = remaining_fraction(max(sale_start, datetime.combine(rd.window_from, cfg.store_open, tzinfo=BKK)),
                              rd.window_from, rd.window_to, cfg)
    expected = rd.menu_qty * frac
    return survival_segments(expected, min(rd.low_qty, rd.menu_qty) * frac, rd.high_qty * frac), expected, frac


SURVIVAL_AT = (1.0, 0.9, 0.5, 0.1, 0.0)        # P(D >= k) ที่ 0, P10, P50, P90, ปลายหาง


def survival_segments(expected: float, low: float, high: float, limit: float = float("inf")) -> list:
    """แบ่งจำนวนที่วางบนชั้นเป็นช่วง [(ความกว้าง, โอกาสขายออกเฉลี่ยของหน่วยในช่วงนั้น)] เรียงจากขายง่ายไปยาก
    หน่วยที่เกินปลายหางขายไม่ได้ (p = 0) ไม่อยู่ในรายการ ผู้เรียกจัดการเอง; limit = ตัดความกว้างรวมไม่เกินจำนวนที่มี"""
    expected, low, high = max(0.0, expected), max(0.0, low), max(0.0, high)
    low, high = min(low, expected), max(high, expected)
    if high - low < 1e-9:                                   # ไม่มีความไม่แน่นอน: ขายได้ expected หน่วยแน่นอน
        pts = [(0.0, 1.0), (expected, 1.0)]
    else:
        tail = high + (high - expected)
        pts = list(zip((0.0, low, expected, high, tail), SURVIVAL_AT))
    segs, used = [], 0.0
    for (k0, s0), (k1, s1) in zip(pts, pts[1:]):
        width = min(k1 - k0, max(0.0, limit - used))
        if width <= 1e-9:
            continue
        # S เป็นเส้นตรงในช่วงนี้: ค่าเฉลี่ยบนความกว้างที่ใช้จริง (ถูกตัดด้วย limit ได้)
        s_end = s0 + (s1 - s0) * width / (k1 - k0)
        segs.append((width, (s0 + s_end) / 2.0))
        used += width
    return segs


def expected_sold(segments: list, units: float) -> float:
    """E[min(D, units)] = ผลรวม p x ความกว้างของช่วงที่หน่วยวางบนชั้นไปถึง"""
    total, left = 0.0, units
    for width, p in segments:
        take = min(width, left)
        total += take * p
        left -= take
        if left <= 0:
            break
    return total


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