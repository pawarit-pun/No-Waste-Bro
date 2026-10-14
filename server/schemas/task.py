from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    decision_id: UUID = Field(..., description="decision จาก Optimizer ที่จะเปลี่ยนเป็น task (ได้จาก `GET /optimization-decisions`) ตัวเลขทั้งหมดของ task จะคัดลอกจาก decision นี้")
    priority: int = Field(3, ge=1, le=5, description="ความเร่งด่วน 1 (ด่วนที่สุด) – 5 ค่าเริ่มต้น 3")
    ai_reasoning: Optional[str] = Field(None, description="เหตุผลที่ควรทำ task นี้ (แสดงให้ admin ดู)")
    staff_instructions: Optional[str] = Field(None, description="คำสั่งงานสำหรับ staff (แสดงใน mobile app) เช่น ไปที่ชั้นไหน ทำอะไร")


class TaskBatchCreate(BaseModel):
    tasks: list[TaskCreate] = Field(..., min_length=1, description="รายการ task อย่างน้อย 1 รายการ สร้างทั้งหมดหรือไม่สร้างเลย")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "tasks": [
                    {
                        "decision_id": "00000000-0000-0000-0000-000000000000", "priority": 2,
                        "ai_reasoning": "คาดว่าเหลือ 54 ขวดตอนหมดอายุ ลด 30% ช่วงเย็นช่วยเพิ่มยอดขายได้",
                        "staff_instructions": "ติดป้ายลด 30% ที่นมสด 830ml จำนวน 30 ขวด ชั้น CHILL-A / A-01",
                    },
                    {
                        "decision_id": "00000000-0000-0000-0000-000000000001", "priority": 1,
                        "ai_reasoning": "นมที่เหลือใช้ทำขนมปังพุดดิ้งได้ 12 ชิ้น ครัวเบเกอรี่ยังว่าง",
                        "staff_instructions": "นำนม 2 ขวดจาก CHILL-A / A-01 ส่งแผนกเบเกอรี่ก่อน 17:00",
                    },
                ]
            }]
        }
    }
