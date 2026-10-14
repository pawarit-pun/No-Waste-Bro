from fastapi import APIRouter

from schemas.responses import TaskCreateResponse
from schemas.task import TaskBatchCreate
from services.tasks import create_tasks as create_tasks_service

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post(
    "",
    status_code=201,
    response_model=TaskCreateResponse,
    summary="สร้าง task ให้ staff (หลายรายการพร้อมกัน)",
    description="""
**ขั้นที่ 5 ของ AI Pipeline** ให้ LLM สร้าง task จากผลของ Optimizer task ทุกตัวเริ่มที่สถานะ `PENDING`

### field ที่ต้องมีตาม `action_type`

| `action_type` | ต้องมี | ต้องว่าง |
| --- | --- | --- |
| `MARKDOWN` (ลดราคา) | `discount_pct` | `batch_count` |
| `KITCHEN_REPURPOSE` (ส่งเข้าครัว) | `target_recipe_id`, `batch_count`, `due_by` | `discount_pct` |
| `DONATE` (บริจาค) | `target_partner_id` | `discount_pct`, `batch_count` |
| `DISCARD` (ทิ้ง) | – | `discount_pct`, `batch_count` |

ทุก task ต้องมี `lot_id` และ `action_quantity` (> 0)

### server เติมให้เอง
- `product_id` ดึงจาก lot (ถ้าส่งมาแล้วไม่ตรงกับ lot จะได้ 422)
- `original_price` = ราคาขายปัจจุบันของ lot ถ้าไม่ส่งมา

### การจองครัว (`KITCHEN_REPURPOSE`)
- server คำนวณชั่วโมงเอง ไม่ต้องส่งมา: `estimated_prep_time_mins × batch_count ÷ 60` จองที่ `department_id` ของสูตร
- วันที่จอง = วันที่ของ `due_by` ตามเวลาไทย
- task ที่ใช้ครัวเดียวกันวันเดียวกันจะถูกรวมชั่วโมงแล้วจองครั้งเดียว
- ดูชั่วโมงที่ว่างได้จาก `kitchen_capacity` ใน `GET /ai/optimize-inputs`

### สร้างทั้งหมดหรือไม่สร้างเลย
ถ้าครัวไหนเต็ม (409) หรือ DB ปฏิเสธตอนบันทึก (400) ระบบจะคืนชั่วโมงครัวที่จองไปแล้วทั้งหมด และไม่มี task ไหนถูกสร้าง

> ตอนนี้ยังสร้าง `DONATE` ไม่ได้ เพราะตาราง `donation_partners` ยังว่าง
""",
    responses={
        400: {"description": "DB ปฏิเสธการบันทึก เช่น `target_partner_id` ไม่มีอยู่จริง (คืนชั่วโมงครัวแล้ว)"},
        409: {"description": "ครัวมีชั่วโมงว่างไม่พอ ข้อความบอกว่าครัวไหน วันไหน (คืนชั่วโมงครัวแล้ว)"},
        422: {"description": "ข้อมูลไม่ครบตาม `action_type`, ไม่พบ `lot_id`, `product_id` ไม่ตรงกับ lot หรือสูตรไม่มีอยู่จริง / ไม่ active"},
    },
)
def create_tasks(payload: TaskBatchCreate):
    """ให้ LLM สร้าง task หลายรายการ task ครัวจะจองชั่วโมงครัวให้ในคำขอเดียวกัน"""
    return create_tasks_service(payload.tasks)
