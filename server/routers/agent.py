from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Query

from schemas.agent import (AgentAskRequest, AgentAskResponse, AgentRunBatch, AgentRunBatchResponse, AgentWarmupResponse,
                           DailyReportListResponse, NotificationListResponse, ProposalDecision, ProposalRow, ReadResult,
                           WatchResponse, AutoApprovePolicy, AutoApprovePolicyUpdate, AutoApproveRequest,
                           AutoApproveResponse)
from services import agent, auto_approve

router = APIRouter(prefix="/agent", tags=["Manager Agent"])
reports_router = APIRouter(tags=["Daily Reports"])     # GET /daily-reports (ลงทะเบียนใน main.py)


@router.post(
    "/ask",
    response_model=AgentAskResponse,
    summary="ถามผู้ช่วย AI ของผู้จัดการ",
    description="""
แชทของ web dashboard (ภาษาไทย) agent **เปลี่ยนข้อมูลเองไม่ได้** ไม่อนุมัติ ไม่สร้าง task ไม่เปลี่ยนราคา

agent (Lambda `ManagerAgentFunction`) เรียก tool เพื่อดึงข้อมูลจริงผ่าน API นี้:
ภาพรวมร้าน, lot เสี่ยง, ข้อมูล lot, task, แผนของ Optimizer, อธิบายเหตุผลของ decision,
**what-if** (รัน Optimizer ใหม่แบบ dry-run: ห้ามลดราคา / บังคับส่วนลด / partner ไม่มา / ชั่วโมงครัว / ยอดขาย x เท่า),
ค้น SOP จาก Knowledge Base และ **เสนองาน** (`artifacts` ชนิด `proposal` มี `proposal.proposal_id` ให้กดยืนยันที่
`POST /agent/proposals/{id}/execute`)

ตัวเลข วันที่ เวลา และรหัส lot ในคำตอบถูกตรวจกับผลของ tool ก่อนส่ง ไม่ผ่าน → ลองแก้ / ใช้ model สำรอง /
`model_used = TEMPLATE` (ข้อความสั้น + การ์ดใน `artifacts`) ทุกรอบบันทึกใน `agent_runs`

ใช้เวลา 3-15 วินาที (คำถามแรกหลัง deploy อาจนานกว่า เรียก `POST /agent/warmup` ตอนเปิดแผงแชทก่อน)
""",
    responses={502: {"description": "เรียก agent ไม่สำเร็จ"}, 503: {"description": "ยังไม่ได้ตั้ง AGENT_FUNCTION_NAME (รันในเครื่อง)"},
               504: {"description": "agent ตอบไม่ทันเวลา"}},
)
def ask_agent(body: AgentAskRequest):
    return agent.ask(body)


@router.post("/warmup", response_model=AgentWarmupResponse, summary="ปลุก agent ไว้ก่อน (ไม่รอผล)")
def warmup_agent():
    return {"started": agent.warm_up()}


@router.post(
    "/watch",
    response_model=WatchResponse,
    summary="ตรวจงานค้างตอนนี้ (ไม่รอผล)",
    description="""
สั่ง agent ตรวจทันทีแบบเดียวกับรอบอัตโนมัติทุก 1 ชั่วโมง (EventBridge 07:00-22:00) แต่ตรวจแม้อยู่นอกเวลาร้าน:
task เลยกำหนด, plan ใกล้ / เลยเวลาอนุมัติ, lot ค้าง `PROCESSING` ผลเป็นแจ้งเตือนใน `GET /agent/notifications`
(ประมาณ 3-10 วินาที) เรื่องที่แจ้งไปแล้วไม่แจ้งซ้ำ
""",
)
def watch():
    return {"started": agent.watch_now()}


