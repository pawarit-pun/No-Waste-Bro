"""PART 1 — แปลง JSON ของ GET /api/v1/ai/optimize-inputs (ข้อมูลจริงจาก Supabase) เป็น object ที่ Optimizer ใช้

ใช้ชื่อ field ตาม Swagger / ตาราง Supabase เท่านั้น
  at_risk_lots[]   = lot_risk_assessments (+ lot = inventory_lots, + shelf = lot_shelf_forecasts) ของรอบสแกน
  recipe_demand[]  = recipe_demand_forecasts (ความต้องการเมนูครัวจาก Forecaster)
  products / recipes / kitchen_capacity / donation_partners / ingredient_stock
หน่วย: lot นับเป็นชิ้น/แพ็ค สูตรใช้ G / ML -> แปลงด้วย net_content_value + net_content_unit (KG / L คูณ 1000)

optimize-inputs ยังไม่ส่ง allow_animal_feed / allow_composting / allow_anaerobic_digestion / allow_landfill
จึงรับรายการสินค้าเต็มจาก GET /api/v1/products (หรือตาราง products) มาเติมผ่าน products_catalog
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Optional

from ai_engine.optimizer.config import BKK

# ประเภท partner -> คอลัมน์ flag ในตาราง products
FLAG_BY_TYPE = {
    "DONATION": "allow_donation",
    "ANIMAL_FEED": "allow_animal_feed",
    "COMPOSTING": "allow_composting",
    "ANAEROBIC_DIGESTION": "allow_anaerobic_digestion",
    "LANDFILL": "allow_landfill",
}
_MASS = {"G": 1.0, "KG": 1000.0}
_VOLUME = {"ML": 1.0, "L": 1000.0}
NO_CAPACITY_LIMIT = 1e9


def to_base(value: Any, unit: Any) -> tuple[Optional[float], Optional[str]]:
    """แปลงเป็นหน่วยฐาน g / ml -> (ปริมาณ, 'MASS' | 'VOLUME') KG / L คูณ 1000"""
    if value is None or unit is None:
        return None, None
    u = str(unit).upper()
    if u in _MASS:
        return float(value) * _MASS[u], "MASS"
    if u in _VOLUME:
        return float(value) * _VOLUME[u], "VOLUME"
    return None, None


def as_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def as_datetime(v: Any) -> datetime:
    """timestamptz ของ Supabase (UTC หรือ +07:00) -> datetime เวลาไทย (ไม่มี timezone = เวลาไทย)"""
    dt = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return dt.replace(tzinfo=BKK) if dt.tzinfo is None else dt.astimezone(BKK)


def as_time(v: Any) -> Optional[time]:
    if v is None:
        return None
    if isinstance(v, time):
        return v
    return time.fromisoformat(str(v)[:8])


def _f(v: Any, default: float = 0.0) -> float:
    return float(v) if v is not None else default


@dataclass
class Product:
    product_id: str
    name: str
    category: str
    uom: str
    content: Optional[float]            # ปริมาณต่อ 1 หน่วยนับ (g หรือ ml)
    family: Optional[str]               # MASS | VOLUME
    base_cost: float
    regular_price: float
    min_price: Optional[float]
    allow_markdown: bool
    allow_kitchen: bool
    disposal: dict = field(default_factory=dict)   # partner_type -> True / False / None(ไม่มีข้อมูล)

    @property
    def weight_kg(self) -> Optional[float]:
        """น้ำหนักจริงต่อหน่วย (kg) จากปริมาณสุทธิ  ASSUMPTION: ML / L ใช้ความหนาแน่น 1 kg/L"""
        return self.content / 1000.0 if self.content else None

    @classmethod
    def from_json(cls, d: dict, extra: Optional[dict] = None) -> "Product":
        extra = extra or {}
        content, family = to_base(d.get("net_content_value"), d.get("net_content_unit"))
        flag = lambda f: d[f] if d.get(f) is not None else extra.get(f)
        return cls(
            product_id=d["product_id"], name=d.get("name", d["product_id"]), category=d.get("category", ""),
            uom=d.get("unit_of_measure", ""), content=content, family=family,
            base_cost=_f(d.get("base_cost")), regular_price=_f(d.get("regular_price")),
            min_price=None if d.get("min_allowed_price") is None else float(d["min_allowed_price"]),
            allow_markdown=bool(d.get("allow_markdown")), allow_kitchen=bool(d.get("allow_kitchen_repurposing")),
            disposal={t: flag(f) for t, f in FLAG_BY_TYPE.items()},
        )


@dataclass
class ShelfRow:
    """1 แถวของ lot_shelf_forecasts: ลด discount_pct% ตั้งแต่เปิดร้านวันนี้จนหมดอายุ จะขายได้เท่าไร"""
    discount_pct: float
    price: float
    expected_qty: float
    low_qty: float
    high_qty: float
    lost_sales_other_lots: float


@dataclass
class Lot:
    lot_id: str
    product_id: str
    quantity: int                      # inventory_lots.current_quantity ตอนนี้
    unit_cost: float
    price: float                       # current_selling_price
    expiration_date: date
    aisle: Optional[str]
    shelf_loc: Optional[str]
    ai_status: Optional[str]
    assessment_id: str
    run_id: Optional[str]
    risk_level: str
    risk_score: float
    days_to_expiry_assessed: int
    quantity_assessed: int
    forecast_daily_demand: float
    predicted_sold: float
    predicted_leftover: float
    sellable_hours: Optional[int]
    shelf: list = field(default_factory=list)


@dataclass
class Partner:
    partner_id: str
    name: str
    partner_type: str
    categories: set
    pickup_days: set                   # 1 = จันทร์ ... 7 = อาทิตย์ (ISO)
    t_start: Optional[time]
    t_end: Optional[time]
    min_days: int                      # NULL ใน DB = ไม่มีเงื่อนไข = 0
    min_kg: float                      # 0 = ไม่มีขั้นต่ำ
    max_kg: float
    fixed: float
    travel: float
    handling: float
    buyback: float
    active: bool
    contact: Optional[str] = None

    @classmethod
    def from_json(cls, d: dict) -> "Partner":
        return cls(
            partner_id=d["partner_id"], name=d.get("name", d["partner_id"]), partner_type=d["partner_type"],
            categories=set(d.get("accepted_categories") or []),
            pickup_days={int(x) for x in (d.get("pickup_days") or [])},
            t_start=as_time(d.get("pickup_time_start")), t_end=as_time(d.get("pickup_time_end")),
            min_days=int(d.get("min_days_before_expiry") or 0), min_kg=_f(d.get("min_kg_per_pickup")),
            max_kg=_f(d.get("max_capacity_kg_per_pickup"), NO_CAPACITY_LIMIT),
            fixed=_f(d.get("fixed_cost_per_trip")), travel=_f(d.get("travel_cost_per_trip")),
            handling=_f(d.get("handling_fee_per_kg")), buyback=_f(d.get("buyback_price_per_kg")),
            active=bool(d.get("is_active", True)), contact=d.get("contact_name"),
        )


@dataclass
class Ingredient:
    product_id: str
    need: Optional[float]              # ต่อ 1 batch ในหน่วยฐาน g / ml
    family: Optional[str]
    primary: bool


@dataclass
class Recipe:
    recipe_id: str
    name: str
    output_product_id: str
    output_qty: float
    prep_mins: Optional[int]
    shelf_life_days: int
    department_id: Optional[str]
    utility_cost: float                # รวมค่าไฟ + ค่าน้ำ + วัตถุดิบรองต่อ batch แล้ว (ตามที่ทีมกำหนด)
    active: bool
    ingredients: list

    @property
    def hours_per_batch(self) -> float:
        return (self.prep_mins or 0) / 60.0

    @classmethod
    def from_json(cls, d: dict) -> "Recipe":
        ings = []
        for i in d.get("ingredients") or []:
            need, family = to_base(i.get("required_quantity"), i.get("unit_of_measure"))
            ings.append(Ingredient(i["ingredient_product_id"], need, family, bool(i.get("is_primary_ingredient"))))
        return cls(
            recipe_id=d["recipe_id"], name=d.get("name", d["recipe_id"]), output_product_id=d["output_product_id"],
            output_qty=_f(d.get("output_quantity")), prep_mins=d.get("estimated_prep_time_mins"),
            shelf_life_days=int(d.get("shelf_life_days") or 0), department_id=d.get("department_id"),
            utility_cost=_f(d.get("utility_cost")), active=bool(d.get("is_active", True)), ingredients=ings,
        )


@dataclass
class RecipeDemand:
    """1 แถวของ recipe_demand_forecasts: เมนูนี้ควรผลิตเพิ่มเท่าไรในช่วงอายุเมนู (หักของบนชั้นแล้ว)"""
    recipe_id: str
    window_from: date
    window_to: date
    gross_demand: float
    current_stock: int
    menu_qty: float
    low_qty: float
    high_qty: float


@dataclass
class KitchenDay:
    department_id: str
    day: date
    remaining_hrs: float
    status: Optional[str]


@dataclass
class StockLot:
    lot_id: str
    product_id: str
    quantity: int
    expiration_date: date


@dataclass
class Inputs:
    reference_date: date
    run_id: Optional[str]
    lots: list
    products: dict
    partners: dict
    recipes: dict
    recipe_demand: dict                # recipe_id -> RecipeDemand
    kitchen: dict                      # (department_id, date) -> KitchenDay
    stock: dict                        # product_id -> [StockLot] เรียงหมดอายุก่อน (ลำดับที่ DB ตัดจริง)
    warnings: list = field(default_factory=list)
    waste_kg_per_day: dict = field(default_factory=dict)   # หมวดสินค้า -> ของทิ้งเฉลี่ย kg/วัน (product_daily.waste_qty)
    waste_history_days: int = 0                            # จำนวนวันย้อนหลังที่ใช้เฉลี่ย (0 = ไม่มีข้อมูล)
    partner_bins: dict = field(default_factory=dict)       # partner_id -> kg ที่รออยู่ในถังแล้ว (decision ที่ยังไม่ส่งมอบ)
    partner_bin_since: dict = field(default_factory=dict)  # partner_id -> ของในถังชิ้นที่รอนานสุดเข้าถังเมื่อไร

    @classmethod
    def from_json(cls, d: dict, products_catalog: Optional[list] = None) -> "Inputs":
        catalog = {p["product_id"]: p for p in products_catalog or []}
        products = {p["product_id"]: Product.from_json(p, catalog.get(p["product_id"])) for p in d.get("products") or []}
        lots, warnings = [], []
        for row in d.get("at_risk_lots") or []:
            lot = row.get("lot")
            if not lot:
                warnings.append(f"assessment {row.get('assessment_id')}: ไม่มีข้อมูล lot แนบมา ข้าม")
                continue
            prod = products.get(lot["product_id"])
            cost, price = lot.get("unit_cost"), lot.get("current_selling_price")
            shelf = [ShelfRow(float(s["discount_pct"]), float(s["price"]), float(s["expected_qty"]), float(s["low_qty"]),
                              float(s["high_qty"]), _f(s.get("lost_sales_other_lots")))
                     for s in sorted(row.get("shelf") or [], key=lambda s: float(s["discount_pct"]))]
            lots.append(Lot(
                lot_id=lot["lot_id"], product_id=lot["product_id"], quantity=int(lot["current_quantity"]),
                unit_cost=float(cost) if cost is not None else (prod.base_cost if prod else 0.0),
                price=float(price) if price is not None else (prod.regular_price if prod else 0.0),
                expiration_date=as_date(lot["expiration_date"]), aisle=lot.get("location_aisle"),
                shelf_loc=lot.get("location_shelf"), ai_status=lot.get("ai_status"),
                assessment_id=str(row["assessment_id"]), run_id=row.get("run_id"),
                risk_level=row.get("risk_level", ""), risk_score=_f(row.get("risk_score")),
                days_to_expiry_assessed=int(row.get("days_to_expiry") or 0),
                quantity_assessed=int(row.get("quantity_at_assessment") or 0),
                forecast_daily_demand=_f(row.get("forecast_daily_demand")),
                predicted_sold=_f(row.get("predicted_units_sold_before_expiry")),
                predicted_leftover=_f(row.get("predicted_leftover_units")),
                sellable_hours=row.get("sellable_hours"), shelf=shelf,
            ))
        demand = {}
        for r in d.get("recipe_demand") or []:
            demand[r["recipe_id"]] = RecipeDemand(
                r["recipe_id"], as_date(r["window_from"]), as_date(r["window_to"]), _f(r.get("gross_demand")),
                int(r.get("current_stock") or 0), _f(r.get("menu_qty")), _f(r.get("low_qty")), _f(r.get("high_qty")))
        kitchen = {}
        for k in d.get("kitchen_capacity") or []:
            remaining = k.get("remaining_hrs")
            if remaining is None:
                remaining = _f(k.get("available_hrs")) - _f(k.get("booked_hrs"))
            kd = KitchenDay(k["department_id"], as_date(k["capacity_date"]), float(remaining), k.get("workload_status"))
            kitchen[(kd.department_id, kd.day)] = kd
        stock = {}
        for s in d.get("ingredient_stock") or []:
            rows = [StockLot(x["lot_id"], s["product_id"], int(x["current_quantity"]), as_date(x["expiration_date"]))
                    for x in s.get("lots") or []]
            stock[s["product_id"]] = sorted(rows, key=lambda x: (x.expiration_date, x.lot_id))
        history = d.get("waste_history") or {}
        return cls(
            reference_date=as_date(d["reference_date"]), run_id=d.get("run_id"), lots=lots, products=products,
            partners={p["partner_id"]: Partner.from_json(p) for p in d.get("donation_partners") or []},
            recipes={r["recipe_id"]: Recipe.from_json(r) for r in d.get("recipes") or []},
            recipe_demand=demand, kitchen=kitchen, stock=stock, warnings=warnings,
            waste_kg_per_day={c: float(v) for c, v in (history.get("kg_per_day") or {}).items()},
            waste_history_days=int(history.get("days") or 0),
            partner_bins={b["partner_id"]: _f(b.get("open_kg")) for b in d.get("partner_bins") or []},
            partner_bin_since={b["partner_id"]: as_datetime(b["oldest_at"]) for b in d.get("partner_bins") or []
                               if b.get("oldest_at")},
        )