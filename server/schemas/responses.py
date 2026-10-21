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


class ScanProductRow(_Row):
    product_id: str
    name: str
    category: str = Field(..., description="DAIRY / BAKERY / MEAT / SEAFOOD / PRODUCE / READY_TO_EAT")
    unit_of_measure: str = Field(..., description="หน่วยนับของ lot เช่น PIECE / PACK")
    regular_price: float = Field(..., description="ราคาปกติ (บาท/หน่วย)")
    min_allowed_price: Optional[float] = Field(None, description="ราคาต่ำสุดที่ลดได้")
    shelf_life_days: int = Field(..., description="อายุสินค้านับจากวันรับเข้า/ผลิต (วัน) 0 = ต้องขายให้หมดในวันนั้น")


class ProductDailyRow(_Row):
    product_id: str
    sale_date: date
    opening_qty: int = Field(..., description="ของบนชั้นตอนเปิดร้าน (08:00)")
    received_qty: int = Field(..., description="ของรับเข้าวันนั้น (supplier หรือครัวผลิต)")
    sold_qty: int = Field(..., description="ยอดขายจริงทั้งวัน = sold_full_price_qty + markdown_sold_qty")
    sold_full_price_qty: int = Field(..., description="ขายได้ในราคาปกติ")
    markdown_sold_qty: int = Field(..., description="ขายได้ในราคาลด")
    waste_qty: int = Field(..., description="ทิ้งเพราะหมดอายุ/เสีย")
    closing_qty: int = Field(..., description="คงเหลือตอนปิดร้าน (22:00) = opening + received - sold - waste")
    is_stockout: bool = Field(..., description="ของหมดชั้นก่อนปิดร้าน: ยอดขายวันนั้นต่ำกว่า demand จริง (censored)")
    stockout_hour: Optional[int] = Field(None, description="ชั่วโมงที่ของหมด (8-22) null = ไม่หมด")
    markdown_pct: float = Field(..., description="ส่วนลดสูงสุดของวัน (0 = ไม่ลด)")
    regular_price: float
    avg_selling_price: Optional[float] = Field(None, description="ราคาขายเฉลี่ยถ่วงน้ำหนักของวัน (null ถ้าขายไม่ได้เลย)")
    latent_demand: int = Field(..., description="demand จริงก่อนถูกจำกัดด้วยสต็อก ใช้วัดผลโมเดลเท่านั้น ห้ามใช้เป็น feature")


class DailyContextRow(_Row):
    context_date: date
    dow: int = Field(..., description="ISO day of week 1 = จันทร์ … 7 = อาทิตย์")
    is_weekend: bool
    is_public_holiday: bool = Field(..., description="วันหยุดราชการ/วันหยุดพิเศษที่มีผลกับ กทม.")
    holiday_name: Optional[str] = None
    is_long_weekend_day: bool = Field(..., description="อยู่ในช่วงหยุดต่อเนื่อง >= 3 วัน")
    is_pension_day: bool = Field(..., description="วันจ่ายบำนาญ (ปฏิทินกรมบัญชีกลาง)")
    is_private_payday: bool = Field(..., description="วันเงินเดือนเอกชน (สมมติ = วันทำการสุดท้ายของเดือน)")
    days_since_any_payday: int = Field(..., description="จำนวนวันนับจากวันเงินเดือนออกล่าสุด (ข้าราชการ/บำนาญ/เอกชน)")
    rain_mm: float = Field(..., description="ฝนรวมทั้งวัน (มม.) วันที่ผ่านมา = ค่าจริง, วันนี้เป็นต้นไป = ค่าพยากรณ์")
    rain_mm_16_20: float = Field(..., description="ฝนช่วง 16:00-20:00 ช่วงพีคคนซื้อของ (มม.)")
    temp_max_c: float
    temp_min_c: float