@router.post(
    "/daily/{kind}",
    response_model=WatchResponse,
    summary="ทำรายงานประจำวันตอนนี้ (ไม่รอผล)",
    description="""
- `morning` = **Morning brief** ของ pipeline รอบล่าสุดที่สำเร็จ (ไม่เริ่ม pipeline ใหม่): แผนต่อวิธี, kg, กำไรที่คาดเทียบ baseline,
  ชั่วโมงครัว, ความผิดปกติ ปกติทำเองเมื่อ pipeline สำเร็จ (และรอบเช้า 07:30 agent เริ่ม pipeline เอง ถ้า `AgentAutoRun=true`)
- `evening` = **Evening summary**: งานที่ทำจริงทั้งวัน, kg ที่ขายต่อ / ฝังกลบ, งานค้าง ปกติทำเองตอน 21:30

ผลอยู่ใน `GET /daily-reports` (ทับรายงานวันเดียวกัน) และแจ้งเตือนในกระดิ่ง ใช้เวลา 5-20 วินาที
""",
)
def daily_now(kind: Literal["morning", "evening"]):
    return {"started": agent.daily_now(kind)}


@reports_router.get(
    "/daily-reports",
    response_model=DailyReportListResponse,
    summary="รายงานประจำวันของ agent (หน้า Overview)",
    description="Morning brief + Evening summary ย้อนหลัง `days` วันถึงวันของระบบ ตัวเลขกำไรเป็นค่าที่ Optimizer คาด "
                "อัปเดตแบบ real-time: subscribe ตาราง `daily_reports`",
)
def daily_reports(days: int = Query(7, ge=0, le=60)):
    return agent.list_daily_reports(days)


# ---------------- แจ้งเตือน ----------------

@router.get(
    "/notifications",
    response_model=NotificationListResponse,
    summary="แจ้งเตือนของ agent (กระดิ่งใน dashboard)",
    description="ใหม่ก่อน แต่ละรายการแนบ `proposal` (ถ้ามี) อัปเดตแบบ real-time: subscribe ตาราง `agent_notifications` "
                "และ `agent_proposals` แล้วเรียก route นี้ใหม่",
)
def list_notifications(
    unread: bool = Query(False, description="true = เฉพาะที่ยังไม่อ่าน"),
    limit: int = Query(30, ge=1, le=100),
    dedupe_key: Optional[str] = Query(None, description="ใช้ภายใน: agent เช็คว่าแจ้งเรื่องนี้ไปแล้วหรือยัง"),
):
    return agent.list_notifications(unread, limit, dedupe_key)


@router.post("/notifications/read-all", response_model=ReadResult, summary="อ่านแจ้งเตือนทั้งหมดแล้ว")
def read_all():
    return agent.mark_read()


@router.post("/notifications/{notification_id}/read", response_model=ReadResult, summary="อ่านแจ้งเตือนนี้แล้ว")
def read_one(notification_id: UUID):
    return agent.mark_read(str(notification_id))


# ---------------- ข้อเสนอ ----------------

@router.get("/proposals/{proposal_id}", response_model=ProposalRow, summary="ข้อเสนอ 1 รายการ")
def get_proposal(proposal_id: UUID):
    return agent.get_proposal(str(proposal_id))


@router.post(
    "/proposals/{proposal_id}/execute",
    response_model=ProposalRow,
    summary="ผู้จัดการยืนยันข้อเสนอ (server ทำตาม)",
    description="""
| `kind` | สิ่งที่ server ทำ |
| --- | --- |
| `RUN_PIPELINE` | `POST /ai/pipeline-runs` ด้วย `stop_after` ของข้อเสนอ (409 ถ้ามีรอบรันอยู่) |
| `RELEASE_LOTS` | `release_lot_if_idle` ทีละ lot: คืนเป็น `IDLE` เฉพาะ lot ที่ไม่มีงานค้างและไม่มี decision รอ |
| `BLOCK_KITCHEN` | จองชั่วโมงที่เหลือของครัวในวันนั้น (ไม่เกินที่เหลือจริง) แล้วเริ่ม pipeline ถ้า `then_run_pipeline` |

ต้องเป็นผู้จัดการ (role MANAGER) และข้อเสนอยัง `PROPOSED` (ไม่หมดอายุ) ทำไม่สำเร็จ → สถานะ `FAILED` + `result.error`
""",
    responses={403: {"description": "ไม่ใช่ผู้จัดการ"}, 404: {"description": "ไม่พบข้อเสนอ / staff"},
               409: {"description": "ข้อเสนอไม่ใช่ PROPOSED แล้ว หรือทำไม่ได้กับข้อมูลตอนนี้"}},
)
def execute_proposal(proposal_id: UUID, body: ProposalDecision):
    return agent.execute_proposal(str(proposal_id), body.staff_id)


