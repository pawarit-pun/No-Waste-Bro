"""Manager Agent (แชทผู้ช่วย AI ของผู้จัดการ) — อ่านข้อมูลอย่างเดียว คำตอบภาษาไทย"""
from typing import Any, Literal, Optional

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
