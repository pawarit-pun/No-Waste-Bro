from fastapi import APIRouter, Query

from db.supabase import supabase
from schemas.enums import StaffRole
from schemas.responses import StaffRow

router = APIRouter(prefix="/staff", tags=["Staff"])


@router.get(
    "",
    response_model=list[StaffRow],
    summary="รายชื่อพนักงานตาม role",
    description="""
ใช้กับหน้าเลือกผู้ใช้ (ระบบยังไม่มี login)

- **Staff mobile app:** `GET /staff` (ค่าเริ่มต้น `role=STAFF`) → พนักงานหน้าร้าน
- **Web dashboard:** `GET /staff?role=MANAGER` → ผู้จัดการ

คืนเฉพาะพนักงานที่ `is_active = true` เรียงตาม `staff_id`
`responsible_categories` บอกว่าพนักงานดูแลสินค้าหมวดไหน (ใช้จับคู่ task กับคนรับผิดชอบ)
""",
)
def list_staff(
    role: StaffRole = Query(StaffRole.STAFF, description="STAFF = พนักงาน (ค่าเริ่มต้น), MANAGER = ผู้จัดการ"),
):
    return (supabase.table("staff")
              .select("staff_id, full_name, role, responsible_categories, image_url, is_active")
              .eq("role", role.value)
              .eq("is_active", True)
              .order("staff_id")
              .execute()).data