class ShelfForecastRow(_Row):
    discount_pct: float = Field(..., description="ส่วนลด (%) 0 = ราคาปัจจุบัน")
    price: float = Field(..., description="ราคาหลังลด (บาท/หน่วย)")
    expected_qty: float = Field(..., description="ล็อตนี้คาดว่าขายได้ก่อนหมดอายุ ถ้าลดตั้งแต่เปิดร้านวันนี้จนหมดอายุ")
    low_qty: float = Field(..., description="ช่วงล่าง (10%)")
    high_qty: float = Field(..., description="ช่วงบน (90%)")
    applies_from: date
    applies_until: date
    lost_sales_other_lots: float = Field(..., description="ล็อตอื่นของสินค้าเดียวกันขายได้น้อยลงเท่าไร")


class RecipeDemandRow(_Row):
    recipe_id: str
    output_product_id: str
    window_from: date
    window_to: date = Field(..., description="ช่วงอายุเมนู")
    gross_demand: float = Field(..., description="ความต้องการเมนูทั้งช่วง")
    current_stock: int = Field(..., description="ของเมนูที่มีบนชั้นแล้ว")
    menu_qty: float = Field(..., description="ควรผลิตเพิ่ม")
    low_qty: float
    high_qty: float
    expected_revenue: float = Field(..., description="รายได้ที่คาด (บาท)")


class AtRiskLot(_Row):
    assessment_id: UUID
    run_id: UUID
    lot_id: str
    assessed_at: datetime
    days_to_expiry: int
    sellable_hours: Optional[int] = Field(None, description="ชั่วโมงร้านเปิดที่เหลือจนสิ้นวันหมดอายุ")
    quantity_at_assessment: int
    forecast_daily_demand: float
    predicted_units_sold_before_expiry: float
    predicted_leftover_units: float
    sell_through_probability: Optional[float] = None
    risk_score: float
    risk_level: str = Field(..., description="HIGH / CRITICAL")
    model_version: Optional[str] = None
    lot: Optional[InventoryLotRow] = Field(None, description="ข้อมูล lot ปัจจุบันทั้งแถว")
    shelf: list[ShelfForecastRow] = Field(default_factory=list, description="ลด x% แล้วขายได้เท่าไร เรียงตามส่วนลด ([] = หมดอายุแล้ว หรือห้ามลดราคา)")


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
    partner_type: str = Field(..., description="FOOD_BANK / CHARITY / COMMUNITY / TEMPLE / DONATION / "
                                                "ANIMAL_FEED / COMPOSTING / ANAEROBIC_DIGESTION / LANDFILL")
    accepted_categories: list[str] = Field(..., description="ประเภทสินค้าที่รับ")
    pickup_days: list[int] = Field(..., description="วันที่มารับ 1 = จันทร์ … 7 = อาทิตย์")
    pickup_time_start: Optional[str] = Field(None, description="เวลาเริ่มรับของ")
    pickup_time_end: Optional[str] = Field(None, description="เวลาสิ้นสุดรับของ")
    min_days_before_expiry: Optional[int] = Field(None, description="สินค้าต้องเหลืออายุอย่างน้อยกี่วัน (null = ไม่มีเงื่อนไข)")
    min_kg_per_pickup: Optional[float] = Field(None, description="น้ำหนักขั้นต่ำต่อรอบที่มารับ (kg)")
    max_capacity_kg_per_pickup: Optional[float] = Field(None, description="น้ำหนักสูงสุดต่อรอบที่มารับ (kg)")
    fixed_cost_per_trip: Optional[float] = Field(None, description="ค่าใช้จ่ายคงที่ต่อเที่ยว (บาท)")
    travel_cost_per_trip: Optional[float] = Field(None, description="ค่าเดินทางต่อเที่ยว (บาท)")
    handling_fee_per_kg: Optional[float] = Field(None, description="ค่าจัดการต่อ kg (บาท)")
    buyback_price_per_kg: Optional[float] = Field(None, description="ราคาที่ partner รับซื้อต่อ kg (บาท) 0 = ไม่รับซื้อ")
    is_active: bool


