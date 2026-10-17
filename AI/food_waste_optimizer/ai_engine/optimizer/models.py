"""PART 1 — โครงสร้างข้อมูล + แปลง JSON ของ GET /api/v1/ai/optimize-inputs (ตาม Swagger) เป็น object

ใช้ field ตามชื่อจริงใน Swagger / Supabase เท่านั้น (ไม่มี allow_upcycling, distance_km ฯลฯ ของโค้ดเดิมแล้ว)
หน่วยสินค้า: lot นับเป็นชิ้น/แพ็ค แต่สูตรอาหารใช้ G/ML -> แปลงด้วย net_content_value + net_content_unit
(KG / L คูณ 1000) ตามคำสั่งงาน
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Optional

# ประเภท partner -> ชื่อคอลัมน์ flag ใน table products
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
    """แปลงเป็นหน่วยฐาน (g หรือ ml) -> (ปริมาณ, 'MASS'|'VOLUME'); KG/L คูณ 1000"""
    if value is None or unit is None:
        return None, None
    u = str(unit).upper()
    if u in _MASS:
        return float(value) * _MASS[u], "MASS"
    if u in _VOLUME:
        return float(value) * _VOLUME[u], "VOLUME"
    return None, None


def _date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _time(v: Any) -> Optional[time]:
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
    content: Optional[float]          # ปริมาณต่อ 1 หน่วยนับ (g หรือ ml)
    family: Optional[str]             # MASS | VOLUME
    base_cost: float
    regular_price: float
    min_price: Optional[float]
    allow_markdown: bool
    allow_kitchen: bool
    disposal: dict = field(default_factory=dict)   # partner_type -> Optional[bool]

    @property
    def weight_kg(self) -> Optional[float]:
        """น้ำหนักจริงต่อหน่วย (kg) จากปริมาณสุทธิ; ML/L ใช้ความหนาแน่น 1 kg/L (ASSUMPTION)"""
        return self.content / 1000.0 if self.content else None

    @classmethod
    def from_json(cls, d: dict) -> "Product":
        content, family = to_base(d.get("net_content_value"), d.get("net_content_unit"))
        return cls(
            product_id=d["product_id"], name=d.get("name", d["product_id"]),
            category=d.get("category", ""), uom=d.get("unit_of_measure", ""),
            content=content, family=family,
            base_cost=_f(d.get("base_cost")), regular_price=_f(d.get("regular_price")),
            min_price=None if d.get("min_allowed_price") is None else float(d["min_allowed_price"]),
            allow_markdown=bool(d.get("allow_markdown")),
            allow_kitchen=bool(d.get("allow_kitchen_repurposing")),
            disposal={t: d.get(f) for t, f in FLAG_BY_TYPE.items()},
        )


@dataclass
class Lot:
    lot_id: str
    product_id: str
    quantity: int
    unit_cost: float
    price: float
    expiration_date: date
    aisle: Optional[str]
    shelf: Optional[str]
    assessment_id: Optional[str]
    run_id: Optional[str]
    risk_level: str
    risk_score: float
    predicted_sold: float
    predicted_leftover: float
    daily_demand: float


@dataclass
class Partner:
    partner_id: str
    name: str
    partner_type: str
    categories: set
    pickup_days: set                  # 1=จันทร์ ... 7=อาทิตย์ (ISO)
    t_start: Optional[time]
    t_end: Optional[time]
    min_days: int                     # NULL ใน DB = ไม่มีเกณฑ์ = 0
    min_kg: float                     # 0 = ไม่มีเกณฑ์
    max_kg: float
    fixed: float
    travel: float
    handling: float
    buyback: float
    active: bool

    @classmethod
    def from_json(cls, d: dict) -> "Partner":
        return cls(
            partner_id=d["partner_id"], name=d.get("name", d["partner_id"]),
            partner_type=d["partner_type"],
            categories=set(d.get("accepted_categories") or []),
            pickup_days={int(x) for x in (d.get("pickup_days") or [])},
            t_start=_time(d.get("pickup_time_start")), t_end=_time(d.get("pickup_time_end")),
            min_days=int(d.get("min_days_before_expiry") or 0),
            min_kg=_f(d.get("min_kg_per_pickup")),
            max_kg=_f(d.get("max_capacity_kg_per_pickup"), NO_CAPACITY_LIMIT),
            fixed=_f(d.get("fixed_cost_per_trip")), travel=_f(d.get("travel_cost_per_trip")),
            handling=_f(d.get("handling_fee_per_kg")), buyback=_f(d.get("buyback_price_per_kg")),
            active=bool(d.get("is_active", True)),
        )


@dataclass
class Ingredient:
    product_id: str
    need: Optional[float]             # ต่อ 1 batch หน่วยฐาน (g/ml) — KG/L คูณ 1000 แล้ว
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
    utility_cost: float               # รวมค่าไฟ+ค่าน้ำ+วัตถุดิบรองแล้ว (ตามคำสั่งงาน)
    active: bool
    ingredients: list

    @classmethod
    def from_json(cls, d: dict) -> "Recipe":
        ings = []
        for i in d.get("ingredients") or []:
            need, family = to_base(i.get("required_quantity"), i.get("unit_of_measure"))
            ings.append(Ingredient(i["ingredient_product_id"], need, family, bool(i.get("is_primary_ingredient"))))
        return cls(
            recipe_id=d["recipe_id"], name=d.get("name", d["recipe_id"]),
            output_product_id=d["output_product_id"], output_qty=_f(d.get("output_quantity")),
            prep_mins=d.get("estimated_prep_time_mins"), shelf_life_days=int(d.get("shelf_life_days") or 0),
            department_id=d.get("department_id"), utility_cost=_f(d.get("utility_cost")),
            active=bool(d.get("is_active", True)), ingredients=ings,
        )


@dataclass
class KitchenDay:
    department_id: str
    day: date
    remaining_hrs: float
    status: Optional[str]


@dataclass
class StockLot:
    lot_id: str
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
    kitchen: dict                     # (department_id, date) -> KitchenDay
    stock: dict                       # product_id -> [StockLot]  (ingredient_stock)

    @classmethod
    def from_json(cls, d: dict) -> "Inputs":
        products = {p["product_id"]: Product.from_json(p) for p in d.get("products") or []}
        lots = []
        for row in d.get("at_risk_lots") or []:
            lot = row.get("lot") or {}
            if not lot:
                continue
            prod = products.get(lot["product_id"])
            cost = lot.get("unit_cost")
            price = lot.get("current_selling_price")
            lots.append(Lot(
                lot_id=lot["lot_id"], product_id=lot["product_id"], quantity=int(lot["current_quantity"]),
                unit_cost=float(cost) if cost is not None else (prod.base_cost if prod else 0.0),
                price=float(price) if price is not None else (prod.regular_price if prod else 0.0),
                expiration_date=_date(lot["expiration_date"]),
                aisle=lot.get("location_aisle"), shelf=lot.get("location_shelf"),
                assessment_id=row.get("assessment_id"), run_id=row.get("run_id"),
                risk_level=row.get("risk_level", ""), risk_score=_f(row.get("risk_score")),
                predicted_sold=_f(row.get("predicted_units_sold_before_expiry")),
                predicted_leftover=_f(row.get("predicted_leftover_units")),
                daily_demand=_f(row.get("forecast_daily_demand")),
            ))
        kitchen = {}
        for k in d.get("kitchen_capacity") or []:
            remaining = k.get("remaining_hrs")
            if remaining is None:
                remaining = _f(k.get("available_hrs")) - _f(k.get("booked_hrs"))
            kd = KitchenDay(k["department_id"], _date(k["capacity_date"]), float(remaining), k.get("workload_status"))
            kitchen[(kd.department_id, kd.day)] = kd
        stock = {}
        for s in d.get("ingredient_stock") or []:
            stock[s["product_id"]] = [
                StockLot(x["lot_id"], int(x["current_quantity"]), _date(x["expiration_date"]))
                for x in s.get("lots") or []
            ]
        return cls(
            reference_date=_date(d["reference_date"]), run_id=d.get("run_id"), lots=lots, products=products,
            partners={p["partner_id"]: Partner.from_json(p) for p in d.get("donation_partners") or []},
            recipes={r["recipe_id"]: Recipe.from_json(r) for r in d.get("recipes") or []},
            kitchen=kitchen, stock=stock,
        )
