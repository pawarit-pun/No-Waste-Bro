from uuid import uuid4

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

- ไม่ส่ง `run_id` = server สร้างให้ แล้วคืนกลับมาใน response
- บันทึกทั้งหมดหรือไม่บันทึกเลย ถ้ามีแถวไหนผิด จะไม่มีแถวไหนถูกบันทึก
- ส่งได้ทุก risk level แต่ `optimize-inputs` จะส่งต่อให้ Optimizer เฉพาะ MEDIUM / HIGH / CRITICAL

**ต้องเก็บไว้ใช้ต่อ:** `run_id` (ส่งให้ `GET /ai/optimize-inputs`) และ `assessment_id` ของแต่ละ lot (ใส่ใน `POST /tasks`)
""",
    responses={
        400: {"description": "DB ปฏิเสธการบันทึกด้วยเหตุผลอื่น"},
        409: {"description": "มี `lot_id` ซ้ำใน `run_id` เดียวกัน"},
        422: {"description": "ข้อมูลไม่ถูกต้อง เช่น `risk_score` เกิน 100, `risk_level` ไม่อยู่ใน enum หรือ `lot_id` ไม่มีอยู่จริง"},
    },
)
def create_risk_assessments(payload: RiskAssessmentBatchCreate):
    """บันทึกผล Risk Scanner + Forecast ของ run เดียวกัน (สำเร็จทั้งหมดหรือไม่สำเร็จเลย)"""
    run_id = str(payload.run_id or uuid4())
    rows = [
        {**item.model_dump(mode="json", exclude_none=True),
         "run_id": run_id, "model_version": payload.model_version}
        for item in payload.assessments
    ]
    try:
        res = supabase.table("lot_risk_assessments").insert(rows).execute()
    except APIError as e:
        if e.code == "23505":   # unique (run_id, lot_id)
            raise HTTPException(409, "Duplicate lot_id within this run_id")
        if e.code == "23503":   # foreign key → lot_id ไม่มีอยู่
            raise HTTPException(422, f"Unknown lot_id: {e.details or e.message}")
        raise HTTPException(400, f"Failed to save risk assessments: {e.message}")

    return {
        "run_id": run_id,
        "created": len(res.data),
        "assessments": [{"assessment_id": r["assessment_id"], "lot_id": r["lot_id"]} for r in res.data],
    }