@router.post("/proposals/{proposal_id}/dismiss", response_model=ProposalRow, summary="ไม่ทำตามข้อเสนอ")
def dismiss_proposal(proposal_id: UUID, body: ProposalDecision):
    return agent.dismiss_proposal(str(proposal_id), body.staff_id)


# ---------------- Phase 4: Auto-approve ----------------

@router.get("/policies/auto-approve", response_model=AutoApprovePolicy, summary="กติกา Auto-approve + จำนวนที่ AI อนุมัติวันนี้")
def get_auto_approve_policy():
    return auto_approve.get_policy()


@router.put(
    "/policies/auto-approve",
    response_model=AutoApprovePolicy,
    summary="ผู้จัดการเปิด/ปิด และตั้งกติกา Auto-approve",
    description="""
เปิดแล้ว Manager Agent จะอนุมัติ plan เองหลัง pipeline เสร็จและทุกรอบตรวจรายชั่วโมง **เฉพาะ plan ที่ผ่านทุกข้อ**:
วิธีอยู่ใน `actions`, ลดราคาไม่เกิน `max_discount_pct`, ราคาไม่ต่ำกว่า `min_allowed_price`,
`action_quantity × ราคาขายปัจจุบัน` ไม่เกิน `max_value_thb`, ไม่มีทางเลือกของ Optimizer ที่กำไรคาดสูงกว่า,
ข้อความไม่ใช่ `TEMPLATE`, lot ยังไม่หมดอายุ, เหลือเวลาก่อน `review_deadline` อย่างน้อย `min_minutes_before_deadline`
และทุก plan ที่รอของ lot เดียวกันผ่านด้วย (อนุมัติทั้ง lot) ไม่เกิน `daily_limit` ต่อวัน

`actions` เลือกได้จาก MARKDOWN / DONATE / ANIMAL_FEED / COMPOST / ANAEROBIC_DIGESTION
(งานครัวใช้ชั่วโมงครัว ฝังกลบ / ทิ้งย้อนไม่ได้ จึงต้องให้ผู้จัดการอนุมัติเอง)
`manager_id` เป็นเจ้าของกติกา: plan ที่ agent อนุมัติจะมี `reviewed_by` = คนนี้ และ `approved_by_agent = true`
""",
    responses={403: {"description": "ไม่ใช่ MANAGER ที่ active"}, 422: {"description": "actions ไม่ถูกต้อง"}},
)
def put_auto_approve_policy(body: AutoApprovePolicyUpdate):
    return auto_approve.put_policy(body.manager_id, body.enabled, body.params.model_dump())


# ---------------- route ภายใน (agent ใช้) ----------------

@router.post(
    "/auto-approve",
    response_model=AutoApproveResponse,
    summary="ภายใน: agent อนุมัติ plan ที่เข้าเกณฑ์ Auto-approve",
    description="server ตรวจกติกาซ้ำทุกข้อกับข้อมูลล่าสุด แล้วอนุมัติทีละ lot ด้วยขั้นตอนเดียวกับ `POST /pending-tasks/approve` "
                "plan ที่ไม่ผ่านอยู่ใน `skipped` พร้อมรหัส (AA_*) ไม่มี auth (prototype)",
    responses={409: {"description": "Auto-approve ปิดอยู่ หรือยังไม่มีผู้จัดการเจ้าของกติกา"}},
)
def run_auto_approve(body: AutoApproveRequest):
    return auto_approve.auto_approve(body.review_ids, str(body.agent_run_id) if body.agent_run_id else None)


@router.post(
    "/runs",
    status_code=201,
    response_model=AgentRunBatchResponse,
    summary="ภายใน: agent บันทึกผลของรอบเหตุการณ์ / ตรวจตามเวลา",
    description="บันทึก `agent_runs` + ข้อเสนอ + แจ้งเตือนในคำขอเดียว แจ้งเตือนที่ `dedupe_key` ซ้ำถูกข้าม (พร้อมข้อเสนอของมัน) "
                "ไม่มี auth เหมือน `PATCH /ai/pipeline-runs` (prototype)",
)
def record_run(batch: AgentRunBatch):
    return agent.record_batch(batch)
