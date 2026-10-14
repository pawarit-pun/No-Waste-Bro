from fastapi import APIRouter, HTTPException

from db.supabase import supabase
from schemas.inventory_lot import InventoryLotCreate, InventoryLotUpdate

router = APIRouter(prefix="/inventory-lots", tags=["Inventory Lots"])


@router.post("", status_code=201)
def create_inventory_lot(lot_model: InventoryLotCreate):
    res = supabase.table("inventory_lots").insert(lot_model.model_dump(mode="json", exclude_none=True)).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to create inventory lot")
    return {"message": "create lot successful", "data": res.data[0]}


@router.patch("/{lot_id}")
def update_inventory_lot(lot_id: str, lot_model: InventoryLotUpdate):
    res = (supabase.table("inventory_lots")
             .update(lot_model.model_dump(mode="json", exclude_unset=True))
             .eq("lot_id", lot_id)
             .execute())
    if not res.data:
        raise HTTPException(status_code=404, detail="Inventory lot not found")
    return {"message": "update lot successful", "data": res.data[0]}
