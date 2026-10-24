from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query

from schemas.enums import ReviewStatus
from schemas.pending_task import PendingTaskBatchCreate, ReviewApprove, ReviewReject
from schemas.responses import (PendingTaskCreateResponse, PendingTaskDetail, PendingTaskListResponse,
                               ReviewApproveResponse, ReviewRejectResponse)
from schemas.agent import UndoAutoRequest, UndoAutoResponse
from services import auto_approve
from services import pending_tasks as service

router = APIRouter(prefix="/pending-tasks", tags=["Review Queue"])

REVIEW_ERRORS = {
    403: {"description": "`manager_id` ไม่ใช่ MANAGER ที่ active"},
    404: {"description": "ไม่พบ `manager_id` หรือ `review_id`"},
    409: {"description": "มี plan ที่ไม่ใช่ `WAITING` แล้ว (ถูกอนุมัติ/ปฏิเสธไปก่อน) หรือครัวมีชั่วโมงว่างไม่พอ (เฉพาะ approve)"},
    422: {"description": "ส่ง `review_id` ซ้ำในคำขอ หรือข้อมูลไม่ครบ"},
}


@router.post(
    "",
    status_code=201,
    response_model=PendingTaskCreateResponse,
    summary="LLM ส่ง plan เข้าคิวรออนุมัติ",
    description="""
**ขั้นที่ 7 ของ AI Pipeline** LLM เปลี่ยน decision จาก Optimizer เป็น plan ของ task แล้วส่งเข้าคิว `pending_tasks`
ทุก plan เริ่มที่ `WAITING` **staff จะยังไม่เห็นงานจนกว่าจะอนุมัติ** (ผู้จัดการกด หรือ Manager Agent อนุมัติเองถ้าเปิด Auto-approve และ plan เข้าเกณฑ์)
(`POST /pending-tasks/approve`) ซึ่งตอนนั้น server จะสร้าง task มอบหมาย staff และจองชั่วโมงครัว

### LLM ส่ง
| field | |
| --- | --- |
| `decision_id` | **บังคับ** ได้จาก `GET /optimization-decisions?status=PENDING` |
| `priority` | 1 (ด่วนที่สุด) – 5 ค่าเริ่มต้น 3 |
| `ai_reasoning` | เหตุผลที่ควรทำ (แสดงให้ผู้จัดการ) |
| `staff_instructions` / `instruction_steps` | คำสั่งงานที่ staff จะเห็นหลังอนุมัติ |
| `model_used` | model ที่เขียนข้อความ หรือ `TEMPLATE` ถ้า LLM ไม่ผ่าน validation |

### server เติมให้
- `run_id`, `assessment_id`, `lot_id` จาก decision (ตัวเลขทั้งหมดของงานยังอยู่ที่ decision LLM แก้ไม่ได้)
- `review_deadline` = `due_by` ของ decision หรือ 22:00 ของวันหมดอายุ lot (เวลาไทย) ถ้าไม่มี `due_by` (MARKDOWN)

decision ต้องยังเป็น `PENDING` (ยังไม่เคยส่ง) 1 decision มีได้ 1 plan บันทึกทั้งหมดหรือไม่บันทึกเลย
หลังส่งแล้ว decision จะเป็น `IN_REVIEW` ใน `GET /optimization-decisions`
""",
    responses={
        400: {"description": "DB ปฏิเสธการบันทึก"},
        409: {"description": "decision ไม่ใช่ `PENDING` แล้ว (ส่ง plan ไปแล้ว / อนุมัติ / ปฏิเสธ)"},
        422: {"description": "ไม่พบ `decision_id` หรือส่งซ้ำในคำขอ"},
    },
)
def create_pending_tasks(payload: PendingTaskBatchCreate):
    return service.create_pending(payload.tasks)


@router.get(
    "",
    response_model=PendingTaskListResponse,
    summary="คิวรออนุมัติ (Review queue)",
    description="""
ใช้กับหน้า **Review queue** ของ web dashboard

- ค่าเริ่มต้นแสดงเฉพาะ `WAITING` ส่ง `status` ได้หลายค่า เช่น `?status=APPROVED&status=REJECTED`
- `reviewed_from` กรอง plan ที่ **อนุมัติ/ปฏิเสธตั้งแต่เวลานี้** (ใช้กับแท็บ "Approved today" / "Rejected today"
  ให้ส่งเวลาเริ่มวันของเครื่องผู้ใช้ เช่น `2026-10-21T00:00:00+07:00`) ไม่มีผลกับ `WAITING`
- `reference_date` = วันที่ของระบบ (หรือ `DEMO_DATE`) ใช้คู่กับเวลาปัจจุบันเพื่อดูว่า `review_deadline` ใกล้หรือเลยแล้ว
- `counts` = จำนวนของแต่ละแท็บ (`approved` / `rejected` นับตาม `reviewed_from` ถ้าส่งมา)
- เรียงตามเวลาที่เข้าคิว (เก่าก่อน) แล้วตาม lot เพื่อให้ plan ของ lot เดียวกันอยู่ติดกัน

แต่ละรายการแนบ `decision` (action ที่เสนอ), `lot`, `product`, `assessment` (ระดับความเสี่ยง = Severity),
`recipe`, `partner`, `reviewer` และ `lot_expired`

### อัปเดตแบบ real-time
subscribe Supabase Realtime ที่ตาราง `pending_tasks` (anon อ่านได้) เมื่อได้ event ให้เรียก route นี้ใหม่
""",
)
def list_pending_tasks(
    status: list[ReviewStatus] = Query([ReviewStatus.WAITING],
                                       description="สถานะที่ต้องการ ส่งได้หลายค่า ค่าเริ่มต้น WAITING"),
    reviewed_from: Optional[datetime] = Query(None, description="กรอง APPROVED / REJECTED ตั้งแต่เวลานี้ (ไม่ใส่ timezone = เวลาไทย)"),
):
    return service.list_pending([s.value for s in status], reviewed_from)


