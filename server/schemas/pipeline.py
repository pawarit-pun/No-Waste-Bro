"""AI pipeline: Risk Scanner → Optimizer → LLM Task Agent ที่รันบน worker (Lambda แยก)"""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PipelineStep(str, Enum):
    SCAN = "SCAN"          # 1) Risk Scanner + Forecaster → POST /risk-assessments
    OPTIMIZE = "OPTIMIZE"  # 2) Optimizer → POST /optimization-decisions
    TASKS = "TASKS"        # 3) LLM Task Agent → POST /tasks


class PipelineStatus(str, Enum):
    QUEUED = "QUEUED"        # สร้างรอบแล้ว รอ worker เริ่ม
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"  # จบครบ (หรือจบก่อนเพราะไม่มีอะไรต้องทำต่อ ดู message)
    FAILED = "FAILED"


FINAL_STATUSES = (PipelineStatus.SUCCEEDED, PipelineStatus.FAILED)


class PipelineRunCreate(BaseModel):
    stop_after: PipelineStep = Field(
        PipelineStep.TASKS,
        description="หยุดหลังขั้นไหน: SCAN = สแกนอย่างเดียว, OPTIMIZE = สแกน + บันทึก decision, "
                    "TASKS = ครบ 3 ขั้นจนสร้าง task ให้ staff (ค่าเริ่มต้น)",
    )

    model_config = {"json_schema_extra": {"examples": [{"stop_after": "TASKS"}]}}


class PipelineRunUpdate(BaseModel):
    """worker ส่งเฉพาะ field ที่เปลี่ยน"""
    status: Optional[PipelineStatus] = None
    current_step: Optional[PipelineStep] = None
    run_id: Optional[UUID] = Field(None, description="รอบสแกนที่ Risk Scanner สร้าง")
    at_risk_lots: Optional[int] = Field(None, ge=0, description="lot HIGH / CRITICAL ที่ส่งต่อ Optimizer")
    decisions_created: Optional[int] = Field(None, ge=0)
    tasks_created: Optional[int] = Field(None, ge=0)
    failed_batches: Optional[int] = Field(None, ge=0, description="batch ของ POST /tasks ที่ไม่ผ่าน (เช่น ครัวเต็ม)")
    message: Optional[str] = None
    error: Optional[str] = None
    steps: Optional[dict[str, Any]] = Field(None, description="สรุปผลและ log ท้าย ๆ ของแต่ละขั้น (แทนที่ทั้งก้อน)")
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class PipelineRunRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    pipeline_run_id: UUID
    status: str = Field(..., description="QUEUED / RUNNING / SUCCEEDED / FAILED")
    current_step: Optional[str] = Field(None, description="ขั้นที่กำลังทำ / ทำล่าสุด: SCAN / OPTIMIZE / TASKS")
    stop_after: str
    run_id: Optional[UUID] = None
    at_risk_lots: Optional[int] = None
    decisions_created: Optional[int] = None
    tasks_created: Optional[int] = None
    failed_batches: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None
    steps: dict[str, Any] = Field(default_factory=dict)
    requested_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
