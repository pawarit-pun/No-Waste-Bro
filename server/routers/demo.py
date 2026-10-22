from fastapi import APIRouter, HTTPException
from postgrest.exceptions import APIError

from core.dates import today_bkk
from db.supabase import supabase
from services.pipeline import ACTIVE_STATUSES, TABLE as PIPELINE_TABLE, _close_stale_runs

router = APIRouter(prefix="/demo", tags=["Demo"])


@router.post(
    "/reset",
    summary="ล้างข้อมูล demo ให้ทุก lot กลับเป็น IDLE (พร้อมรัน AI pipeline)",
    description="""
ทำเหมือน `python -m scripts.demo reset` แต่กดจาก dashboard ได้ (ใช้ service role ของ server เรียกฟังก์ชันใน DB)

`demo_reset(วันของระบบ)` ลบ **ทุก** plan ในคิว (`pending_tasks`), task, decision, ผลสแกน, forecast run
ลบ lot ที่เกิดจาก demo คืนค่า lot ตั้งต้น (**ai_status = IDLE**, วันที่เลื่อนมาที่วัน demo) และคืนชั่วโมงครัวทั้งหมด

**ไม่เรียก `demo_seed`** เพราะ seed สแกนทุก lot แล้วตั้งเป็น CHECKED ทำให้ AI pipeline ไม่มี lot ให้สแกน
ถ้าต้องการ task ตัวอย่างให้ mobile app ใช้ `python -m scripts.demo reset-seed` ในเครื่องแทน

วันของระบบ = `DEMO_DATE` ถ้าตั้งไว้ ไม่งั้นวันนี้ตามเวลาไทย

⚠ **ลบข้อมูลจริงทั้งหมดของรอบก่อน** รวมถึงผลของ AI pipeline จริง ใช้สำหรับเตรียม demo เท่านั้น
ถ้ามีรอบ AI pipeline กำลังรันอยู่จะไม่ยอมล้าง (409)
""",
    responses={
        409: {"description": "มีรอบ AI pipeline ที่ยังรันอยู่"},
        500: {"description": "ฟังก์ชัน demo ใน DB ล้ม (เช่น ยังไม่ได้รัน scripts/demo_functions.sql)"},
    },
)
def reset_demo() -> dict:
    _close_stale_runs()   # รอบที่ค้างเกิน 20 นาที → FAILED (กฎเดียวกับตอนสั่งรัน)
    active = (supabase.table(PIPELINE_TABLE).select("pipeline_run_id, status")
                .in_("status", ACTIVE_STATUSES).limit(1).execute()).data
    if active:
        raise HTTPException(409, f"Pipeline run '{active[0]['pipeline_run_id']}' is still {active[0]['status']}")

    day = today_bkk().isoformat()
    try:
        reset = supabase.rpc("demo_reset", {"p_today": day}).execute().data
    except APIError as e:
        raise HTTPException(500, f"Demo reset failed: {e.message}")
    idle = (supabase.table("inventory_lots").select("lot_id", count="exact")
              .eq("ai_status", "IDLE").limit(1).execute()).count or 0
    return {"demo_date": day, "reset": reset, "idle_lots": idle}
