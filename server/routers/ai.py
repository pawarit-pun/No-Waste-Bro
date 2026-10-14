from datetime import timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query

from core.dates import today_bkk
from db.helpers import fetch_all
from db.supabase import supabase
from schemas.responses import OptimizeInputsResponse, ScanInputsResponse

router = APIRouter(prefix="/ai", tags=["AI"])


@router.get(
    "/scan-inputs",
    response_model=ScanInputsResponse,
    summary="ข้อมูลสำหรับ Risk Scanner + Forecast",
    description="""
**ขั้นที่ 2 ของ AI Pipeline** ดึงข้อมูลทั้งหมดที่ใช้ประเมินความเสี่ยงและพยากรณ์ยอดขาย

- `inventory_lots`: lot ทุกตัวในสต็อก (จำนวนคงเหลือ, วันหมดอายุ, ราคา, ตำแหน่ง)
- `sales_history`: ยอดขายรายวันทั้งหมด แยกแถวตามระดับส่วนลด (`markdown_pct`) ใช้ประมาณผลของการลดราคาได้
- `average_daily_sales`: ยอดขายเฉลี่ยต่อวัน 7 วัน / 30 วัน / 30 วันเฉพาะราคาปกติ

ค่าเฉลี่ยคำนวณจากวันขายล่าสุดใน `sales_history` (ดู `reference_date` ในแต่ละแถว) ไม่ใช่วันนี้
อ่านข้อมูลอย่างเดียว ไม่แก้ไขอะไร
""",
)
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


AT_RISK_LEVELS = ["MEDIUM", "HIGH", "CRITICAL"]


@router.get(
    "/optimize-inputs",
    response_model=OptimizeInputsResponse,
    summary="ข้อมูลสำหรับ Optimizer",
    description="""
**ขั้นที่ 4 ของ AI Pipeline** (เรียกหลัง `POST /risk-assessments`) รวมข้อมูลที่ Optimizer ใช้ตัดสินใจว่าแต่ละ lot ควร
ลดราคา / ส่งเข้าครัว / บริจาค / ทิ้ง ไว้ในคำขอเดียว

| ส่วน | ใช้ตอบคำถาม |
| --- | --- |
| `at_risk_lots` | ต้องจัดการ lot ไหนบ้าง (เฉพาะ risk MEDIUM / HIGH / CRITICAL ของ run นั้น พร้อมข้อมูล lot ใน `lot`) |
| `products` | ลดราคาได้ถึงเท่าไหร่ (`min_allowed_price`), ส่งครัว / บริจาคได้ไหม (`allow_*`), ขนาดบรรจุสำหรับแปลงหน่วย |
| `recipes` | lot นี้ทำเมนูอะไรได้ ใช้วัตถุดิบเท่าไหร่ต่อ batch ใช้เวลาเท่าไหร่ ครัวไหนทำ |
| `kitchen_capacity` | ครัวยังว่างกี่ชั่วโมงในแต่ละวัน |
| `donation_partners` | บริจาคให้ใครได้ รับสินค้าประเภทไหน ต้องเหลืออายุกี่วัน |

- ไม่ส่ง `run_id` = ใช้รอบสแกนล่าสุด ถ้ายังไม่เคยสแกนหรือ `run_id` ไม่มีอยู่จริง `at_risk_lots` จะเป็น `[]`
- เรียกแล้ว server จะสร้างแถวความจุครัวรายวันให้ถ้ายังไม่มี (ไม่แตะชั่วโมงที่จองไว้)
""",
)
def get_optimize_inputs(
    run_id: Optional[UUID] = Query(None, description="รอบสแกนที่ต้องการ ไม่ส่ง = รอบล่าสุด"),
    days_ahead: int = Query(1, ge=0, le=30, description="ดูความจุครัวตั้งแต่วันนี้ถึงกี่วันข้างหน้า (0–30)"),
):
    """ข้อมูล input สำหรับ Optimizer: lot ที่เสี่ยง + กฎสินค้า + สูตร + ครัว + partner บริจาค"""
    if run_id is None:
        latest = (supabase.table("lot_risk_assessments")
                    .select("run_id")
                    .order("assessed_at", desc=True)
                    .limit(1)
                    .execute())
        run_id = latest.data[0]["run_id"] if latest.data else None

    at_risk_lots = []
    if run_id is not None:
        at_risk_lots = (supabase.table("lot_risk_assessments")
                          .select("*, lot:inventory_lots(*)")
                          .eq("run_id", str(run_id))
                          .in_("risk_level", AT_RISK_LEVELS)
                          .order("risk_score", desc=True)
                          .execute()).data

    products = supabase.table("products").select(
        "product_id, name, category, unit_of_measure, net_content_value, net_content_unit, "
        "base_cost, regular_price, min_allowed_price, "
        "allow_markdown, allow_kitchen_repurposing, allow_donation"
    ).execute().data

    recipes = (supabase.table("recipes")
                 .select("*, ingredients:recipe_ingredients(*)")
                 .eq("is_active", True)
                 .execute()).data

    start = today_bkk()
    end = start + timedelta(days=days_ahead)
    supabase.rpc("ensure_kitchen_days", {"p_from": start.isoformat(), "p_to": end.isoformat()}).execute()
    kitchen_capacity = (supabase.table("kitchen_capacity_daily")
                          .select("department_id, capacity_date, available_hrs, booked_hrs, remaining_hrs, workload_status")
                          .gte("capacity_date", start.isoformat())
                          .lte("capacity_date", end.isoformat())
                          .order("capacity_date")
                          .execute()).data

    donation_partners = (supabase.table("donation_partners")
                           .select("*")
                           .eq("is_active", True)
                           .execute()).data

    return {
        "reference_date": start.isoformat(),
        "run_id": str(run_id) if run_id else None,
        "at_risk_lots": at_risk_lots,
        "products": products,
        "recipes": recipes,
        "kitchen_capacity": kitchen_capacity,
        "donation_partners": donation_partners,
    }
