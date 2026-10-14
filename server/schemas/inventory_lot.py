from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

from schemas.enums import LotAIStatus


class InventoryLotCreate(BaseModel):
    product_id: str
    received_date: date
    expiration_date: date
    initial_quantity: int
    current_quantity: int
    unit_cost: Optional[float] = None
    location_aisle: Optional[str] = None
    location_shelf: Optional[str] = None
    ai_status: Optional[str] = None
    current_selling_price: Optional[float] = None
    source_task_id: Optional[str] = None


class InventoryLotUpdate(BaseModel):
    product_id: Optional[str] = None
    received_date: Optional[date] = None
    expiration_date: Optional[date] = None
    initial_quantity: Optional[int] = None
    current_quantity: Optional[int] = None
    unit_cost: Optional[float] = None
    location_aisle: Optional[str] = None
    location_shelf: Optional[str] = None
    ai_status: Optional[str] = None
    current_selling_price: Optional[float] = None
    source_task_id: Optional[str] = None


class LotAIStatusUpdate(BaseModel):
    lot_ids: list[str] = Field(..., min_length=1, description="รหัส lot ที่ต้องการเปลี่ยนสถานะ อย่างน้อย 1 ตัว")
    ai_status: LotAIStatus = Field(..., description="IDLE = ยังไม่สแกน, PROCESSING = กำลังสแกน, CHECKED = สแกนเสร็จแล้ว")

    model_config = {
        "json_schema_extra": {
            "examples": [{"lot_ids": ["LOT-000001", "LOT-000003"], "ai_status": "PROCESSING"}]
        }
    }
