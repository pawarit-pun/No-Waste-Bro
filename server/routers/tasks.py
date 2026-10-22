from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query

from schemas.enums import TaskStatus
from schemas.responses import TaskCompleteResponse, TaskDetail, TaskListItem
from schemas.task import TaskAccept, TaskComplete, TaskReject
from services import task_actions
from services.tasks import get_task, list_tasks

router = APIRouter(prefix="/tasks", tags=["Tasks"])

# ไม่มี POST /tasks แล้ว: LLM ส่ง plan เข้า POST /pending-tasks และ task จะถูกสร้างตอนผู้จัดการอนุมัติเท่านั้น


@router.get(
    "",
    response_model=list[TaskListItem],
    summary="คิวงาน (staff) / ภาพรวม task (manager)",
    description="""
- **Staff mobile app:** `GET /tasks?staff_id=STF-003` → งานที่มอบหมายให้คนนั้น
- **Web dashboard:** `GET /tasks` (ไม่ใส่ `staff_id`) → task ทั้งร้าน

ค่าเริ่มต้นแสดงเฉพาะงานที่ยังไม่จบ (`PENDING` + `IN_PROGRESS`) ส่ง `status` ได้หลายค่า เช่น `?status=COMPLETED&status=REJECTED`

เรียงตาม `priority` (1 ก่อน) → `due_by` (ใกล้ก่อน, ไม่มีกำหนดไว้ท้าย) → `created_at`

แต่ละรายการแนบ `product` (ชื่อ, หมวด), `lot` (ตำแหน่งชั้นวาง, วันหมดอายุ) และ `assigned_staff` (ชื่อ, รูป) สำหรับการ์ดในหน้ารายการ

### อัปเดตแบบ real-time (mobile)
subscribe Supabase Realtime ที่ตาราง `ai_recommended_tasks` กรอง `assigned_staff_id=eq.<staff_id>`
เมื่อได้ event ให้เรียก route นี้ใหม่ (ใช้ event เป็นแค่สัญญาณ ไม่ต้องอ่านข้อมูลจาก event)
""",
    responses={404: {"description": "ไม่พบ `staff_id`"}},
)
def get_tasks(
    staff_id: Optional[str] = Query(None, description="รหัส staff ไม่ใส่ = ทุก task (สำหรับ manager)"),
    status: list[TaskStatus] = Query([TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
                                     description="สถานะที่ต้องการ ส่งได้หลายค่า ค่าเริ่มต้น PENDING + IN_PROGRESS"),
):
    return list_tasks(staff_id, [s.value for s in status])


@router.get(
    "/{task_id}",
    response_model=TaskDetail,
    summary="รายละเอียด task",
    description="""
task ทั้งแถว พร้อม `product`, `lot` (ตำแหน่งชั้นวาง, ราคาปัจจุบัน), `assigned_staff`,
`assessment` (ระดับความเสี่ยง, คาดว่าเหลือเท่าไหร่), `recipe` (เฉพาะงานครัว) และ `partner` (งานที่ส่งให้ partner: บริจาค / อาหารสัตว์ / ปุ๋ยหมัก / ก๊าซชีวภาพ / ฝังกลบ)
""",
    responses={404: {"description": "ไม่พบ `task_id`"}},
)
def get_task_detail(task_id: UUID):
    return get_task(str(task_id))


ACTION_ERRORS = {
    403: {"description": "`staff_id` ไม่ใช่คนที่ได้รับมอบหมาย task นี้"},
    404: {"description": "ไม่พบ `task_id` หรือ `staff_id`"},
    409: {"description": "สถานะของ task ไม่ถูกต้องสำหรับการกระทำนี้ (หรือถูกเปลี่ยนไปแล้วโดยคำขออื่น)"},
}


@router.post(
    "/{task_id}/accept",
    response_model=TaskDetail,
    summary="staff กดเริ่มงาน",
    description="""
`PENDING` → `IN_PROGRESS` กดได้เฉพาะ staff ที่ได้รับมอบหมาย (`assigned_staff_id`)

ต้อง accept ก่อนถึงจะ complete ได้ ตอบกลับเป็นรายละเอียด task ที่อัปเดตแล้ว (Realtime ส่ง event `UPDATE` ไปที่มือถือด้วย)
""",
    responses=ACTION_ERRORS,
)
def accept(task_id: UUID, payload: TaskAccept):
    return task_actions.accept_task(str(task_id), payload.staff_id)


@router.post(
    "/{task_id}/reject",
    response_model=TaskDetail,
    summary="staff ปฏิเสธงาน",
    description="""
`PENDING` หรือ `IN_PROGRESS` → `REJECTED` ต้องระบุ `rejection_reason`

- สต็อกไม่เปลี่ยน
- **งานครัว (`KITCHEN_REPURPOSE`):** คืนชั่วโมงครัวที่จองไว้อัตโนมัติ (สูตร × `batch_count` ในวันของ `due_by`)
""",
    responses={**ACTION_ERRORS, 422: {"description": "`rejection_reason` ว่าง"}},
)
def reject(task_id: UUID, payload: TaskReject):
    return task_actions.reject_task(str(task_id), payload.staff_id, payload.rejection_reason)


@router.post(
    "/{task_id}/complete",
    response_model=TaskCompleteResponse,
    summary="staff ทำงานเสร็จ + อัปเดตสต็อก",
    description="""
`IN_PROGRESS` → `COMPLETED` บันทึก `actual_quantity_handled` (0 ถึง `action_quantity`) แล้วอัปเดตสต็อกตาม `action_type`
**ทุกอย่างอยู่ใน transaction เดียว** ถ้าขั้นไหนไม่ผ่าน จะไม่มีอะไรเปลี่ยนเลย

| `action_type` | ผลต่อสต็อก |
| --- | --- |
| `MARKDOWN` | ตัด lot เดิมตามจำนวนที่ติดป้ายลด แล้ว **แยกเป็น lot ใหม่** ราคา `new_recommended_price` (วันหมดอายุ/ตำแหน่งเดิม, `ai_status = IDLE` ให้รอบสแกนถัดไปวางแผนกำจัดของที่ขายไม่หมด) |
| `KITCHEN_REPURPOSE` | ตัด lot ของ task ตามจำนวนจริง + **ตัดวัตถุดิบอื่นของสูตร** แล้ว **สร้าง lot ผลผลิต** |
| `DONATE` / `ANIMAL_FEED` / `COMPOST` / `ANAEROBIC_DIGESTION` / `LANDFILL` / `DISCARD` | ตัด lot ของ task ตามจำนวนจริง |

### งานครัว
- วัตถุดิบอื่น = `required_quantity × batch_count ÷ ขนาดบรรจุ` **ปัดขึ้นเป็นหน่วยเต็ม**
  ตัดจาก lot ที่ยังไม่หมดอายุ ณ วันอ้างอิง เรียงจากหมดอายุก่อน (FIFO) ตัดข้ามหลาย lot ได้
- วัตถุดิบไม่พอ → 422 บอกว่าขาดสินค้าอะไรกี่หน่วย
- lot ผลผลิต: จำนวน `output_quantity × batch_count`, หมดอายุ วันอ้างอิง + `shelf_life_days`,
  ราคา `regular_price`, ตำแหน่ง = ครัวที่ผลิต, `ai_status = IDLE` (รอบสแกนถัดไปจะเห็น)
- ชั่วโมงครัวที่จองไว้ถือว่าใช้ไปแล้ว

`effects` บอก lot ที่ถูกตัด (ก่อน → หลัง) และ lot ใหม่ที่ถูกสร้าง ทุก lot ใหม่มี `source_task_id` ชี้กลับมาที่ task นี้
""",
    responses={**ACTION_ERRORS, 422: {"description": "จำนวนไม่อยู่ในช่วง, สต็อกใน lot ไม่พอ หรือวัตถุดิบของสูตรไม่พอ"}},
)
def complete(task_id: UUID, payload: TaskComplete):
    return task_actions.complete_task(str(task_id), payload.staff_id, payload.actual_quantity_handled)
