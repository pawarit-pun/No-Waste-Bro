from datetime import date
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from schemas.enums import RiskLevel


class ShelfForecastItem(BaseModel):
    discount_pct: float = Field(..., ge=0, lt=100, description="ส่วนลด (%) 0 = ราคาปัจจุบัน")
    price: float = Field(..., ge=0, description="ราคาหลังลด (บาท/หน่วย)")
    expected_qty: float = Field(..., ge=0, description="ล็อตนี้คาดว่าขายได้เท่าไรก่อนหมดอายุ ถ้าลดตั้งแต่เปิดร้านวันนี้จนหมดอายุ")
    low_qty: float = Field(..., ge=0, description="ช่วงล่าง (10%)")
    high_qty: float = Field(..., ge=0, description="ช่วงบน (90%) ต้อง ≥ low_qty")
    applies_from: date = Field(..., description="เริ่มลดวันไหน (= reference_date)")
    applies_until: date = Field(..., description="ลดถึงวันไหน (= วันหมดอายุ)")
    lost_sales_other_lots: float = Field(0, ge=0, description="ล็อตอื่นของสินค้าเดียวกันขายได้น้อยลงเท่าไร เพราะลูกค้าไปหยิบล็อตที่ลดราคา")


class RecipeDemandItem(BaseModel):
    recipe_id: str = Field(..., description="สูตรที่ active ต้องมีอยู่ใน `recipes`")
    output_product_id: str = Field(..., description="สินค้าที่สูตรผลิต")
    window_from: date
    window_to: date = Field(..., description="ช่วงอายุเมนู (ผลิตวันนี้ขายได้ถึงวันไหน)")
    gross_demand: float = Field(..., ge=0, description="ความต้องการเมนูทั้งช่วง")
    current_stock: int = Field(0, ge=0, description="ของเมนูที่มีบนชั้นแล้ว")
    menu_qty: float = Field(..., ge=0, description="ควรผลิตเพิ่ม = gross_demand - current_stock")
    low_qty: float = Field(..., ge=0)
    high_qty: float = Field(..., ge=0)
    expected_revenue: float = Field(..., ge=0, description="รายได้ที่คาด = menu_qty x ราคาปกติ (ใช้เลือกสูตร)")


class RiskAssessmentItem(BaseModel):
    lot_id: str = Field(..., description="รหัส lot ที่ประเมิน ต้องมีอยู่ใน `inventory_lots`")
    days_to_expiry: int = Field(..., description="จำนวนวันก่อนหมดอายุ นับจาก `reference_date` (ติดลบได้ถ้าหมดอายุแล้ว)")
    sellable_hours: Optional[int] = Field(None, ge=0, description="ชั่วโมงร้านเปิด (08:00-22:00) ที่เหลือจนสิ้นวันหมดอายุ")
    quantity_at_assessment: int = Field(..., ge=0, description="จำนวนคงเหลือของ lot ตอนประเมิน")
    forecast_daily_demand: float = Field(..., description="ยอดขายที่คาดการณ์ต่อวัน (หน่วยเดียวกับ lot)")
    predicted_units_sold_before_expiry: float = Field(..., description="จำนวนที่คาดว่าจะขายได้ก่อนหมดอายุ")
    predicted_leftover_units: float = Field(..., ge=0, description="จำนวนที่คาดว่าจะเหลือตอนหมดอายุ (≥ 0)")
    sell_through_probability: Optional[float] = Field(None, ge=0, le=1, description="โอกาสขายหมดก่อนหมดอายุ (0–1) ไม่บังคับ")
    risk_score: float = Field(..., ge=0, le=100, description="คะแนนความเสี่ยง 0–100 (ยิ่งมากยิ่งเสี่ยง)")
    risk_level: RiskLevel = Field(..., description="ระดับความเสี่ยง `optimize-inputs` จะส่งต่อเฉพาะ HIGH / CRITICAL")
    shelf: list[ShelfForecastItem] = Field(default_factory=list, description="ลด x% แล้วขายได้เท่าไร (ส่งเฉพาะล็อต HIGH / CRITICAL ที่ยังไม่หมดอายุ)")


class RiskAssessmentBatchCreate(BaseModel):
    run_id: Optional[UUID] = Field(None, description="รหัสรอบสแกน ไม่ส่ง = server สร้างให้ ถ้าส่งเองต้องไม่ซ้ำ lot เดิมใน run เดียวกัน")
    model_version: Optional[str] = Field(None, description="เวอร์ชันของโมเดล AI ที่ใช้ประเมิน (ไว้ตามย้อนหลัง)")
    reference_date: Optional[date] = Field(None, description="\"วันนี้\" ของรอบสแกน ไม่ส่ง = วันนี้เวลาไทย")
    run_metrics: Optional[dict[str, Any]] = Field(None, description="ความแม่นของโมเดล cutoff ที่ใช้ lift ของส่วนลด (เก็บใน forecast_runs.metrics)")
    assessments: list[RiskAssessmentItem] = Field(..., min_length=1, description="ผลประเมินของแต่ละ lot อย่างน้อย 1 รายการ")
    recipe_demand: list[RecipeDemandItem] = Field(default_factory=list, description="ความต้องการเมนูครัวต่อสูตร เรียงตามรายได้")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "model_version": "risk-v3+forecaster_v3",
                "reference_date": "2026-10-16",
                "run_metrics": {"forecaster": "lgbm", "thresholds": {"MEDIUM": 10, "HIGH": 40, "CRITICAL": 50}},
                "assessments": [
                    {
                        "lot_id": "LOT-000005", "days_to_expiry": 1, "sellable_hours": 28,
                        "quantity_at_assessment": 24, "forecast_daily_demand": 6.82,
                        "predicted_units_sold_before_expiry": 13.65, "predicted_leftover_units": 10.35,
                        "sell_through_probability": 0.042, "risk_score": 43.13, "risk_level": "HIGH",
                        "shelf": [
                            {"discount_pct": 0, "price": 130.0, "expected_qty": 13.6, "low_qty": 7, "high_qty": 21,
                             "applies_from": "2026-10-16", "applies_until": "2026-10-17", "lost_sales_other_lots": 0},
                            {"discount_pct": 30, "price": 91.0, "expected_qty": 15.9, "low_qty": 9, "high_qty": 23,
                             "applies_from": "2026-10-16", "applies_until": "2026-10-17", "lost_sales_other_lots": 0},
                        ],
                    },
                    {
                        "lot_id": "LOT-000002", "days_to_expiry": 8, "sellable_hours": 126,
                        "quantity_at_assessment": 172, "forecast_daily_demand": 30.86,
                        "predicted_units_sold_before_expiry": 172, "predicted_leftover_units": 0,
                        "sell_through_probability": 0.97, "risk_score": 0, "risk_level": "LOW",
                    },
                ],
                "recipe_demand": [
                    {"recipe_id": "RCP-001", "output_product_id": "RTE-001", "window_from": "2026-10-16",
                     "window_to": "2026-10-16", "gross_demand": 7.7, "current_stock": 0, "menu_qty": 7.7,
                     "low_qty": 3, "high_qty": 13, "expected_revenue": 1294.94},
                ],
            }]
        }
    }
