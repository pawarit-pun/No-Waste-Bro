from datetime import date

from db.supabase import supabase


def department_exists(department_id: str) -> bool:
    res = (supabase.table("kitchen_capacity")
             .select("department_id")
             .eq("department_id", department_id)
             .execute())
    return bool(res.data)


def book_hours(department_id: str, on: date, hours: float) -> bool:
    """จองชั่วโมงครัว คืน False ถ้าครัวเต็ม (ให้ Optimizer เลือกทางอื่น)"""
    res = supabase.rpc("book_kitchen_hours", {
        "p_department_id": department_id,
        "p_date": on.isoformat(),
        "p_hours": hours,
    }).execute()
    return bool(res.data)  # RPC คืนแถวที่อัปเดต ถ้าเต็มจะได้ list ว่าง
