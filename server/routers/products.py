from fastapi import APIRouter

from db.supabase import supabase

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("")
def list_products():
    return supabase.table("products").select("*").execute().data
