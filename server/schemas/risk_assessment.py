from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from schemas.enums import RiskLevel


class RiskAssessmentItem(BaseModel):
    lot_id: str = Field(..., description="รหัส lot ที่ประเมิน ต้องมีอยู่ใน `inventory_lots`")
    days_to_expiry: int = Field(..., description="จำนวนวันก่อนหมดอายุ นับจาก `reference_date` (ติดลบได้ถ้าหมดอายุแล้ว)")
    quantity_at_assessment: int = Field(..., ge=0, description="จำนวนคงเหลือของ lot ตอนประเมิน")
    forecast_daily_demand: float = Field(..., description="ยอดขายที่คาดการณ์ต่อวัน (หน่วยเดียวกับ lot)")
    predicted_units_sold_before_expiry: float = Field(..., description="จำนวนที่คาดว่าจะขายได้ก่อนหมดอายุ")
    predicted_leftover_units: float = Field(..., ge=0, description="จำนวนที่คาดว่าจะเหลือตอนหมดอายุ (≥ 0)")
    sell_through_probability: Optional[float] = Field(None, ge=0, le=1, description="โอกาสขายหมดก่อนหมดอายุ (0–1) ไม่บังคับ")
    risk_score: float = Field(..., ge=0, le=100, description="คะแนนความเสี่ยง 0–100 (ยิ่งมากยิ่งเสี่ยง)")
    risk_level: RiskLevel = Field(..., description="ระดับความเสี่ยง `optimize-inputs` จะส่งต่อเฉพาะ MEDIUM / HIGH / CRITICAL")


class RiskAssessmentBatchCreate(BaseModel):
    run_id: Optional[UUID] = Field(None, description="รหัสรอบสแกน ไม่ส่ง = server สร้างให้ ถ้าส่งเองต้องไม่ซ้ำ lot เดิมใน run เดียวกัน")
    model_version: Optional[str] = Field(None, description="เวอร์ชันของโมเดล AI ที่ใช้ประเมิน (ไว้ตามย้อนหลัง)")
    assessments: list[RiskAssessmentItem] = Field(..., min_length=1, description="ผลประเมินของแต่ละ lot อย่างน้อย 1 รายการ")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "model_version": "risk-v1",
                "assessments": [
                    {
                        "lot_id": "LOT-000001", "days_to_expiry": 0, "quantity_at_assessment": 85,
                        "forecast_daily_demand": 30.8, "predicted_units_sold_before_expiry": 30.8,
                        "predicted_leftover_units": 54.2, "sell_through_probability": 0.36,
                        "risk_score": 82.5, "risk_level": "CRITICAL",
                    },
                    {
                        "lot_id": "LOT-000002", "days_to_expiry": 6, "quantity_at_assessment": 172,
                        "forecast_daily_demand": 30.8, "predicted_units_sold_before_expiry": 172,
                        "predicted_leftover_units": 0, "sell_through_probability": 0.95,
                        "risk_score": 8, "risk_level": "LOW",
                    },
                ],
            }]
        }
    }