@router.post(
    "/approve",
    response_model=ReviewApproveResponse,
    summary="ผู้จัดการอนุมัติ plan → สร้าง task ให้ staff",
    description="""
อนุมัติได้หลาย plan พร้อมกัน (เช่น ทุก plan ของ lot เดียวกัน หรือเลือกหลายแถว) **ทั้งหมดหรือไม่อนุมัติเลย**

server ทำตามลำดับเดียวกับการสร้าง task เดิม:
1. คัดลอกตัวเลขจาก decision + ข้อความจาก plan เป็น task ใน `ai_recommended_tasks` (สถานะ `PENDING`)
2. มอบหมาย staff ตามหมวดสินค้า (คนที่มีงานค้างน้อยสุด)
3. งานครัวจองชั่วโมงครัว (`estimated_prep_time_mins × batch_count ÷ 60`) ที่วันของ `due_by`
4. ตั้ง plan เป็น `APPROVED` พร้อม `task_id`, `reviewed_by`, `reviewed_at`

ถ้าครัวเต็ม (409) หรือขั้นไหนล้ม server จะลบ task ที่เพิ่งสร้าง คืนชั่วโมงครัว และ plan ยังเป็น `WAITING`
staff mobile app เห็นงานทันทีผ่าน Realtime ของ `ai_recommended_tasks`
""",
    responses={400: {"description": "DB ปฏิเสธการบันทึก (ย้อนกลับแล้ว)"}, **REVIEW_ERRORS},
)
def approve_pending_tasks(payload: ReviewApprove):
    return service.approve(payload.review_ids, payload.manager_id, payload.review_note)


@router.post(
    "/reject",
    response_model=ReviewRejectResponse,
    summary="ผู้จัดการปฏิเสธ plan",
    description="""
ปฏิเสธได้หลาย plan พร้อมกัน **ทั้งหมดหรือไม่ปฏิเสธเลย** ต้องใส่เหตุผล (`review_note`) ไม่มี task ถูกสร้าง

decision ที่ถูกปฏิเสธจะเป็น `REJECTED` และ LLM จะไม่หยิบไปทำซ้ำ
ถ้า lot ไม่เหลือ decision ที่รออนุมัติหรือมี task แล้วในรอบสแกนนั้น server จะตั้ง lot กลับเป็น `IDLE`
(เฉพาะ lot ที่เป็น `CHECKED`) เพื่อให้ AI pipeline รอบหน้าวางแผนใหม่ ดูได้ใน `lots_reset`
""",
    responses=REVIEW_ERRORS,
)
def reject_pending_tasks(payload: ReviewReject):
    return service.reject(payload.review_ids, payload.manager_id, payload.review_note)


@router.post(
    "/{review_id}/undo-auto",
    response_model=UndoAutoResponse,
    summary="ผู้จัดการย้อนการอนุมัติของ AI (Auto-approve)",
    description="""
ใช้ได้กับ plan ที่ `approved_by_agent = true` ภายใน `undo_minutes` ของกติกา (ดู `undo_until`) และ task ยังเป็น `PENDING`
ย้อนทั้งชุดของ lot นั้นที่ agent อนุมัติพร้อมกัน: ลบ task (staff app เห็นงานหายไปทันที) แล้ว plan กลับเป็น `WAITING`
ให้ผู้จัดการตัดสินเอง และ agent จะไม่อนุมัติ plan นี้อีก (`agent_undone_at`)
""",
    responses={403: {"description": "ไม่ใช่ MANAGER ที่ active"}, 404: {"description": "ไม่พบ `review_id`"},
               409: {"description": "ไม่ได้อนุมัติโดย agent, เกินเวลาย้อน หรือ staff เริ่มงานแล้ว"}},
)
def undo_auto_approve(review_id: UUID, body: UndoAutoRequest):
    return auto_approve.undo(str(review_id), body.staff_id)


@router.get(
    "/{review_id}",
    response_model=PendingTaskDetail,
    summary="รายละเอียด plan",
    description="plan ทั้งแถว พร้อม decision (รวม `alternatives` ทางเลือกอื่นของ Optimizer), lot, สินค้า, ความเสี่ยง, สูตรเต็ม และ partner เต็ม",
    responses={404: {"description": "ไม่พบ `review_id`"}},
)
def get_pending_task(review_id: UUID):
    return service.get_pending(str(review_id))
