from datetime import date
from typing import Optional

from pydantic import BaseModel


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
