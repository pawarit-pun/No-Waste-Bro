from datetime import timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query

from core.dates import today_bkk
from db.helpers import fetch_all
from db.supabase import supabase
from schemas.enums import LotAIStatus
from schemas.responses import OptimizeInputsResponse, ScanInputsResponse

router = APIRouter(prefix="/ai", tags=["AI"])

CONTEXT_DAYS_AHEAD = 7  # daily_context ใน scan-inputs: วันนี้ถึงวันนี้ + 7 (ยืดถึงวันหมดอายุล่าสุดถ้าเกิน)


@router.get(
    "/scan-inputs",
    response_model=ScanInputsResponse,
    summary="ข้อมูลสำหรับ Risk Scanner + Forecast",
    description="""
**ขั้นที่ 1 ของ AI Pipeline** ดึงข้อมูลที่ใช้ประเมินความเสี่ยงและพยากรณ์ยอดขาย **เฉพาะ lot ที่ยังไม่เคยถูกสแกน**

route นี้เป็น **input ตอนทำนาย (inference)** เท่านั้น ข้อมูลสำหรับเทรนโมเดลอยู่ในไฟล์ CSV
(`AI/data/` หรือ export ใหม่ด้วย `python -m scripts.export_training_data`) ซึ่งมีคอลัมน์ชุดเดียวกัน

| ส่วน | 1 แถว = | ใช้ทำอะไร |
| --- | --- | --- |
| `reference_date` | – | "วันนี้" ของระบบ (เวลาไทย หรือ `DEMO_DATE`) ใช้นับ `days_to_expiry` |
| `inventory_lots` | 1 lot | lot ที่ `ai_status = IDLE` (คงเหลือ วันหมดอายุ ราคา ตำแหน่ง) |
| `products` | 1 สินค้า | หมวด ราคาปกติ ราคาต่ำสุด `shelf_life_days` ของสินค้าใน lot ข้างบน |
| `product_daily` | สินค้า × วัน | ยอดขายย้อนหลัง `history_days` วัน **ถึงเมื่อวาน** (ยอดเปิด/รับเข้า/ขายราคาเต็ม/ราคาลด/ทิ้ง/คงเหลือ, `is_stockout`) ใช้คำนวณ feature อย่างยอดเฉลี่ย 7 วัน ส่ง `history_days=0` ถ้าโมเดลไม่ใช้ |
| `daily_context` | 1 วัน | ปัจจัยรายวัน (วันหยุด วันเงินเดือนออก ฝน อุณหภูมิ) **วันนี้ถึง 7 วันข้างหน้า** ถ้ามี lot หมดอายุช้ากว่านั้นจะยืดถึงวันหมดอายุล่าสุด (อากาศ = ค่าพยากรณ์) ปัจจัยของวันในอดีตดูจาก `AI/data/daily_context.csv` |

- **ไม่มี `product_daily` ของวันนี้** เพราะเป็นสรุปทั้งวัน (รู้ตอนปิดร้าน) และยอดขายวันนี้คือสิ่งที่โมเดลต้องทำนาย ของที่อยู่บนชั้นตอนนี้ดูจาก `inventory_lots`
- วันที่ `is_stockout = true` ยอดขายถูกตัด (censored) ต่ำกว่า demand จริง ควรจัดการก่อนเทรน
- `latent_demand` = demand จริงจาก simulation ใช้วัดผลโมเดลเท่านั้น **ห้ามใช้เป็น feature**
- สินค้าเดียวกันมีหลาย lot ได้ ให้แบ่ง demand แบบ FIFO (lot ที่หมดอายุก่อนได้ก่อน)

**หลังเรียก route นี้ ให้ล็อก `lot_id` ที่ได้เป็น `PROCESSING` ทันที** (`PATCH /inventory-lots/ai-status`)
lot แต่ละตัวถูกสแกนได้ครั้งเดียว ถ้าไม่มี lot ที่เป็น `IDLE` ทุกส่วนจะเป็น `[]`
อ่านข้อมูลอย่างเดียว ไม่แก้ไขอะไร
""",
)
def get_scan_inputs(
    history_days: int = Query(28, ge=0, le=60,
                              description="ยอดขายย้อนหลังกี่วัน (0–60) 0 = ไม่ส่ง product_daily"),
):
    """ข้อมูล input สำหรับ Risk Scanner & Forecaster เฉพาะ lot ที่ยังไม่เคยถูกสแกน (IDLE)"""
    today = today_bkk()
    history_from = today - timedelta(days=history_days)
    empty = {"reference_date": today.isoformat(), "inventory_lots": [], "products": [], "product_daily": [],
             "daily_context": []}
    lots = (supabase.table("inventory_lots")
              .select("lot_id, product_id, received_date, expiration_date, initial_quantity, "
                      "current_quantity, unit_cost, location_aisle, location_shelf, "
                      "current_selling_price, ai_status")
              .eq("ai_status", LotAIStatus.IDLE.value)
              .order("expiration_date")
              .execute()).data
    if not lots:
        return empty

    product_ids = sorted({lot["product_id"] for lot in lots})
    products = (supabase.table("products")
                  .select("product_id, name, category, unit_of_measure, regular_price, "
                          "min_allowed_price, shelf_life_days")
                  .in_("product_id", product_ids)
                  .order("product_id")
                  .execute()).data

    # ถึงเมื่อวานเท่านั้น: วันนี้ยังไม่ปิดร้าน และกันข้อมูลอนาคตรั่วเข้าโมเดลตอนย้อนวันด้วย DEMO_DATE
    product_daily = []
    if history_days > 0:
        product_daily = fetch_all("product_daily", in_filter=("product_id", product_ids),
                                  order_by=("product_id", "sale_date"),
                                  filters=[("gte", "sale_date", history_from.isoformat()),
                                           ("lt", "sale_date", today.isoformat())])

    # วันนี้ถึง +7 วัน หรือถึงวันหมดอายุล่าสุดของ lot ถ้าช้ากว่า
    ctx_to = max(max(lot["expiration_date"] for lot in lots),
                 (today + timedelta(days=CONTEXT_DAYS_AHEAD)).isoformat())
    daily_context = (supabase.table("daily_context")
                       .select("*")
                       .gte("context_date", today.isoformat())
                       .lte("context_date", ctx_to)
                       .order("context_date")
                       .execute()).data

    return {
        "reference_date": today.isoformat(),
        "inventory_lots": lots,
        "products": products,
        "product_daily": product_daily,
        "daily_context": daily_context,
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
| `ingredient_stock` | **วัตถุดิบของทุกสูตรเหลือเท่าไหร่** (เฉพาะ lot ที่ยังไม่หมดอายุ เรียงหมดอายุก่อน = ลำดับที่ระบบจะตัดจริงตอน complete) |

- **งานครัวที่ใช้วัตถุดิบเดียวกันหลายงาน:** Optimizer ต้องรวมความต้องการเองแล้วเทียบกับ `ingredient_stock` (วัตถุดิบต่อ batch = `required_quantity` ในหน่วย G/ML เทียบกับ `total_content`)
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
        "ingredient_stock": _ingredient_stock(recipes, products, start),
        "reference_date": start.isoformat(),
        "run_id": str(run_id) if run_id else None,
        "at_risk_lots": at_risk_lots,
        "products": products,
        "recipes": recipes,
        "kitchen_capacity": kitchen_capacity,
        "donation_partners": donation_partners,
    }


