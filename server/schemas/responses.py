"""Model ของ response ใช้แสดงรูปร่างข้อมูลใน Swagger
ทุก model ตั้ง extra="allow" เพื่อไม่ตัด field ที่ไม่ได้ประกาศไว้ทิ้ง (response เหมือนเดิมทุก field)"""
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Row(BaseModel):
    model_config = ConfigDict(extra="allow")


# ---------- แถวข้อมูลจากตาราง ----------

class InventoryLotRow(_Row):
    lot_id: str
    product_id: str
    received_date: date
    expiration_date: date = Field(..., description="วันหมดอายุ")
    initial_quantity: int
    current_quantity: int = Field(..., description="จำนวนคงเหลือปัจจุบัน")
    current_selling_price: float = Field(..., description="ราคาขายปัจจุบัน (บาท/หน่วย)")
    unit_cost: Optional[float] = Field(None, description="ต้นทุนต่อหน่วย")
    location_aisle: Optional[str] = None
    location_shelf: Optional[str] = None
    ai_status: Optional[str] = Field(None, description="IDLE / PROCESSING / CHECKED")
    last_price_changed_at: Optional[datetime] = None
    source_task_id: Optional[UUID] = Field(None, description="task ที่ผลิต lot นี้ (เฉพาะ lot ที่มาจากครัว)")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SalesHistoryRow(_Row):
    product_id: str
    sale_date: date
    markdown_pct: float = Field(..., description="% ส่วนลดของวันนั้น (0 = ราคาปกติ)")
    quantity_sold: int
    avg_selling_price: float


class SalesVelocityRow(_Row):
    product_id: str
    avg_daily_sales_7d: Optional[float] = Field(None, description="ยอดขายเฉลี่ยต่อวัน 7 วันล่าสุด")
    avg_daily_sales_30d: Optional[float] = Field(None, description="ยอดขายเฉลี่ยต่อวัน 30 วันล่าสุด")
    avg_daily_sales_regular_30d: Optional[float] = Field(None, description="ยอดขายเฉลี่ยต่อวัน 30 วัน เฉพาะวันขายราคาปกติ")
    reference_date: Optional[date] = Field(None, description="วันขายล่าสุดใน sales_history ที่ใช้เป็นจุดอ้างอิง")


class AtRiskLot(_Row):
    assessment_id: UUID
    run_id: UUID
    lot_id: str
    assessed_at: datetime
    days_to_expiry: int
    quantity_at_assessment: int
    forecast_daily_demand: float
    predicted_units_sold_before_expiry: float
    predicted_leftover_units: float
    sell_through_probability: Optional[float] = None
    risk_score: float
    risk_level: str = Field(..., description="MEDIUM / HIGH / CRITICAL")
    model_version: Optional[str] = None
    lot: Optional[InventoryLotRow] = Field(None, description="ข้อมูล lot ปัจจุบันทั้งแถว")


class ProductRule(_Row):
    product_id: str
    name: str
    category: str = Field(..., description="DAIRY / BAKERY / MEAT / SEAFOOD / PRODUCE / READY_TO_EAT")
    unit_of_measure: str = Field(..., description="หน่วยนับของ lot เช่น PIECE / PACK")
    net_content_value: Optional[float] = Field(None, description="ขนาดบรรจุต่อหน่วย ใช้แปลงหน่วยกับสูตรอาหาร")
    net_content_unit: Optional[str] = Field(None, description="G / KG / ML / L")
    base_cost: float
    regular_price: float
    min_allowed_price: Optional[float] = Field(None, description="ราคาต่ำสุดที่ลดได้")
    allow_markdown: Optional[bool] = Field(None, description="ลดราคาได้ไหม")
    allow_kitchen_repurposing: Optional[bool] = Field(None, description="ส่งเข้าครัวได้ไหม")
    allow_donation: Optional[bool] = Field(None, description="บริจาคได้ไหม")


class RecipeIngredientRow(_Row):
    recipe_id: str
    ingredient_product_id: str = Field(..., description="สินค้าที่ใช้เป็นวัตถุดิบ")
    required_quantity: float = Field(..., description="ปริมาณที่ใช้ต่อ 1 batch (หน่วยตาม unit_of_measure)")
    unit_of_measure: str = Field(..., description="G / ML ฯลฯ")
    is_primary_ingredient: Optional[bool] = None


