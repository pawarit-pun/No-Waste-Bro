"""Manager Agent (แชทผู้ช่วย AI ของผู้จัดการ) — อ่านข้อมูลอย่างเดียว คำตอบภาษาไทย"""
from datetime import date, datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AgentTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(..., max_length=4000)


class AgentContext(BaseModel):
    page: Optional[str] = Field(None, max_length=40, description="หน้าที่ผู้จัดการเปิดอยู่ เช่น overview / inventory / review / tasks")
    lot_id: Optional[str] = Field(None, max_length=20, description="lot ที่เลือกอยู่ (คำถามที่ไม่ระบุ lot หมายถึง lot นี้)")


class AgentAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    history: list[AgentTurn] = Field(default_factory=list, max_length=20, description="บทสนทนาก่อนหน้า (ล่าสุด 10 รอบ)")
    context: AgentContext = Field(default_factory=AgentContext)

    model_config = {"json_schema_extra": {"examples": [
        {"question": "ทำไม LOT-000020 ถึงลดราคาแค่ 20%", "history": [], "context": {"page": "inventory", "lot_id": "LOT-000020"}},
    ]}}


class AgentToolCall(BaseModel):
    name: str
    args: Optional[Any] = None
    ms: int = Field(..., description="เวลาที่ tool ใช้ (มิลลิวินาที)")
    ok: bool


class AgentAskResponse(BaseModel):
    answer: str = Field(..., description="คำตอบภาษาไทย (ผ่านการตรวจตัวเลข / รหัส lot กับข้อมูลจริงแล้ว)")
    model_used: str = Field(..., description="model ที่ตอบ หรือ TEMPLATE (คำตอบของ model ไม่ผ่านการตรวจ ใช้การ์ดแทน)")
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list,
                                            description="การ์ดข้อมูล: snapshot / lot_list / lot / task_list / "
                                                        "lot_explain / what_if / sources")
    warnings: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int


class AgentWarmupResponse(BaseModel):
    started: bool = Field(..., description="true = ส่งคำสั่งปลุก Lambda แล้ว")


# ================= Phase 2: แจ้งเตือน + ข้อเสนอ + บันทึกการทำงาน =================

ProposalKind = Literal["RUN_PIPELINE", "RELEASE_LOTS", "BLOCK_KITCHEN"]
Source = Literal["CHAT", "EVENT", "SCHEDULE"]
Severity = Literal["INFO", "WARNING", "CRITICAL"]


class ProposalRow(BaseModel):
    proposal_id: UUID
    kind: str = Field(..., description="RUN_PIPELINE / RELEASE_LOTS / BLOCK_KITCHEN")
    params: dict[str, Any]
    title: str
    reason: Optional[str] = None
    status: str = Field(..., description="PROPOSED = รอผู้จัดการ, EXECUTED, DISMISSED, FAILED, EXPIRED")
    source: str
    expires_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    result: Optional[dict[str, Any]] = Field(None, description="ผลที่ server ทำ หรือ error")
    created_at: datetime


class NotificationRow(BaseModel):
    notification_id: UUID
    severity: str
    title: str
    message: str
    event_type: Optional[str] = None
    lot_id: Optional[str] = None
    task_id: Optional[UUID] = None
    dedupe_key: Optional[str] = None
    read_at: Optional[datetime] = None
    created_at: datetime
    proposal: Optional[ProposalRow] = Field(None, description="ข้อเสนอที่แนบมา (กดยืนยันได้ถ้ายัง PROPOSED)")


class NotificationListResponse(BaseModel):
    unread: int = Field(..., description="จำนวนที่ยังไม่อ่านทั้งหมด")
    items: list[NotificationRow]


class ProposalDecision(BaseModel):
    staff_id: str = Field(..., description="ผู้จัดการที่กด (role MANAGER)")


class ReadResult(BaseModel):
    updated: int


# ---------- route ภายใน: agent ส่งผลของรอบเหตุการณ์ / ตรวจตามเวลา ----------

class RunRecord(BaseModel):
    trigger: Source
    event_type: Optional[str] = None
    input: dict[str, Any] = Field(default_factory=dict)
    answer: Optional[str] = None
    model_used: Optional[str] = None
    tool_calls: list[Any] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: Optional[int] = None


class ProposalCreate(BaseModel):
    kind: ProposalKind
    params: dict[str, Any] = Field(default_factory=dict)
    title: str = Field(..., max_length=200)
    reason: Optional[str] = Field(None, max_length=1000)
    source: Source = "EVENT"


class NotificationCreate(BaseModel):
    severity: Severity = "INFO"
    title: str = Field(..., max_length=200)
    message: str = Field(..., max_length=2000)
    event_type: Optional[str] = None
    lot_id: Optional[str] = None
    task_id: Optional[UUID] = None
    dedupe_key: Optional[str] = Field(None, max_length=200)
    proposal_ref: Optional[int] = Field(None, ge=0, description="index ใน proposals ของคำขอเดียวกัน")


class DailyReportCreate(BaseModel):
    report_date: date
    kind: Literal["MORNING", "EVENING"]
    metrics: dict[str, Any] = Field(default_factory=dict)
    anomalies: list[dict[str, Any]] = Field(default_factory=list)
    message: Optional[str] = Field(None, max_length=2000)
    model_used: Optional[str] = None


