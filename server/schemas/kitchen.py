from datetime import date

from pydantic import BaseModel, Field


class KitchenBookingRequest(BaseModel):
    department_id: str
    booking_date: date
    hours: float = Field(..., gt=0, description="จำนวนชั่วโมงต้องมากกว่า 0")
