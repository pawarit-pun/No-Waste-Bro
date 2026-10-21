from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query

from schemas.optimizer import OptimizeRunResponse, ScanRunsResponse
from services.optimizer import list_scan_runs, run_optimize

router = APIRouter(prefix="/ai", tags=["Optimizer"])


@router.post(
    "/optimize",
    response_model=OptimizeRunResponse,
    summary="รัน Optimizer กับรอบสแกน (ขั้นที่ 4-5 ในคำขอเดียว)",
    description="""
**ทางเชื่อม Risk Scanner + Forecaster → Optimizer → RAG** server อ่านข้อมูลชุดเดียวกับ `GET /ai/optimize-inputs`
แล้วรัน Optimizer (โค้ดใน `AI/food_waste_optimizer`) ตัดสินใจว่าแต่ละ lot ควรขายราคาปกติ / ลดราคา / ส่งเข้าครัว /
บริจาค / ส่ง partner กำจัด กี่หน่วย ให้ขาดทุนน้อยที่สุด

| `dry_run` | ทำอะไร |
| --- | --- |
| `true` (ค่าเริ่มต้น) | คำนวณอย่างเดียว ไม่เขียน DB (ปลอดภัยสำหรับ Try it out) |
| `false` | บันทึก decision ลง `optimization_decisions` (ตรวจกฎเดียวกับ `POST /optimization-decisions`) และคืน lot ที่ขายราคาปกติได้หมดเป็น `IDLE` |

- ไม่ส่ง `run_id` = รอบล่าสุดที่สแกนวันเดียวกับ `DEMO_DATE` และยังมี lot HIGH / CRITICAL รอตัดสินใจ
  (ดูได้จาก `GET /ai/optimize-runs` → `suggested_run_id`) ถ้าไม่มีรอบแบบนั้น = รอบสแกนล่าสุด
- assessment ที่มี decision แล้วในรอบนี้จะถูกข้าม (เรียกซ้ำได้ ไม่บันทึกซ้ำ)
- เวลาที่ใช้คิด = `DEMO_DATE` (หรือวันนี้) + เวลาไทยตอนที่เรียก ใช้เช็คช่วงเวลารับของของ partner และชั่วโมงครัวที่เหลือ
- `allocations` = น้ำหนัก (kg), สัดส่วน (%) และเงินของแต่ละส่วน **ไม่บันทึกลงตาราง** ส่งให้ส่วนอื่นใช้
- **ยังไม่จองครัวในขั้นนี้** จะจองตอนผู้จัดการอนุมัติ plan (`POST /pending-tasks/approve`)
""",
    responses={
        422: {"description": "แผนไม่ผ่านการตรวจกฎ หรือ server ไม่รับ decision (ไม่มีอะไรถูกบันทึก)"},
        503: {"description": "โหลด Optimizer ไม่ได้ (ยังไม่ได้ติดตั้ง numpy / scipy หรือหาโฟลเดอร์ไม่เจอ)"},
    },
)
def optimize(
    run_id: Optional[UUID] = Query(None, description="รอบสแกน ไม่ส่ง = รอบที่พร้อมตัดสินใจ (suggested_run_id ของ GET /ai/optimize-runs)"),
    days_ahead: int = Query(1, ge=0, le=7, description="วางแผนครัวตั้งแต่วันนี้ถึงกี่วันข้างหน้า"),
    dry_run: bool = Query(True, description="true = คำนวณอย่างเดียว, false = บันทึก decision + คืน lot ที่ไม่ต้องทำอะไรเป็น IDLE"),
    release_no_action_lots: bool = Query(True, description="คืน lot ที่ขายราคาปกติได้หมดเป็น IDLE ให้สแกนใหม่พรุ่งนี้"),
    include_plan: bool = Query(False, description="แนบแผนเต็ม (ต่อ lot, งานครัว, เที่ยวรับของ, เหตุผล)"),
):
    return run_optimize(str(run_id) if run_id else None, days_ahead, dry_run, release_no_action_lots, include_plan)


@router.get(
    "/optimize-runs",
    response_model=ScanRunsResponse,
    summary="รอบสแกนทั้งหมด และรอบไหนพร้อมให้ Optimizer ตัดสินใจ (อ่านอย่างเดียว)",
    description="""
อ่านจาก `lot_risk_assessments` + `inventory_lots` + `optimization_decisions` ไม่เขียนอะไร

| ช่อง | ความหมาย |
| --- | --- |
| `scan_date` | วันที่ Risk Scanner สแกน (= วันหมดอายุ − `days_to_expiry`) |
| `at_risk` | จำนวน lot ระดับ HIGH / CRITICAL |
| `decided` | lot ที่มี decision ใน `optimization_decisions` แล้ว |
| `pending` | lot HIGH / CRITICAL สถานะ `PROCESSING` ที่ยังไม่มี decision (Optimizer จะตัดสินใจให้) |
| `ready` | `scan_date` = `reference_date` (DEMO_DATE) และ `pending` > 0 |

`suggested_run_id` = รอบล่าสุดที่ `ready` ใช้เป็นค่าเริ่มต้นของ `POST /ai/optimize` และ `run_optimize.py`
""",
)
def optimize_runs():
    return list_scan_runs()