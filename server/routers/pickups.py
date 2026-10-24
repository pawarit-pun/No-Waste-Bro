from fastapi import APIRouter, Query

from schemas.pickups import PickupScheduleResponse
from services import pickups as service

router = APIRouter(prefix="/pickup-schedule", tags=["Pickups"])


@router.get(
    "",
    response_model=PickupScheduleResponse,
    summary="ตารางรอบรับของของ partner + ของที่ต้องส่งมอบ",
    description="""
ใช้กับหน้า **Pickups** ของ web dashboard

- รอบรับ = partner ที่ active × วันในตาราง (`pickup_days`, 1 = จันทร์) ตั้งแต่วันของระบบ (DEMO_DATE) ถึง `days_ahead` วันข้างหน้า
  ช่วงเวลารับ = `pickup_time_start`–`pickup_time_end`
- `items` ของรอบ: task ที่อนุมัติแล้ว (`source = TASK`, `target_partner_id` + `due_by` วันนั้น) และ plan ที่ยังรออนุมัติ (`PLAN`)
- `kg_confirmed` / `kg_waiting` จาก `net_content` ของสินค้า เทียบกับ `capacity_kg` และ `min_kg`
- `costs` ประมาณด้วยสูตรเดียวกับ Optimizer (ค่าเที่ยว + handling − รับซื้อ, DONATION คิดแค่ค่าเที่ยวคงที่)
- `alerts`: `OVER_CAPACITY`, `BELOW_MIN`, `NOT_READY` (ถึงเวลารับแล้วแต่งานยังไม่เสร็จ), `WAITING_APPROVAL`
- รอบในอนาคตที่ Optimizer วางแบบชั่วคราว (provisional) ไม่ถูกบันทึก จึงไม่อยู่ในนี้

### อัปเดตแบบ real-time
subscribe Supabase Realtime ที่ `ai_recommended_tasks` และ `pending_tasks` แล้วเรียก route นี้ใหม่
""",
)
def get_pickup_schedule(days_ahead: int = Query(6, ge=0, le=13, description="จำนวนวันข้างหน้า (0 = วันนี้อย่างเดียว)")):
    return service.schedule(days_ahead)
