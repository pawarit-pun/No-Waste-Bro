from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Query

from schemas.enums import ActionType
from schemas.task_log import TaskLogResponse
from services import task_log as service

router = APIRouter(prefix="/task-log", tags=["Task Log"])


@router.get(
    "",
    response_model=TaskLogResponse,
    summary="Task log: task ที่อนุมัติแล้ว + สถานะและประวัติ",
    description="""
ใช้กับหน้า **Task log** ของ web dashboard ให้ผู้จัดการดูว่างานที่อนุมัติไป (เองหรือ AI auto-approve) เดินไปถึงไหนแล้ว

- คืน task ที่สร้างตั้งแต่ `created_from` (ค่าเริ่มต้น เที่ยงคืนวันนี้ตามเวลาไทย) **รวมกับงานที่ยังไม่จบทั้งหมด** ใหม่ก่อน
- `status` ส่งได้หลายค่า (`PENDING`, `IN_PROGRESS`, `COMPLETED`, `REJECTED`, `OVERDUE`) `counts` นับก่อนกรองสถานะ
- `events` = timeline จาก `task_events` (trigger บันทึกเมื่อสร้าง / รับงาน / เสร็จ / ปฏิเสธ) ถ้ายังไม่ได้รัน
  `scripts/task_events.sql` จะได้แค่เวลาสร้างกับเวลาเสร็จ (`events_available = false`)
- `review` = plan ที่เป็นที่มา: ผู้จัดการที่อนุมัติ หรือ `approved_by_agent = true`
- `is_overdue` เทียบ `due_by` กับเวลาของระบบ (DEMO_DATE + เวลาตอนนี้) `wait_minutes` / `work_minutes` คิดจากเวลาจริงของ event

### อัปเดตแบบ real-time
subscribe Supabase Realtime ที่ `ai_recommended_tasks` และ `task_events` แล้วเรียก route นี้ใหม่
""",
)
def get_task_log(
    created_from: Optional[datetime] = Query(None, description="task ที่สร้างตั้งแต่เวลานี้ (ไม่ใส่ timezone = เวลาไทย)"),
    status: list[Literal["PENDING", "IN_PROGRESS", "COMPLETED", "REJECTED", "OVERDUE"]] = Query(
        [], description="กรองสถานะ ส่งได้หลายค่า ไม่ส่ง = ทุกสถานะ"),
    action_type: Optional[ActionType] = Query(None, description="กรองวิธี"),
    staff_id: Optional[str] = Query(None, description="กรองพนักงานที่ได้รับมอบหมาย"),
):
    return service.list_log(created_from, list(status), action_type.value if action_type else None, staff_id)