class TaskRow(_Row):
    task_id: UUID
    decision_id: Optional[UUID] = Field(None, description="decision ที่เป็นที่มาของ task")
    assigned_staff_id: Optional[str] = Field(None, description="staff ที่ได้รับมอบหมาย (ระบบเลือกตามหมวดสินค้า) null = ไม่มีใครดูแลหมวดนี้")
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
    instruction_steps: Optional[list[dict]] = Field(None, description="ขั้นตอนทำงาน [{title, detail}] (null = ใช้ staff_instructions)")
    created_at: Optional[datetime] = None


# ---------- Response ของแต่ละ route ----------

class ScanInputsResponse(BaseModel):
    reference_date: date = Field(..., description="วันที่ระบบถือว่าเป็นวันนี้ (เวลาไทย หรือ DEMO_DATE) ใช้คำนวณ days_to_expiry")
    inventory_lots: list[InventoryLotRow] = Field(..., description="lot ที่ ai_status = IDLE (ยังไม่เคยถูกสแกน) เรียงตามวันหมดอายุ")
    products: list[ScanProductRow] = Field(..., description="ข้อมูลสินค้าของ lot ข้างบน (หมวด ราคา อายุสินค้า)")
    product_daily: list[ProductDailyRow] = Field(..., description="ยอดขาย/สต็อก/ของทิ้งรายวันของสินค้าของ lot ข้างบน ย้อนหลัง history_days วันถึงเมื่อวาน ([] ถ้า history_days = 0)")
    daily_context: list[DailyContextRow] = Field(..., description="ปัจจัยรายวัน (วันหยุด วันเงินเดือน อากาศ) วันนี้ถึง 7 วันข้างหน้า หรือถึงวันหมดอายุล่าสุดของ lot ถ้าช้ากว่า")


class IngredientLot(_Row):
    lot_id: str
    current_quantity: int
    expiration_date: date
    location_aisle: Optional[str] = None
    location_shelf: Optional[str] = None


class IngredientStock(BaseModel):
    product_id: str
    name: str
    net_content_value: Optional[float] = Field(None, description="ขนาดบรรจุต่อหน่วย")
    net_content_unit: Optional[str] = Field(None, description="G / KG / ML / L")
    total_units: int = Field(..., description="จำนวนหน่วยที่ใช้ได้รวมทุก lot")
    total_content: Optional[float] = Field(None, description="ปริมาณรวมในหน่วย content_unit (เทียบกับ required_quantity ของสูตรได้ตรงๆ)")
    content_unit: Optional[str] = Field(None, description="G หรือ ML")
    lots: list[IngredientLot] = Field(..., description="lot ที่ใช้ได้ เรียงจากหมดอายุก่อน (ลำดับที่ระบบตัดจริง)")


class OptimizeInputsResponse(BaseModel):
    reference_date: date = Field(..., description="วันที่ระบบถือว่าเป็นวันนี้")
    run_id: Optional[UUID] = Field(None, description="รอบสแกนที่ใช้ null = ยังไม่เคยสแกน")
    at_risk_lots: list[AtRiskLot] = Field(..., description="lot ที่ risk HIGH / CRITICAL เรียงจาก risk_score มากไปน้อย")
    recipe_demand: list[RecipeDemandRow] = Field(default_factory=list, description="ความต้องการเมนูครัวต่อสูตรของรอบสแกน เรียงตามรายได้ที่คาด")
    products: list[ProductRule] = Field(..., description="กฎของสินค้าทุกตัว")
    recipes: list[RecipeWithIngredients] = Field(..., description="สูตรที่ active พร้อมวัตถุดิบ")
    kitchen_capacity: list[KitchenCapacityDay] = Field(..., description="ความจุครัวตั้งแต่วันนี้ถึง +days_ahead")
    donation_partners: list[DonationPartnerRow] = Field(..., description="partner ที่ active")
    ingredient_stock: list["IngredientStock"] = Field(..., description="สต็อกที่ใช้ได้ของวัตถุดิบทุกสูตร (lot ยังไม่หมดอายุ เรียงหมดอายุก่อน)")


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
    department_name: Optional[str] = Field(None, description="ชื่อครัว (มีเฉพาะใน GET /tasks/{task_id})")
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
    partner: Optional[DecisionPartner] = Field(None, description="partner ที่มารับของ (งานที่มี target_partner_id)")


