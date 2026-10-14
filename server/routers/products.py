from fastapi import APIRouter

from db.supabase import supabase

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("", summary="รายการสินค้าทั้งหมด")
def list_products():
    return supabase.table("products").select("*").execute().data
