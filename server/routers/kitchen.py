from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query

from core.dates import today_bkk
from db.supabase import supabase
from schemas.kitchen import KitchenBookingRequest
from services.kitchen import book_hours, department_exists

router = APIRouter(tags=["Kitchen"])


@router.get("/kitchen-capacity")
def list_kitchen_capacity(days_ahead: int = Query(1, ge=0, le=30)) -> list[dict]:
    """ความจุครัวตั้งแต่วันนี้ถึง +days_ahead (สร้างแถวรายวันให้ก่อนถ้ายังไม่มี)"""
    start = today_bkk()
    end = start + timedelta(days=days_ahead)
    supabase.rpc("ensure_kitchen_days", {"p_from": start.isoformat(), "p_to": end.isoformat()}).execute()
    res = (supabase.table("kitchen_capacity_daily")
             .select("department_id, capacity_date, available_hrs, booked_hrs, remaining_hrs, workload_status")
             .gte("capacity_date", start.isoformat())
             .lte("capacity_date", end.isoformat())
             .order("capacity_date")
             .execute())
    return res.data


@router.post("/kitchen-bookings", status_code=201)
def create_kitchen_booking(payload: KitchenBookingRequest):
    if not department_exists(payload.department_id):
        raise HTTPException(status_code=404, detail="Booking unsuccessful: department not found")

    if not book_hours(payload.department_id, payload.booking_date, payload.hours):
        raise HTTPException(status_code=400, detail="Booking unsuccessful: requested hours exceed available capacity")

    return {
        "status": "success",
        "message": "Booking successful",
        "data": {
            "department_id": payload.department_id,
            "date": payload.booking_date,
            "booked_hours": payload.hours,
        },
    }
