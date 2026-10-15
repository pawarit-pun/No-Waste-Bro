from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class InstructionStep(BaseModel):
    title: str = Field(..., min_length=1, max_length=80, description="หัวข้อสั้นๆ ของขั้นตอน เช่น \"หา lot\"")
    detail: str = Field(..., min_length=1, max_length=300, description="รายละเอียดว่าต้องทำอะไร ที่ไหน เท่าไร")

    model_config = {"str_strip_whitespace": True}


class TaskCreate(BaseModel):
    decision_id: UUID = Field(..., description="decision จาก Optimizer ที่จะเปลี่ยนเป็น task (ได้จาก `GET /optimization-decisions`) ตัวเลขทั้งหมดของ task จะคัดลอกจาก decision นี้")
    priority: int = Field(3, ge=1, le=5, description="ความเร่งด่วน 1 (ด่วนที่สุด) – 5 ค่าเริ่มต้น 3")
    ai_reasoning: Optional[str] = Field(None, description="เหตุผลที่ควรทำ task นี้ (แสดงให้ admin ดู)")
    staff_instructions: Optional[str] = Field(None, description="คำสั่งงานสำหรับ staff แบบข้อความเดียว (แสดงใน mobile app เมื่อไม่มี instruction_steps) เช่น ไปที่ชั้นไหน ทำอะไร")
    instruction_steps: Optional[list[InstructionStep]] = Field(
        None, min_length=1, max_length=8,
        description="ขั้นตอนทำงานทีละข้อ (1–8 ข้อ เรียงตามลำดับที่ต้องทำ) แสดงในหัวข้อ \"How to do it\" ของ mobile app "
                    "ถ้าไม่ส่ง app จะแสดง staff_instructions แทน",
    )


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
                        "instruction_steps": [
                            {"title": "หา lot", "detail": "ไปที่ชั้น CHILL-A / A-01 ตรวจรหัส lot บนฉลากให้ตรงกับ task"},
                            {"title": "พิมพ์ป้ายราคา 30 ใบ", "detail": "พิมพ์ราคาใหม่จากเครื่องพิมพ์ป้ายแบบพกพา"},
                            {"title": "ติดป้ายและย้ายไปด้านหน้า", "detail": "ติดทับราคาเดิม แล้ววางขวดที่ลดราคาไว้หน้าชั้น"},
                        ],
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


STAFF_ID_DESC = "รหัส staff ที่กด (ต้องเป็นคนที่ได้รับมอบหมาย task นี้)"


class TaskAccept(BaseModel):
    staff_id: str = Field(..., description=STAFF_ID_DESC)

    model_config = {"json_schema_extra": {"examples": [{"staff_id": "STF-003"}]}}


class TaskReject(BaseModel):
    staff_id: str = Field(..., description=STAFF_ID_DESC)
    rejection_reason: str = Field(..., min_length=1, description="เหตุผลที่ทำไม่ได้ (บังคับ)")

    model_config = {
        "str_strip_whitespace": True,
        "json_schema_extra": {"examples": [{"staff_id": "STF-003", "rejection_reason": "สินค้าเสียหาย ขายไม่ได้"}]},
    }


class TaskComplete(BaseModel):
    staff_id: str = Field(..., description=STAFF_ID_DESC)
    actual_quantity_handled: int = Field(..., ge=0, description="จำนวนที่จัดการได้จริง (0 ถึง action_quantity) ใช้ตัด/แยกสต็อก")

    model_config = {"json_schema_extra": {"examples": [{"staff_id": "STF-003", "actual_quantity_handled": 30}]}}
