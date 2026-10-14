from fastapi import APIRouter

from schemas.responses import TaskCreateResponse
from schemas.task import TaskBatchCreate
from services.tasks import create_tasks as create_tasks_service

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post(
    "",
    status_code=201,
    response_model=TaskCreateResponse,
    summary="สร้าง task ให้ staff จาก decision (หลายรายการพร้อมกัน)",
    description="""
**ขั้นที่ 7 ของ AI Pipeline** LLM เปลี่ยน decision จาก Optimizer เป็น task ให้ staff task ทุกตัวเริ่มที่สถานะ `PENDING`

### LLM ส่งแค่ 4 field
| field | |
| --- | --- |
| `decision_id` | **บังคับ** ได้จาก `GET /optimization-decisions?status=PENDING` |
| `priority` | 1 (ด่วนที่สุด) – 5 ค่าเริ่มต้น 3 |
| `ai_reasoning` | เหตุผลที่ควรทำ (แสดงให้ admin) |
| `staff_instructions` | คำสั่งงาน (แสดงใน mobile app) |

### server คัดลอกให้เอง (LLM แก้ไม่ได้)
- จาก decision: `lot_id`, `assessment_id`, `action_type`, `action_quantity`, `discount_pct`, `new_recommended_price`,
  `target_recipe_id`, `batch_count`, `target_partner_id`, `due_by`, `expected_profit_impact`
- จาก lot: `product_id`, `original_price` (ราคาขายปัจจุบัน)

### การจองครัว (`KITCHEN_REPURPOSE`)
- ชั่วโมง = `estimated_prep_time_mins × batch_count ÷ 60` จองที่ `department_id` ของสูตร
- วันที่จอง = วันที่ของ `due_by` ตามเวลาไทย
- task ที่ใช้ครัวเดียวกันวันเดียวกันจะถูกรวมชั่วโมงแล้วจองครั้งเดียว

### สร้างทั้งหมดหรือไม่สร้างเลย
1 decision สร้างได้ 1 task เท่านั้น ถ้าครัวเต็ม (409), มี decision ที่สร้าง task ไปแล้ว (409)
หรือ DB ปฏิเสธ (400) ระบบจะคืนชั่วโมงครัวที่จองไปแล้วทั้งหมด และไม่มี task ไหนถูกสร้าง
""",
    responses={
        400: {"description": "DB ปฏิเสธการบันทึก (คืนชั่วโมงครัวแล้ว)"},
        409: {"description": "ครัวมีชั่วโมงว่างไม่พอ หรือ decision มี task อยู่แล้ว (คืนชั่วโมงครัวแล้ว)"},
        422: {"description": "ไม่พบ `decision_id`, ส่ง `decision_id` ซ้ำในคำขอ หรือสูตรไม่มีอยู่จริง / ไม่ active"},
    },
)
def create_tasks(payload: TaskBatchCreate):
    """ให้ LLM เปลี่ยน decision เป็น task task ครัวจะจองชั่วโมงครัวให้ในคำขอเดียวกัน"""
    return create_tasks_service(payload.tasks)
