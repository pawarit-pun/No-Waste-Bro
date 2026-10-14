from fastapi import APIRouter, HTTPException

from db.supabase import supabase
from schemas.inventory_lot import InventoryLotCreate, InventoryLotUpdate, LotAIStatusUpdate
from schemas.responses import LotAIStatusResponse

router = APIRouter(prefix="/inventory-lots", tags=["Inventory Lots"])


@router.post("", status_code=201, summary="สร้าง lot ใหม่")
def create_inventory_lot(lot_model: InventoryLotCreate):
    res = supabase.table("inventory_lots").insert(lot_model.model_dump(mode="json", exclude_none=True)).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to create inventory lot")
    return {"message": "create lot successful", "data": res.data[0]}


# ต้องอยู่ก่อน PATCH /{lot_id} ไม่งั้น FastAPI จะจับ "ai-status" เป็น lot_id
@router.patch(
    "/ai-status",
    response_model=LotAIStatusResponse,
    summary="เปลี่ยน ai_status ของหลาย lot พร้อมกัน",
    description="""
**ขั้นที่ 1 และ 8 ของ AI Pipeline**

- ก่อนสแกน: ตั้งเป็น `PROCESSING` เพื่อกันไม่ให้ lot ถูกสแกนซ้ำ
- สแกนและสร้าง task เสร็จ: ตั้งเป็น `CHECKED`
- `IDLE` = ยังไม่สแกน (ค่าเริ่มต้นของ lot ใหม่)

`lot_id` ที่ไม่มีอยู่จริงจะอยู่ใน `not_found` โดยไม่ทำให้คำขอล้มเหลว ยกเว้นไม่พบเลยสักตัว (404)
""",
    responses={404: {"description": "ไม่พบ `lot_id` ใดเลย"}},
)
def update_lots_ai_status(payload: LotAIStatusUpdate):
    """เปลี่ยน ai_status ของหลาย lot พร้อมกัน (IDLE → PROCESSING → CHECKED)"""
    res = (supabase.table("inventory_lots")
             .update({"ai_status": payload.ai_status.value})
             .in_("lot_id", payload.lot_ids)
             .execute())
    if not res.data:
        raise HTTPException(status_code=404, detail="None of the lot_ids were found")
    updated_ids = {row["lot_id"] for row in res.data}
    return {
        "message": "update ai_status successful",
        "updated": [{"lot_id": r["lot_id"], "ai_status": r["ai_status"]} for r in res.data],
        "not_found": [lot_id for lot_id in payload.lot_ids if lot_id not in updated_ids],
    }


@router.patch("/{lot_id}", summary="แก้ไขข้อมูล lot")
def update_inventory_lot(lot_id: str, lot_model: InventoryLotUpdate):
    res = (supabase.table("inventory_lots")
             .update(lot_model.model_dump(mode="json", exclude_unset=True))
             .eq("lot_id", lot_id)
             .execute())
    if not res.data:
        raise HTTPException(status_code=404, detail="Inventory lot not found")
    return {"message": "update lot successful", "data": res.data[0]}
