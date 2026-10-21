from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from schemas.task import TaskCreate


class PendingTaskCreate(TaskCreate):
    model_used: Optional[str] = Field(None, max_length=120,
                                      description="model ที่เขียนข้อความ เช่น amazon.nova-lite-v1:0 หรือ TEMPLATE ถ้า LLM ไม่ผ่าน validation")


class PendingTaskBatchCreate(BaseModel):
    tasks: list[PendingTaskCreate] = Field(..., min_length=1,
                                           description="plan อย่างน้อย 1 รายการ เข้าคิวทั้งหมดหรือไม่เข้าเลย")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "tasks": [
                    {
                        "decision_id": "00000000-0000-0000-0000-000000000000", "priority": 2,
                        "model_used": "amazon.nova-lite-v1:0",
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
                        "model_used": "TEMPLATE",
                        "ai_reasoning": "นมที่เหลือใช้ทำขนมปังพุดดิ้งได้ 12 ชิ้น ครัวเบเกอรี่ยังว่าง",
                        "staff_instructions": "นำนม 2 ขวดจาก CHILL-A / A-01 ส่งแผนกเบเกอรี่ก่อน 17:00",
                    },
                ]
            }]
        }
    }


REVIEW_IDS_DESC = "plan ที่จะอนุมัติ/ปฏิเสธ (ส่งทุก plan ของ lot เดียวกันพร้อมกันได้) ทำทั้งหมดหรือไม่ทำเลย"
MANAGER_ID_DESC = "staff_id ของผู้จัดการที่กด (role ต้องเป็น MANAGER)"


class ReviewApprove(BaseModel):
    review_ids: list[UUID] = Field(..., min_length=1, max_length=100, description=REVIEW_IDS_DESC)
    manager_id: str = Field(..., description=MANAGER_ID_DESC)
    review_note: Optional[str] = Field(None, max_length=500, description="หมายเหตุ (ไม่บังคับ)")

    model_config = {
        "str_strip_whitespace": True,
        "json_schema_extra": {"examples": [{
            "review_ids": ["00000000-0000-0000-0000-000000000000"], "manager_id": "STF-001",
        }]},
    }


class ReviewReject(BaseModel):
    review_ids: list[UUID] = Field(..., min_length=1, max_length=100, description=REVIEW_IDS_DESC)
    manager_id: str = Field(..., description=MANAGER_ID_DESC)
    review_note: str = Field(..., min_length=1, max_length=500, description="เหตุผลที่ปฏิเสธ (บังคับ)")

    model_config = {
        "str_strip_whitespace": True,
        "json_schema_extra": {"examples": [{
            "review_ids": ["00000000-0000-0000-0000-000000000000"], "manager_id": "STF-001",
            "review_note": "ลด 50% ลึกเกินไป ให้ส่งเข้าครัวแทน",
        }]},
    }
