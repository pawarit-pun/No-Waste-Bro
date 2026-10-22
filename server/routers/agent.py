from fastapi import APIRouter

from schemas.agent import AgentAskRequest, AgentAskResponse, AgentWarmupResponse
from services import agent

router = APIRouter(prefix="/agent", tags=["Manager Agent"])


@router.post(
    "/ask",
    response_model=AgentAskResponse,
    summary="ถามผู้ช่วย AI ของผู้จัดการ",
    description="""
แชทของ web dashboard (ภาษาไทย) **อ่านข้อมูลอย่างเดียว** ไม่อนุมัติ ไม่สร้าง task ไม่เปลี่ยนราคา

agent (Lambda `ManagerAgentFunction`) เรียก tool เพื่อดึงข้อมูลจริงผ่าน API นี้:
ภาพรวมร้าน, lot เสี่ยง, ข้อมูล lot, task, แผนของ Optimizer, อธิบายเหตุผลของ decision,
**what-if** (รัน Optimizer ใหม่แบบ dry-run: ห้ามลดราคา / บังคับส่วนลด / partner ไม่มา / ชั่วโมงครัว / ยอดขาย x เท่า)
และค้น SOP จาก Knowledge Base

ตัวเลข วันที่ เวลา และรหัส lot ในคำตอบถูกตรวจกับผลของ tool ก่อนส่ง ไม่ผ่าน → ลองแก้ / ใช้ model สำรอง /
`model_used = TEMPLATE` (ข้อความสั้น + การ์ดใน `artifacts`)

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