class DecisionListResponse(BaseModel):
    run_id: Optional[UUID] = Field(None, description="รอบสแกนที่ใช้ null = ยังไม่มี decision")
    decisions: list[DecisionWithContext]


# ---------- Staff ----------

class StaffRow(_Row):
    staff_id: str = Field(..., description="รหัสพนักงาน เช่น STF-002")
    full_name: str
    role: str = Field(..., description="MANAGER = เข้า web dashboard, STAFF = เข้า mobile app")
    responsible_categories: list[str] = Field(..., description="หมวดสินค้าที่รับผิดชอบ (STAFF มี 1–2 หมวด, MANAGER ว่าง)")
    image_url: Optional[str] = Field(None, description="URL รูปโปรไฟล์ (null = ไม่มีรูป)")
    is_active: bool


# ---------- Task queue ----------

class TaskProduct(_Row):
    product_id: str
    name: str
    category: str
    unit_of_measure: str
    image_url: Optional[str] = None


class TaskLot(_Row):
    lot_id: str
    current_quantity: int
    expiration_date: date
    location_aisle: Optional[str] = Field(None, description="ทางเดินที่วางสินค้า")
    location_shelf: Optional[str] = Field(None, description="ชั้นที่วางสินค้า")


class StaffRef(_Row):
    staff_id: str
    full_name: str
    image_url: Optional[str] = None


class TaskRecipeRef(BaseModel):
    model_config = ConfigDict(extra="allow")
    recipe_id: str
    name: str


class TaskListItem(TaskRow):
    product: Optional[TaskProduct] = Field(None, description="สินค้าของ task")
    lot: Optional[TaskLot] = Field(None, description="lot + ตำแหน่งชั้นวาง")
    assigned_staff: Optional[StaffRef] = Field(None, description="staff ที่ได้รับมอบหมาย")
    recipe: Optional[TaskRecipeRef] = Field(None, description="ชื่อสูตรที่จะทำ (เฉพาะ KITCHEN_REPURPOSE)")


class TaskDetail(TaskListItem):
    assessment: Optional[DecisionAssessment] = Field(None, description="ผลประเมินความเสี่ยงที่เป็นที่มาของ task")
    recipe: Optional[DecisionRecipe] = Field(None, description="สูตรที่จะทำ (เฉพาะ KITCHEN_REPURPOSE)")
    partner: Optional[DecisionPartner] = Field(None, description="partner ที่มารับของ (งานที่มี target_partner_id)")


# ---------- Task actions ----------

class LotChange(BaseModel):
    lot_id: str
    product_id: str
    reason: str = Field(..., description="TASK_LOT = lot ของ task, INGREDIENT = วัตถุดิบอื่นของสูตร")
    quantity_before: int
    quantity_after: int


class LotCreated(BaseModel):
    lot_id: str
    product_id: str
    reason: str = Field(..., description="MARKDOWN_SPLIT = ส่วนที่แยกมาลดราคา, KITCHEN_OUTPUT = ผลผลิตจากครัว")
    quantity: int
    current_selling_price: float
    expiration_date: date
    ai_status: str


class CompleteEffects(BaseModel):
    lots_updated: list[LotChange] = Field(..., description="lot ที่ถูกตัดสต็อก (ก่อน → หลัง)")
    lots_created: list[LotCreated] = Field(..., description="lot ใหม่ที่ถูกสร้าง")


class TaskCompleteResponse(BaseModel):
    task: TaskDetail
    effects: CompleteEffects
