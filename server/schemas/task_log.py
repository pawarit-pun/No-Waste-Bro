"""Task log (GET /task-log): task ที่อนุมัติแล้ว + ประวัติสถานะ"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from schemas.responses import StaffRef, TaskListItem


class TaskEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    event_type: str = Field(..., description="CREATED / STARTED / COMPLETED / REJECTED")
    from_status: Optional[str] = None
    to_status: str
    staff_id: Optional[str] = None
    quantity: Optional[int] = Field(None, description="จำนวนที่ทำจริง (COMPLETED)")
    note: Optional[str] = Field(None, description="เหตุผลที่ปฏิเสธ (REJECTED)")
    backfilled: bool = Field(False, description="เติมย้อนหลังจาก created_at / completed_at (ไม่ใช่เวลาจาก trigger)")
    created_at: datetime


class TaskReviewRef(BaseModel):
    review_id: str
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    approved_by_agent: bool = Field(False, description="true = AI อนุมัติเองตามกติกา Auto-approve")
    reviewer: Optional[StaffRef] = Field(None, description="ผู้จัดการที่อนุมัติ (หรือเจ้าของกติกา ถ้า AI อนุมัติ)")


class TaskLogItem(TaskListItem):
    events: list[TaskEvent] = Field(..., description="timeline เรียงตามเวลา")
    review: Optional[TaskReviewRef] = Field(None, description="plan ที่เป็นที่มาของ task")
    is_overdue: bool = Field(..., description="ยังไม่จบและเลย due_by แล้ว (เทียบกับเวลาของระบบ)")
    minutes_late: Optional[int] = None
    started_at: Optional[datetime] = Field(None, description="staff กดรับงาน")
    finished_at: Optional[datetime] = Field(None, description="เสร็จหรือปฏิเสธ")
    wait_minutes: Optional[int] = Field(None, description="จากอนุมัติจนเริ่มงาน")
    work_minutes: Optional[int] = Field(None, description="จากเริ่มจนเสร็จ")
    last_event: Optional[TaskEvent] = None


class TaskLogCounts(BaseModel):
    pending: int
    in_progress: int
    completed: int
    rejected: int
    overdue: int
    total: int


class TaskLogResponse(BaseModel):
    reference_date: date
    since: datetime
    events_available: bool = Field(..., description="false = ยังไม่ได้รัน scripts/task_events.sql (timeline มีแค่เวลาสร้าง/เสร็จ)")
    counts: TaskLogCounts = Field(..., description="นับทุกสถานะก่อนกรอง status")
    items: list[TaskLogItem]
