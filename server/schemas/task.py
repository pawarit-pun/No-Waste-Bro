from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from schemas.enums import ActionType


class TaskCreate(BaseModel):
    lot_id: str = Field(..., description="lot ที่ task นี้จัดการ ต้องมีอยู่จริง")
    action_type: ActionType = Field(..., description="MARKDOWN = ลดราคา, KITCHEN_REPURPOSE = ส่งเข้าครัว, DONATE = บริจาค, DISCARD = ทิ้ง")
    action_quantity: int = Field(..., gt=0, description="จำนวนหน่วยของ lot ที่ให้ staff จัดการ (> 0)")
    assessment_id: Optional[UUID] = Field(None, description="ผลประเมินที่เป็นที่มาของ task (ได้จาก `POST /risk-assessments`)")
    product_id: Optional[str] = Field(None, description="ไม่ต้องส่ง server ดึงจาก lot ให้ ถ้าส่งมาต้องตรงกับ lot")
    original_price: Optional[float] = Field(None, description="ราคาก่อนทำ task ไม่ส่ง = ราคาขายปัจจุบันของ lot")
    new_recommended_price: Optional[float] = Field(None, description="ราคาใหม่ที่แนะนำ (สำหรับ MARKDOWN) ห้ามต่ำกว่า `min_allowed_price` ของสินค้า")
    discount_pct: Optional[float] = Field(None, gt=0, lt=100, description="% ส่วนลด **บังคับเฉพาะ MARKDOWN** และต้องว่างสำหรับ action อื่น")
    expected_profit_impact: Optional[float] = Field(None, description="ผลกำไร/ขาดทุนที่คาดว่าจะได้ (บาท) ใช้แสดงบน dashboard")
    target_recipe_id: Optional[str] = Field(None, description="สูตรที่จะทำ **บังคับสำหรับ KITCHEN_REPURPOSE**")
    target_partner_id: Optional[str] = Field(None, description="partner ที่รับบริจาค **บังคับสำหรับ DONATE**")
    batch_count: Optional[int] = Field(None, gt=0, description="จำนวนรอบที่ทำตามสูตร **บังคับเฉพาะ KITCHEN_REPURPOSE** ใช้คำนวณชั่วโมงครัว")
    priority: int = Field(3, ge=1, le=5, description="ความเร่งด่วน 1 (ด่วนที่สุด) – 5 ค่าเริ่มต้น 3")
    due_by: Optional[datetime] = Field(None, description="ต้องทำให้เสร็จภายใน **บังคับสำหรับ KITCHEN_REPURPOSE** วันที่ตามเวลาไทยใช้เป็นวันจองครัว ไม่ใส่ timezone = เวลาไทย")
    ai_reasoning: Optional[str] = Field(None, description="เหตุผลที่ AI เลือก action นี้ (แสดงให้ admin ดู)")
    staff_instructions: Optional[str] = Field(None, description="คำสั่งงานสำหรับ staff (แสดงใน mobile app)")

    @model_validator(mode="after")
    def check_action_fields(self):
        """กติกาเดียวกับ CHECK constraint ใน DB แต่แจ้ง error ชัดกว่า"""
        is_markdown = self.action_type == ActionType.MARKDOWN
        is_kitchen = self.action_type == ActionType.KITCHEN_REPURPOSE

        if is_markdown != (self.discount_pct is not None):
            raise ValueError("discount_pct is required for MARKDOWN and must be empty for other action types")
        if is_kitchen:
            if not self.target_recipe_id or self.batch_count is None:
                raise ValueError("KITCHEN_REPURPOSE requires target_recipe_id and batch_count")
            if self.due_by is None:
                raise ValueError("KITCHEN_REPURPOSE requires due_by (used as the kitchen booking date)")
        elif self.batch_count is not None:
            raise ValueError("batch_count is only allowed for KITCHEN_REPURPOSE")
        if self.action_type == ActionType.DONATE and not self.target_partner_id:
            raise ValueError("DONATE requires target_partner_id")
        return self


class TaskBatchCreate(BaseModel):
    tasks: list[TaskCreate] = Field(..., min_length=1, description="รายการ task อย่างน้อย 1 รายการ สร้างทั้งหมดหรือไม่สร้างเลย")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "tasks": [
                    {
                        "lot_id": "LOT-000001", "action_type": "MARKDOWN", "action_quantity": 30,
                        "discount_pct": 30, "new_recommended_price": 33.25, "priority": 2,
                        "due_by": "2026-10-14T18:00:00+07:00",
                        "ai_reasoning": "คาดว่าเหลือ 54 ขวดตอนหมดอายุ ลด 30% ช่วงเย็นช่วยเพิ่มยอดขายได้",
                        "staff_instructions": "ติดป้ายลด 30% ที่ชั้น CHILL-A / A-01",
                        "expected_profit_impact": -300,
                    },
                    {
                        "lot_id": "LOT-000001", "action_type": "KITCHEN_REPURPOSE", "action_quantity": 2,
                        "target_recipe_id": "RCP-006", "batch_count": 1, "priority": 1,
                        "due_by": "2026-10-14T17:00:00+07:00",
                        "ai_reasoning": "นมที่เหลือใช้ทำขนมปังพุดดิ้งได้ 12 ชิ้น ครัวเบเกอรี่ยังว่าง",
                        "staff_instructions": "นำนม 2 ขวดจาก CHILL-A / A-01 ส่งแผนกเบเกอรี่",
                    },
                ]
            }]
        }
    }
