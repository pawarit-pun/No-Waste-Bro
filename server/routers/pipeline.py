from uuid import UUID

from fastapi import APIRouter, Query, status

from schemas.pipeline import PipelineRunCreate, PipelineRunRow, PipelineRunUpdate
from services.pipeline import get_run, list_runs, start_run, update_run

router = APIRouter(prefix="/ai/pipeline-runs", tags=["AI Pipeline"])


@router.post(
    "",
    response_model=PipelineRunRow,
    status_code=status.HTTP_202_ACCEPTED,
    summary="สั่งรัน AI ทั้ง 3 ขั้น (ไม่รอผล)",
    description="""
สั่ง worker (Lambda แยก) รัน AI ต่อกันตามลำดับ แล้ว **ตอบกลับทันที** ด้วยรอบที่สร้าง (`status = QUEUED`)

| ขั้น | ทำอะไร | ผลที่บันทึก |
| --- | --- | --- |
| `SCAN` | Risk Scanner + Forecaster (`AI/risk_forecaster/run_scan.py`) | `lot_risk_assessments` ได้ `run_id` |
| `OPTIMIZE` | Optimizer กับรอบสแกนนั้น (`AI/food_waste_optimizer/run_optimize.py`) | `optimization_decisions` |
| `TASKS` | LLM Task Agent (`AI/llm-task-agent/main.py`) | `ai_recommended_tasks` → mobile app เด้งผ่าน Realtime |

- ติดตามผลด้วย `GET /ai/pipeline-runs/{pipeline_run_id}` หรือ Supabase Realtime ตาราง `pipeline_runs`
- จบก่อนครบ 3 ขั้นได้ ถ้าไม่มีอะไรต้องทำต่อ (ไม่มี lot IDLE / ไม่มี lot HIGH / CRITICAL / ได้ 0 decision) → `SUCCEEDED` + `message`
- ทั้ง pipeline รันได้ทีละรอบ รอบที่ค้าง `QUEUED` / `RUNNING` เกิน 20 นาทีจะถูกตั้งเป็น `FAILED` อัตโนมัติ
- ⚠ เขียนข้อมูลจริง: สถานะ lot, ผลสแกน, decision, task และ **จองชั่วโมงครัว**
""",
    responses={
        409: {"description": "มีรอบที่ยังรันอยู่"},
        502: {"description": "เรียก worker ไม่ได้ (รอบนี้ถูกตั้งเป็น FAILED)"},
        503: {"description": "server ยังไม่ได้ตั้งค่า worker (`PIPELINE_FUNCTION_NAME`) เช่น ตอนรันในเครื่อง"},
    },
)
def create_pipeline_run(body: PipelineRunCreate = PipelineRunCreate()):
    return start_run(body.stop_after)


@router.get(
    "",
    response_model=list[PipelineRunRow],
    summary="รอบ pipeline ล่าสุด",
)
def get_pipeline_runs(limit: int = Query(10, ge=1, le=100, description="จำนวนรอบ ใหม่สุดก่อน")):
    return list_runs(limit)


@router.get(
    "/{pipeline_run_id}",
    response_model=PipelineRunRow,
    summary="สถานะของรอบ pipeline",
    description="""
| ช่อง | ความหมาย |
| --- | --- |
| `status` | QUEUED → RUNNING → SUCCEEDED / FAILED |
| `current_step` | SCAN / OPTIMIZE / TASKS (ขั้นที่กำลังทำ หรือขั้นสุดท้ายที่ทำ) |
| `run_id` | รอบสแกน ใช้กับ `GET /optimization-decisions?run_id=` |
| `at_risk_lots` / `decisions_created` / `tasks_created` | ผลของแต่ละขั้น |
| `failed_batches` | batch ของ `POST /tasks` ที่ไม่ผ่าน (decision ยังเป็น PENDING ให้ผู้จัดการดู) |
| `steps` | สรุปและ log ท้าย ๆ ของแต่ละขั้น ใช้ดูว่าพังตรงไหน |
""",
    responses={404: {"description": "ไม่พบรอบนี้"}},
)
def get_pipeline_run(pipeline_run_id: UUID):
    return get_run(pipeline_run_id)


@router.patch(
    "/{pipeline_run_id}",
    response_model=PipelineRunRow,
    summary="(ภายใน) worker อัปเดตสถานะของรอบ",
    description="""
**สำหรับ `AI/pipeline/worker.py` เท่านั้น** ส่งเฉพาะ field ที่เปลี่ยน

- `status = RUNNING` ครั้งแรก → server ใส่ `started_at` ให้
- `status = SUCCEEDED / FAILED` → server ใส่ `finished_at` ให้ และรอบนั้นแก้ต่อไม่ได้ (409)
""",
    responses={404: {"description": "ไม่พบรอบนี้"}, 409: {"description": "รอบนี้จบไปแล้ว"}},
)
def patch_pipeline_run(pipeline_run_id: UUID, body: PipelineRunUpdate):
    return update_run(pipeline_run_id, body)
