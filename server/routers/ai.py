from fastapi import APIRouter

from db.helpers import fetch_all
from db.supabase import supabase

router = APIRouter(prefix="/ai", tags=["AI"])


@router.get("/scan-inputs")
def get_scan_inputs():
    """ข้อมูล input สำหรับ Risk Scanner & Forecaster"""
    lots = supabase.table("inventory_lots").select(
        "lot_id, product_id, received_date, expiration_date, initial_quantity, "
        "current_quantity, unit_cost, location_aisle, location_shelf, current_selling_price"
    ).execute()
    sales_history = fetch_all("sales_history")
    # TODO: reference_date ยึดวันขายล่าสุดใน sales_history ไม่ใช่ today_bkk()
    velocity = supabase.table("daily_sales_velocity").select(
        "product_id, avg_daily_sales_7d, avg_daily_sales_30d, avg_daily_sales_regular_30d, reference_date"
    ).execute()
    return {
        "inventory_lots": lots.data,
        "sales_history": sales_history,
        "average_daily_sales": velocity.data,
    }
