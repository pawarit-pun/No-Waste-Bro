"""Mock Forecaster / Risk Scanner (ไม่ใช่ส่วนหลักของเรา — คนอื่นทำของจริง)

หน้าที่: รับ lot ที่ ai_status = IDLE (รูปแบบเดียวกับ GET /ai/scan-inputs -> inventory_lots)
        แล้วคืนผลประเมินตามฟิลด์ของ table lot_risk_assessments / POST /risk-assessments ให้ครบ:
        lot_id, days_to_expiry, quantity_at_assessment, forecast_daily_demand,
        predicted_units_sold_before_expiry, predicted_leftover_units, sell_through_probability,
        risk_score, risk_level   (assessment_id / run_id / assessed_at / model_version ให้ server เติม)
  • 1 lot = สินค้าชนิดเดียว จำนวนมากตาม inventory_lots
  • ยอดขายต่อวันเป็นค่าคงที่ในตาราง DAILY_DEMAND (deterministic ประหยัด token ไม่มีสุ่ม)
  • นอกจาก assessments ยังคืน "demand" (curve ต่อ % ส่วนลด + ความต้องการเมนูต่อวัน) ให้ Optimizer ใช้
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time

from ai_engine.clock import BKK
from ai_engine.optimizer.demand import default_demand_curve

MODEL_VERSION = "forecaster_mock_v1"
LEVELS = (0, 20, 30, 40, 50, 60, 70, 80)
RISK_LEVELS = ((75, "CRITICAL"), (50, "HIGH"), (25, "MEDIUM"))     # score ≥ เกณฑ์ -> ระดับนั้น ไม่ถึง = LOW
CATEGORY = {"DAI": "DAIRY", "MEA": "MEAT", "SEA": "SEAFOOD", "PRO": "PRODUCE", "BAK": "BAKERY", "RTE": "READY_TO_EAT"}

DAILY_DEMAND = {   # หน่วย/วัน ที่ขายราคาปกติ
    "DAI-001": 20, "DAI-002": 15, "MEA-001": 7, "MEA-002": 4, "SEA-001": 8.5,
    "PRO-001": 8, "PRO-002": 10, "BAK-001": 12, "BAK-002": 4,
}
MENU_DAILY_DEMAND = {"RCP-001": 30, "RCP-002": 60, "RCP-003": 30, "RCP-004": 24, "RCP-005": 12, "RCP-006": 24}


def _level(score: float) -> str:
    return next((name for threshold, name in RISK_LEVELS if score >= threshold), "LOW")


def mock_forecast(lots: list, now: datetime, levels=LEVELS) -> dict:
    """lots = inventory_lots (dict) ที่ ai_status = IDLE   now = เวลาที่จำลอง (tz Asia/Bangkok)"""
    assessments, curves = [], {}
    for lot in lots:
        pid, qty = lot["product_id"], int(lot["current_quantity"])
        expiry = date.fromisoformat(str(lot["expiration_date"])[:10])
        days = (expiry - now.date()).days
        hours = max(0.0, (datetime.combine(expiry, time(23, 59, 59), tzinfo=BKK) - now).total_seconds() / 3600.0)
        daily = float(DAILY_DEMAND.get(pid, 10.0))
        sold = 0 if days < 0 else int(round(min(float(qty), daily * hours / 24.0)))
        score = 100.0 if days < 0 else round((qty - sold) / qty * 100.0, 1)
        assessments.append({
            "lot_id": lot["lot_id"], "days_to_expiry": days, "quantity_at_assessment": qty,
            "forecast_daily_demand": daily, "predicted_units_sold_before_expiry": sold,
            "predicted_leftover_units": qty - sold, "sell_through_probability": round(sold / qty, 3),
            "risk_score": score, "risk_level": _level(score),
        })
        curves[lot["lot_id"]] = default_demand_curve(qty, sold, CATEGORY.get(pid[:3], ""), levels)
    return {"model_version": MODEL_VERSION, "assessments": assessments,
            "demand": {"curves": curves, "menu_daily_demand": dict(MENU_DAILY_DEMAND)}}


def to_post_payload(forecast: dict) -> dict:
    """body ของ POST /api/v1/risk-assessments"""
    return {"model_version": forecast["model_version"], "assessments": forecast["assessments"]}


def to_at_risk_rows(lots: list, forecast: dict, run_id: str, assessment_ids: dict | None, now: datetime) -> list:
    """ประกอบ at_risk_lots (หน้าตาตาม Swagger ของ GET /ai/optimize-inputs) จากผลประเมิน — เฉพาะ MEDIUM ขึ้นไป
    ใช้ตอน dry-run/offline (ถ้ายิง POST จริง ให้ใช้ assessment_id ที่ server คืนมาแทน)"""
    by_lot = {l["lot_id"]: l for l in lots}
    rows = []
    for a in forecast["assessments"]:
        if a["risk_level"] == "LOW":
            continue
        aid = (assessment_ids or {}).get(a["lot_id"]) or str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}|{a['lot_id']}"))
        rows.append({"assessment_id": aid, "run_id": run_id, "assessed_at": now.isoformat(),
                     "model_version": forecast["model_version"], **a, "lot": by_lot[a["lot_id"]]})
    return sorted(rows, key=lambda r: -r["risk_score"])
