from fastapi import APIRouter, HTTPException
from postgrest.exceptions import APIError

from db.supabase import supabase
from schemas.responses import RiskAssessmentCreateResponse
from schemas.risk_assessment import RiskAssessmentBatchCreate

router = APIRouter(prefix="/risk-assessments", tags=["Risk Assessments"])


@router.post(
    "",
    status_code=201,
    response_model=RiskAssessmentCreateResponse,
    summary="บันทึกผล Risk Scanner + Forecast",
    description="""
**ขั้นที่ 3 ของ AI Pipeline** บันทึกผลประเมินความเสี่ยงของทุก lot ในรอบสแกนเดียวกัน

| ส่วน | บันทึกที่ |
| --- | --- |
| รอบสแกน (`reference_date`, `model_version`, `run_metrics`) | `forecast_runs` |
| `assessments` | `lot_risk_assessments` |
| `assessments[].shelf` (ลด x% แล้วขายได้เท่าไร) | `lot_shelf_forecasts` |
| `recipe_demand` | `recipe_demand_forecasts` |

- ไม่ส่ง `run_id` = server สร้างให้ แล้วคืนกลับมาใน response
- บันทึกทั้งหมดหรือไม่บันทึกเลย (RPC `save_risk_run` ใน transaction เดียว) ถ้ามีแถวไหนผิด จะไม่มีแถวไหนถูกบันทึก
- ส่งได้ทุก risk level แต่ `optimize-inputs` จะส่งต่อให้ Optimizer เฉพาะ HIGH / CRITICAL
- `shelf`, `recipe_demand`, `sellable_hours`, `reference_date`, `run_metrics` ไม่บังคับ (payload แบบเดิมยังใช้ได้)

**ต้องเก็บไว้ใช้ต่อ:** `run_id` (ส่งให้ `GET /ai/optimize-inputs`) และ `assessment_id` ของแต่ละ lot (ใส่ใน `POST /tasks`)
""",
    responses={
        400: {"description": "DB ปฏิเสธการบันทึกด้วยเหตุผลอื่น"},
        409: {"description": "`run_id` นี้มีอยู่แล้ว หรือมี `lot_id` ซ้ำใน `run_id` เดียวกัน"},
        422: {"description": "ข้อมูลไม่ถูกต้อง เช่น `risk_score` เกิน 100, `risk_level` ไม่อยู่ใน enum, "
                             "`lot_id` / `recipe_id` ไม่มีอยู่จริง, `high_qty` < `low_qty` หรือ discount_pct ซ้ำในล็อตเดียว"},
    },
)
def create_risk_assessments(payload: RiskAssessmentBatchCreate):
    """บันทึกผล Risk Scanner + Forecast ของ run เดียวกัน (สำเร็จทั้งหมดหรือไม่สำเร็จเลย)"""
    try:
        res = supabase.rpc("save_risk_run", {"p_run": payload.model_dump(mode="json", exclude_none=True)}).execute()
    except APIError as e:
        if e.code == "23505":   # unique: run_id ซ้ำ / (run_id, lot_id) ซ้ำ / (assessment_id, discount_pct) ซ้ำ
            if "forecast_runs_pkey" in (e.message or ""):
                raise HTTPException(409, "run_id already exists")
            if "lot_shelf_forecasts_pkey" in (e.message or ""):
                raise HTTPException(422, f"Duplicate discount_pct within a lot: {e.details or e.message}")
            raise HTTPException(409, "Duplicate lot_id within this run_id")
        if e.code == "23503":   # foreign key → lot_id / recipe_id / product_id ไม่มีอยู่
            raise HTTPException(422, f"Unknown id: {e.details or e.message}")
        if e.code in ("23514", "22P02"):   # check constraint / ค่าแปลงชนิดไม่ได้
            raise HTTPException(422, f"Invalid value: {e.details or e.message}")
        raise HTTPException(400, f"Failed to save risk assessments: {e.message}")

    return res.data