class AgentRunBatch(BaseModel):
    run: RunRecord
    auto_approved: list[UUID] = Field(default_factory=list, description="Phase 4: review_id ที่ agent อนุมัติในรอบนี้ (ผูก agent_run_id)")
    proposals: list[ProposalCreate] = Field(default_factory=list, max_length=20)
    notifications: list[NotificationCreate] = Field(default_factory=list, max_length=50)
    report: Optional[DailyReportCreate] = Field(None, description="Phase 3: รายงานประจำวัน (ทับรายงานวันเดียวกัน kind เดียวกัน)")


class AgentRunBatchResponse(BaseModel):
    agent_run_id: UUID
    notifications: int = Field(..., description="แจ้งเตือนที่บันทึก (ไม่นับที่ซ้ำ dedupe_key)")
    proposals: int
    skipped_duplicates: int
    report_id: Optional[UUID] = None


class DailyReportRow(BaseModel):
    report_id: UUID
    report_date: date
    kind: str = Field(..., description="MORNING = สรุปแผนของวัน, EVENING = สรุปปิดวัน")
    metrics: dict[str, Any] = Field(..., description="ตัวเลขที่ agent คำนวณ (ดู AI/manager_agent/daily.py)")
    anomalies: list[dict[str, Any]] = Field(..., description="[{code, severity, text, lot_ids?}]")
    message: Optional[str] = None
    model_used: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class DailyReportListResponse(BaseModel):
    reference_date: date
    items: list[DailyReportRow] = Field(..., description="ใหม่ก่อน (วันที่ แล้ว EVENING ก่อน MORNING)")


class WatchResponse(BaseModel):
    started: bool


# ---------- Phase 4: Auto-approve ----------

AutoAction = Literal["MARKDOWN", "DONATE", "ANIMAL_FEED", "COMPOST", "ANAEROBIC_DIGESTION"]


class AutoApproveParams(BaseModel):
    actions: list[AutoAction] = Field(["MARKDOWN"], description="วิธีที่ agent อนุมัติเองได้ (ไม่มีงานครัว / ฝังกลบ / ทิ้ง)")
    max_discount_pct: float = Field(30, ge=0, le=90, description="ลดราคาได้ไม่เกิน (%)")
    max_value_thb: float = Field(2000, ge=0, le=100000, description="action_quantity × ราคาขายปัจจุบัน ไม่เกิน (บาท)")
    min_minutes_before_deadline: int = Field(30, ge=0, le=720, description="ต้องเหลือเวลาก่อน review_deadline อย่างน้อย (นาที)")
    daily_limit: int = Field(30, ge=1, le=500, description="plan ต่อวันสูงสุด")
    undo_minutes: int = Field(15, ge=1, le=120, description="ผู้จัดการย้อนได้ภายใน (นาที)")


class AutoApprovePolicyUpdate(BaseModel):
    manager_id: str = Field(..., description="ผู้จัดการที่ตั้งกติกา (เป็นเจ้าของ: plan ที่ agent อนุมัติจะมี reviewed_by = คนนี้)")
    enabled: bool
    params: AutoApproveParams = Field(default_factory=AutoApproveParams)


class AutoApproveToday(BaseModel):
    approved: int = Field(..., description="plan ที่ agent อนุมัติวันนี้ (วันจริงตามเวลาไทย)")
    lots: int
    remaining: int = Field(..., description="อนุมัติได้อีกกี่ plan วันนี้")


class AutoApprovePolicy(BaseModel):
    policy_id: str
    enabled: bool
    params: AutoApproveParams
    owner_staff_id: Optional[str] = None
    owner: Optional[dict[str, Any]] = None
    updated_at: Optional[datetime] = None
    allowed_actions: list[str]
    today: AutoApproveToday


class AutoApproveRequest(BaseModel):
    review_ids: list[UUID] = Field(..., min_length=1, max_length=200, description="plan ที่ agent เลือก (ทุก plan ที่รอของ lot)")
    agent_run_id: Optional[UUID] = None


class AutoApproveSkip(BaseModel):
    review_id: str
    lot_id: Optional[str] = None
    reasons: list[str] = Field(..., description="รหัสกติกาที่ไม่ผ่าน (AA_*) ดู services/auto_approve.py")


class AutoApproveResponse(BaseModel):
    approved: int
    lots: list[str]
    reviews: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    skipped: list[AutoApproveSkip]
    errors: list[dict[str, Any]] = Field(..., description="lot ที่ผ่านกติกาแต่อนุมัติไม่สำเร็จ (เช่น decision ถูกแก้ไปก่อน)")
    undo_minutes: int
    today: AutoApproveToday


class UndoAutoRequest(BaseModel):
    staff_id: str = Field(..., description="ผู้จัดการที่กดย้อน")


class UndoAutoResponse(BaseModel):
    undone: int
    lot_id: str
    review_ids: list[str] = Field(..., description="plan ของ lot เดียวกันที่ agent อนุมัติพร้อมกัน (ย้อนทั้งชุด)")
    deleted_task_ids: list[str]
    undone_by: str