class RecipeWithIngredients(_Row):
    recipe_id: str
    name: str
    target_category: str
    output_product_id: str = Field(..., description="สินค้าที่ได้จากสูตร")
    output_quantity: float = Field(..., description="จำนวนที่ได้ต่อ 1 batch")
    estimated_prep_time_mins: Optional[int] = Field(None, description="เวลาทำต่อ 1 batch (นาที) ใช้คำนวณชั่วโมงครัว")
    shelf_life_days: int = Field(..., description="อายุของสินค้าที่ผลิต (0 = ต้องขายให้หมดในวันนั้น)")
    department_id: Optional[str] = Field(None, description="ครัวที่ทำสูตรนี้")
    utility_cost: float = Field(..., description="ค่าน้ำไฟแก๊สต่อ 1 batch (บาท)")
    is_active: Optional[bool] = None
    ingredients: list[RecipeIngredientRow] = Field(default_factory=list, description="วัตถุดิบของสูตร")


class KitchenCapacityDay(_Row):
    department_id: str
    capacity_date: date
    available_hrs: float
    booked_hrs: float
    remaining_hrs: Optional[float] = Field(None, description="ชั่วโมงที่ยังว่าง")
    workload_status: Optional[str] = Field(None, description="AVAILABLE / BUSY / FULL")


class DonationPartnerRow(_Row):
    partner_id: str
    name: str
    partner_type: str = Field(..., description="FOOD_BANK / CHARITY / COMMUNITY / TEMPLE / ANIMAL_FEED")
    accepted_categories: list[str] = Field(..., description="ประเภทสินค้าที่รับ")
    pickup_days: list[int] = Field(..., description="วันที่มารับ 1 = จันทร์ … 7 = อาทิตย์")
    pickup_time_start: Optional[str] = None
    pickup_time_end: Optional[str] = None
    min_days_before_expiry: int = Field(..., description="สินค้าต้องเหลืออายุอย่างน้อยกี่วัน")
    max_capacity_kg_per_pickup: Optional[float] = None
    requires_cold_chain: bool = Field(..., description="ต้องขนส่งแบบแช่เย็นไหม")
    is_active: bool


class TaskRow(_Row):
    task_id: UUID
    decision_id: Optional[UUID] = Field(None, description="decision ที่เป็นที่มาของ task")
    lot_id: Optional[str] = None
    product_id: Optional[str] = None
    assessment_id: Optional[UUID] = None
    action_type: str
    action_quantity: int
    task_status: str = Field(..., description="PENDING / IN_PROGRESS / COMPLETED / REJECTED (สร้างใหม่ = PENDING)")
    priority: int
    original_price: float
    new_recommended_price: Optional[float] = None
    discount_pct: Optional[float] = None
    expected_profit_impact: Optional[float] = None
    target_recipe_id: Optional[str] = None
    target_partner_id: Optional[str] = None
    batch_count: Optional[int] = None
    due_by: Optional[datetime] = None
    ai_reasoning: Optional[str] = None
    staff_instructions: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------- Response ของแต่ละ route ----------

class ScanInputsResponse(BaseModel):
    inventory_lots: list[InventoryLotRow] = Field(..., description="lot ทั้งหมดในสต็อก")
    sales_history: list[SalesHistoryRow] = Field(..., description="ยอดขายรายวันทั้งหมด (แยกตามระดับส่วนลด)")
    average_daily_sales: list[SalesVelocityRow] = Field(..., description="ยอดขายเฉลี่ยต่อวันของแต่ละสินค้า")


class OptimizeInputsResponse(BaseModel):
    reference_date: date = Field(..., description="วันที่ระบบถือว่าเป็นวันนี้")
    run_id: Optional[UUID] = Field(None, description="รอบสแกนที่ใช้ null = ยังไม่เคยสแกน")
    at_risk_lots: list[AtRiskLot] = Field(..., description="lot ที่ risk MEDIUM ขึ้นไป เรียงจาก risk_score มากไปน้อย")
    products: list[ProductRule] = Field(..., description="กฎของสินค้าทุกตัว")
    recipes: list[RecipeWithIngredients] = Field(..., description="สูตรที่ active พร้อมวัตถุดิบ")
    kitchen_capacity: list[KitchenCapacityDay] = Field(..., description="ความจุครัวตั้งแต่วันนี้ถึง +days_ahead")
    donation_partners: list[DonationPartnerRow] = Field(..., description="partner ที่ active")


class AssessmentRef(BaseModel):
    assessment_id: UUID
    lot_id: str


