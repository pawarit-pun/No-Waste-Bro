"""PART 2a — ความต้องการซื้อ (demand) ที่ Optimizer ใช้ตัดสินว่า markdown "คุ้มไหม"

ตาราง lot_risk_assessments ไม่มี demand ราย % ส่วนลด จึงรับจาก forecaster ได้ 2 แบบ:
  demand = {"curves": {lot_id: [{"discount_pct","expected_qty","low"}...]},
            "menu_daily_demand": {recipe_id: หน่วยต่อวัน}}
ถ้าไม่ส่ง curves มา จะใช้โมเดลสำรอง default_demand_curve (ASSUMPTION: ค่ายืดหยุ่นราคาตามหมวดสินค้า
ย้ายมาจาก forecaster เดิม) — ข้อเสนอให้เก็บ curve ลง DB อยู่ใน sql/001_schema_fixes.sql
"""
from __future__ import annotations

from typing import Optional

CATEGORY_ELASTICITY = {
    "MEAT": 2.4, "SEAFOOD": 3.2, "PRODUCE": 3.0, "DAIRY": 2.6, "BAKERY": 2.8, "READY_TO_EAT": 2.0,
}


def default_demand_curve(quantity: int, base_units: float, category: str, levels) -> list[dict]:
    """expected(d) = min(Q, base * (1 + elasticity * d/100)); low/high = ±(10% + 0.2% * d)"""
    elasticity = CATEGORY_ELASTICITY.get(category, 2.5)
    curve = []
    for d in levels:
        expected = int(round(min(float(quantity), base_units * (1.0 + elasticity * d / 100.0))))
        band = 0.10 + 0.002 * d
        curve.append({
            "discount_pct": d,
            "expected_qty": expected,
            "low": max(0, int(round(expected * (1.0 - band)))),
            "high": min(quantity, int(round(expected * (1.0 + band)))),
        })
    return curve


def resolve_demand(inputs, demand: Optional[dict], cfg) -> tuple[dict, dict]:
    """คืน (curves ต่อ lot, menu_daily_demand ต่อสูตร) — lot ที่ forecaster ไม่ส่ง curve ใช้โมเดลสำรอง"""
    demand = demand or {}
    given = demand.get("curves") or {}
    curves = {}
    for lot in inputs.lots:
        if lot.lot_id in given:
            curves[lot.lot_id] = given[lot.lot_id]
        else:
            product = inputs.products.get(lot.product_id)
            category = product.category if product else ""
            curves[lot.lot_id] = default_demand_curve(lot.quantity, lot.predicted_sold, category, cfg.markdown_levels)
    return curves, dict(demand.get("menu_daily_demand") or {})
