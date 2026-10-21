from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from schemas.enums import PARTNER_ACTIONS, ActionType


class DecisionCreate(BaseModel):
    assessment_id: UUID = Field(..., description="ผลประเมินที่เป็นที่มาของ decision (ได้จาก `POST /risk-assessments`) server ใช้หา `run_id` และ `lot_id`")
    action_type: ActionType = Field(..., description="MARKDOWN = ลดราคา, KITCHEN_REPURPOSE = ส่งเข้าครัว, DONATE = บริจาค, ANIMAL_FEED = ส่งทำอาหารสัตว์, COMPOST = ส่งทำปุ๋ยหมัก, ANAEROBIC_DIGESTION = ส่งโรงก๊าซชีวภาพ, LANDFILL = ส่งฝังกลบ, DISCARD = ทิ้งเองในร้าน (ไม่มี partner)")
    action_quantity: int = Field(..., gt=0, description="จำนวนหน่วยของ lot ที่จะจัดการ (> 0) รวมทุก decision ของ lot เดียวกันในคำขอต้องไม่เกินจำนวนคงเหลือ")
    discount_pct: Optional[float] = Field(None, gt=0, lt=100, description="% ส่วนลด **บังคับเฉพาะ MARKDOWN** และต้องว่างสำหรับ action อื่น")
    new_recommended_price: Optional[float] = Field(None, description="ราคาใหม่ (MARKDOWN) ไม่ส่ง = server คำนวณจากราคาปัจจุบัน × (1 − discount_pct/100) ต้องไม่ต่ำกว่า `min_allowed_price`")
    target_recipe_id: Optional[str] = Field(None, description="สูตรที่จะทำ **บังคับสำหรับ KITCHEN_REPURPOSE** สินค้าของ lot ต้องเป็นวัตถุดิบของสูตรนี้")
    batch_count: Optional[int] = Field(None, gt=0, description="จำนวนรอบที่ทำตามสูตร **บังคับเฉพาะ KITCHEN_REPURPOSE** ใช้คำนวณชั่วโมงครัว")
    target_partner_id: Optional[str] = Field(None, description="partner ที่มารับของ **บังคับสำหรับ DONATE / ANIMAL_FEED / COMPOST / ANAEROBIC_DIGESTION / LANDFILL** ประเภท partner ต้องตรงกับ action")
    due_by: Optional[datetime] = Field(None, description="ต้องทำให้เสร็จภายใน **บังคับสำหรับ KITCHEN_REPURPOSE** (วันที่ตามเวลาไทยใช้เป็นวันจองครัว) ไม่ใส่ timezone = เวลาไทย")
    expected_profit_impact: Optional[float] = Field(None, description="ผลกำไร/ขาดทุนที่คาดว่าจะได้ (บาท)")
    decision_score: Optional[float] = Field(None, description="คะแนนของทางเลือกนี้จาก Optimizer (ไว้จัดลำดับ / แสดงบน dashboard)")
    alternatives: Optional[list[dict[str, Any]]] = Field(None, description="ทางเลือกอื่นที่ Optimizer พิจารณาแล้วไม่เลือก รูปแบบอิสระ (เก็บเป็น jsonb)")

    @model_validator(mode="after")
    def check_action_fields(self):
        """กติกาเดียวกับ CHECK constraint ใน DB แต่แจ้ง error ชัดกว่า"""
        is_markdown = self.action_type == ActionType.MARKDOWN
        is_kitchen = self.action_type == ActionType.KITCHEN_REPURPOSE

        if is_markdown != (self.discount_pct is not None):
            raise ValueError("discount_pct is required for MARKDOWN and must be empty for other action types")
        if not is_markdown and self.new_recommended_price is not None:
            raise ValueError("new_recommended_price is only allowed for MARKDOWN")
        if is_kitchen:
            if not self.target_recipe_id or self.batch_count is None:
                raise ValueError("KITCHEN_REPURPOSE requires target_recipe_id and batch_count")
            if self.due_by is None:
                raise ValueError("KITCHEN_REPURPOSE requires due_by (used as the kitchen booking date)")
        elif self.batch_count is not None:
            raise ValueError("batch_count is only allowed for KITCHEN_REPURPOSE")
        if self.action_type in PARTNER_ACTIONS and not self.target_partner_id:
            raise ValueError(f"{self.action_type.value} requires target_partner_id")
        return self


class DecisionBatchCreate(BaseModel):
    optimizer_version: Optional[str] = Field(None, description="เวอร์ชันของ Optimizer (ไว้ตามย้อนหลัง)")
    decisions: list[DecisionCreate] = Field(..., min_length=1, description="ผลของ Optimizer อย่างน้อย 1 รายการ บันทึกทั้งหมดหรือไม่บันทึกเลย 1 assessment มีได้หลาย decision")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "optimizer_version": "opt-v1",
                "decisions": [
                    {
                        "assessment_id": "00000000-0000-0000-0000-000000000000",
                        "action_type": "MARKDOWN", "action_quantity": 30, "discount_pct": 30,
                        "expected_profit_impact": -300, "decision_score": 0.82,
                        "alternatives": [{"action_type": "DISCARD", "expected_profit_impact": -1168}],
                    },
                    {
                        "assessment_id": "00000000-0000-0000-0000-000000000000",
                        "action_type": "KITCHEN_REPURPOSE", "action_quantity": 2,
                        "target_recipe_id": "RCP-006", "batch_count": 1,
                        "due_by": "2026-10-14T17:00:00+07:00", "expected_profit_impact": 120,
                    },
                ],
            }]
        }
    }