class RiskAssessmentCreateResponse(BaseModel):
    run_id: UUID = Field(..., description="รหัสรอบสแกน ส่งต่อให้ `GET /ai/optimize-inputs`")
    created: int = Field(..., description="จำนวนแถวที่บันทึก")
    assessments: list[AssessmentRef] = Field(..., description="assessment_id ของแต่ละ lot ใช้ผูกกับ task")


class KitchenBooking(BaseModel):
    department_id: str
    date: date
    hours: float = Field(..., description="ชั่วโมงที่จอง (รวมทุก task ของครัวเดียวกันในวันเดียวกัน)")


class TaskCreateResponse(BaseModel):
    created: int = Field(..., description="จำนวน task ที่สร้าง")
    tasks: list[TaskRow] = Field(..., description="task ที่สร้าง (แถวเต็มจาก DB)")
    kitchen_bookings: list[KitchenBooking] = Field(..., description="ชั่วโมงครัวที่จองไป ว่าง = ไม่มี task ครัว")


class LotStatus(BaseModel):
    lot_id: str
    ai_status: str


class LotAIStatusResponse(BaseModel):
    message: str
    updated: list[LotStatus] = Field(..., description="lot ที่อัปเดตสำเร็จ")
    not_found: list[str] = Field(..., description="lot_id ที่ไม่มีอยู่จริง")


# ---------- Optimization Decisions ----------

class DecisionRef(BaseModel):
    decision_id: UUID
    run_id: UUID
    assessment_id: UUID
    lot_id: str
    action_type: str


class DecisionCreateResponse(BaseModel):
    created: int = Field(..., description="จำนวน decision ที่บันทึก")
    decisions: list[DecisionRef] = Field(..., description="decision_id ของแต่ละรายการ")


class DecisionAssessment(_Row):
    assessment_id: UUID
    days_to_expiry: int
    quantity_at_assessment: int
    predicted_leftover_units: float
    risk_score: float
    risk_level: str


class DecisionLot(_Row):
    lot_id: str
    product_id: str
    current_quantity: int
    current_selling_price: float
    expiration_date: date
    location_aisle: Optional[str] = Field(None, description="ทางเดินที่วางสินค้า")
    location_shelf: Optional[str] = Field(None, description="ชั้นที่วางสินค้า")


class DecisionProduct(_Row):
    product_id: str
    name: str
    category: str
    unit_of_measure: str
    regular_price: float
    min_allowed_price: Optional[float] = None


class DecisionRecipe(_Row):
    recipe_id: str
    name: str
    department_id: Optional[str] = None
    output_product_id: str
    output_quantity: float
    estimated_prep_time_mins: Optional[int] = None
    shelf_life_days: int


class DecisionPartner(_Row):
    partner_id: str
    name: str
    partner_type: str
    pickup_days: list[int]
    pickup_time_start: Optional[str] = None
    pickup_time_end: Optional[str] = None
    requires_cold_chain: bool
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None


class DecisionWithContext(_Row):
    decision_id: UUID
    run_id: UUID
    assessment_id: UUID
    lot_id: str
    action_type: str
    action_quantity: int
    discount_pct: Optional[float] = None
    new_recommended_price: Optional[float] = None
    target_recipe_id: Optional[str] = None
    batch_count: Optional[int] = None
    target_partner_id: Optional[str] = None
    due_by: Optional[datetime] = None
    expected_profit_impact: Optional[float] = None
    decision_score: Optional[float] = None
    alternatives: Optional[list[dict]] = None
    optimizer_version: Optional[str] = None
    created_at: datetime
    status: str = Field(..., description="PENDING = ยังไม่มี task, TASK_CREATED = สร้าง task แล้ว")
    task_id: Optional[UUID] = Field(None, description="task ที่สร้างจาก decision นี้ (ถ้ามี)")
    assessment: Optional[DecisionAssessment] = Field(None, description="ผลประเมินความเสี่ยง")
    lot: Optional[DecisionLot] = Field(None, description="สภาพ lot ปัจจุบัน + ตำแหน่งชั้นวาง")
    product: Optional[DecisionProduct] = Field(None, description="ชื่อและประเภทสินค้า")
    recipe: Optional[DecisionRecipe] = Field(None, description="สูตรที่จะทำ (เฉพาะ KITCHEN_REPURPOSE)")
    partner: Optional[DecisionPartner] = Field(None, description="partner ที่รับบริจาค (เฉพาะ DONATE)")


class DecisionListResponse(BaseModel):
    run_id: Optional[UUID] = Field(None, description="รอบสแกนที่ใช้ null = ยังไม่มี decision")
    decisions: list[DecisionWithContext]