def _ingredient_stock(recipes: list[dict], products: list[dict], today) -> list[dict]:
    """สต็อกที่ใช้ได้ของสินค้าที่เป็นวัตถุดิบของสูตร active (lot ที่ยังมีของและยังไม่หมดอายุ)"""
    ingredient_ids = sorted({i["ingredient_product_id"] for r in recipes for i in r["ingredients"]})
    if not ingredient_ids:
        return []
    lots = (supabase.table("inventory_lots")
              .select("lot_id, product_id, current_quantity, expiration_date, location_aisle, location_shelf")
              .in_("product_id", ingredient_ids)
              .gt("current_quantity", 0)
              .gte("expiration_date", today.isoformat())
              .order("expiration_date").order("lot_id")
              .execute()).data
    by_product = {p["product_id"]: p for p in products}

    stock = []
    for product_id in ingredient_ids:
        p = by_product[product_id]
        product_lots = [l for l in lots if l["product_id"] == product_id]
        total_units = sum(l["current_quantity"] for l in product_lots)
        unit, size = p["net_content_unit"], p["net_content_value"]
        # แปลงเป็น G / ML ให้ตรงกับหน่วยใน recipe_ingredients
        base_unit = {"KG": "G", "L": "ML"}.get(unit, unit)
        multiplier = 1000 if unit in ("KG", "L") else 1
        stock.append({
            "product_id": product_id,
            "name": p["name"],
            "net_content_value": size,
            "net_content_unit": unit,
            "total_units": total_units,
            "total_content": round(total_units * size * multiplier, 2) if size is not None else None,
            "content_unit": base_unit,
            "lots": product_lots,
        })
    return stock
