"""ตารางรอบรับของของ partner (GET /pickup-schedule)"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class PickupPartner(BaseModel):
    partner_id: str
    name: str
    partner_type: str = Field(..., description="DONATION / ANIMAL_FEED / COMPOSTING / ANAEROBIC_DIGESTION / LANDFILL")
    accepted_categories: list[str] = []
    pickup_days: list[int] = Field([], description="1 = จันทร์ .. 7 = อาทิตย์")
    pickup_time_start: Optional[str] = None
    pickup_time_end: Optional[str] = None
    max_capacity_kg_per_pickup: Optional[float] = None
    min_kg_per_pickup: Optional[float] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    min_days_before_expiry: Optional[int] = None


class PickupItem(BaseModel):
    source: str = Field(..., description="TASK = อนุมัติแล้ว, PLAN = รออนุมัติใน Review queue")
    task_id: Optional[str] = None
    review_id: Optional[str] = None
    lot_id: str
    product_name: Optional[str] = None
    unit_of_measure: Optional[str] = None
    action_type: str
    quantity: int
    kg: float = Field(..., description="จำนวน × น้ำหนักต่อหน่วยจาก net_content")
    status: str = Field(..., description="สถานะ task หรือ WAITING_APPROVAL")
    staff_name: Optional[str] = None
    due_by: datetime
    location: Optional[str] = None


class PickupCosts(BaseModel):
    trip_cost_thb: float
    handling_thb: float
    buyback_thb: float
    net_cost_thb: float = Field(..., description="ค่าเที่ยว + handling − รับซื้อ (ประมาณ สูตรเดียวกับ Optimizer)")


class PickupSlot(BaseModel):
    slot_id: str
    partner_id: str
    date: date
    window_start: datetime
    window_end: datetime
    state: str = Field(..., description="UPCOMING / OPEN (อยู่ในช่วงรับ) / PAST เทียบกับเวลาของระบบ")
    on_schedule: bool = Field(..., description="false = มีของนัดวันที่ partner ไม่ได้มารับตามตาราง")
    items: list[PickupItem]
    kg_confirmed: float
    kg_waiting: float
    capacity_kg: Optional[float] = None
    min_kg: float
    tasks_done: int
    tasks_total: int
    alerts: list[str] = Field(..., description="OVER_CAPACITY / BELOW_MIN / NOT_READY / WAITING_APPROVAL")
    costs: Optional[PickupCosts] = Field(None, description="null = รอบนี้ไม่มีของ")


class PickupScheduleResponse(BaseModel):
    reference_date: date
    now: datetime
    days_ahead: int
    partners: list[PickupPartner]
    slots: list[PickupSlot] = Field(..., description="เรียงตามวัน แล้วเวลาเริ่มรับ")
