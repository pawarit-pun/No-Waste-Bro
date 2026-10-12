import hashlib
import json
import uuid
from datetime import date, datetime, time, timedelta

SIMULATION_START = datetime(2026, 10, 12, 14, 0, 0)

PRODUCT_CATEGORIES = ["DAIRY", "BAKERY", "MEAT", "SEAFOOD", "PRODUCE", "READY_TO_EAT"]
PARTNER_TYPES = ["DONATION", "ANIMAL_FEED", "COMPOSTING", "ANAEROBIC_DIGESTION", "LANDFILL"]
ACTION_TYPES = [
    "MARKDOWN", "KITCHEN_REPURPOSE", "DONATE", "DISCARD",
    "ANIMAL_FEED", "COMPOST", "ANAEROBIC_DIGESTION", "LANDFILL",
]
ACTIVE_BOOKING_STATUSES = ("CONFIRMED", "PLANNED")

OPTIMIZER_CONFIG = {
    "donation_tax_rate": 0.20,
    "variable_cost_per_km": 4.29,
    "labor_cost_per_minute": 1.53,
    "electricity_cost_per_hour": 40.0,
    "big_m_per_unit": 10000.0,
    "lead_time_minutes": 60,
    "expiry_cutoff_time": "23:59:59",
    "donation_min_hours_left": 12.0,
    "kappa": 0.0,
    "markdown_discount_levels": [0, 20, 30, 50],
    "markdown_max_depth_by_risk": {"LOW": 0, "MEDIUM": 30, "HIGH": 100, "CRITICAL": 100},
    "risk_forward_threshold": 50.0,
    "risk_levels": [[70.0, "CRITICAL"], [50.0, "HIGH"], [30.0, "MEDIUM"], [0.0, "LOW"]],
    "solver_time_limit_seconds": 10,
    "solver_mip_gap": 0.001,
    "guardrails": {
        "markdown_discount_cap_thb": 2000.0,
        "destroy_value_cap_thb": 1000.0,
        "trip_cost_cap_thb": 3000.0,
        "trip_cost_per_kg_cap_thb": 50.0,
        "solver_gap_cap": 0.01,
        "forecast_band_cap": 0.5,
        "kitchen_utilization_warning": 0.95,
        "approval_deadline_buffer_hours": 2.0,
        "max_resolve_rounds": 2,
    },
}

SCHEMA_CHANGES = [
    "products: added allow_upcycling (replaces allow_kitchen_repurposing, same values)",
    "products: added allow_landfill, allow_anaerobic_digestion, allow_composting, allow_animal_feed",
    "donation_partners: partner_type extended to DONATION, ANIMAL_FEED, COMPOSTING, ANAEROBIC_DIGESTION, LANDFILL",
    "donation_partners: added distance_km, fixed_cost_per_trip, handling_fee_per_kg",
    "donation_partners: accepted_categories contains every product category for every partner",
    "donation_partners: pickup_days is [1..7] (ISO, 1 = Monday) for every partner",
    "partner_pickup_bookings: new table (partner_id, pickup_datetime, booked_kg, status)",
    "optimizer_config: new table holding tax rate, cost per km, labor per minute and thresholds",
    "action_type: extended with ANIMAL_FEED, COMPOST, ANAEROBIC_DIGESTION, LANDFILL",
    "inventory_lots: added locked_by to record which run holds the lot",
]

STATIC_MISSING_ATTRIBUTES = [
    "products.allow_land: name is ambiguous in the request, column not created",
    "products.allow_landfill / allow_anaerobic_digestion / allow_composting / allow_animal_feed: no values given, set to TRUE for every product",
    "donation_partners.pickup_time_start / pickup_time_end: not given, assumed window per partner_type",
    "donation_partners.min_days_before_expiry: DONATION = 1 and ANIMAL_FEED = 0 assumed, LANDFILL / COMPOSTING / ANAEROBIC_DIGESTION = -30",
    "donation_partners.distance_km for DONATION: not given, set to 0.0 because donation has no travel cost",
    "donation_partners.fixed_cost_per_trip and handling_fee_per_kg: taken from the earlier design document",
    "partner_pickup_bookings: one mock booking for the composting partner (940 kg, trip already paid)",
    "recipe_ingredients: RCP-002 grilled chicken salad is missing from the recipe PDF, recipe_ingredients values from the database screenshot are used",
    "recipe_ingredients: ingredients that are not inventory products have no price and are costed at 0",
    "optimizer_config.electricity_cost_per_hour: 40 baht per hour is an assumption, no tariff or equipment power given",
    "products.requires_cold_chain: missing, cold chain matching with partners is not checked",
    "inventory_lots: quantities, received dates and expiry dates are mock values",
    "forecaster: demand curve, elasticity and menu demand come from simulated scraped data",
]


def unit_content_grams(product):
    value = float(product["net_content_value"])
    if product["net_content_unit"] in ("KG", "L"):
        return value * 1000.0
    return value


def unit_weight_kg(product):
    return unit_content_grams(product) / 1000.0


def _product(product_id, name, category, unit, base_cost, regular_price, min_price,
             allow_markdown, allow_upcycling, allow_donation, content_value, content_unit):
    return {
        "product_id": product_id,
        "name": name,
        "category": category,
        "unit_of_measure": unit,
        "base_cost": base_cost,
        "regular_price": regular_price,
        "min_allowed_price": min_price,
        "allow_markdown": allow_markdown,
        "allow_upcycling": allow_upcycling,
        "allow_donation": allow_donation,
        "allow_landfill": True,
        "allow_anaerobic_digestion": True,
        "allow_composting": True,
        "allow_animal_feed": True,
        "net_content_value": content_value,
        "net_content_unit": content_unit,
    }


def _build_products():
    rows = [
        _product("BAK-001", "ขนมปังแซนวิช 480g", "BAKERY", "PIECE", 32.00, 40.00, 20.00, True, True, True, 480, "G"),
        _product("BAK-002", "เค้กกล้วยหอม 700g", "BAKERY", "PIECE", 59.75, 179.00, 89.50, True, False, True, 700, "G"),
        _product("BAK-003", "ขนมปังพุดดิ้ง 150g", "BAKERY", "PIECE", 10.75, 35.00, 17.50, True, False, True, 150, "G"),
        _product("DAI-001", "นมสดพาสเจอร์ไรส์ รสจืด 830ml", "DAIRY", "PIECE", 38.95, 47.50, 23.75, True, True, True, 830, "ML"),
        _product("DAI-002", "โยเกิร์ต รสธรรมชาติ 125g", "DAIRY", "PIECE", 11.89, 14.50, 7.25, True, True, True, 125, "G"),
        _product("MEA-001", "อกไก่สด 500g", "MEAT", "PACK", 33.38, 44.50, 22.25, True, True, False, 500, "G"),
        _product("MEA-002", "เนื้อวัวสันนอก สเต็ก 500g", "MEAT", "PACK", 97.50, 130.00, 65.00, True, True, False, 500, "G"),
        _product("PRO-001", "กล้วยหอม 1kg", "PRODUCE", "PACK", 24.50, 35.00, 17.50, True, True, True, 1, "KG"),
        _product("PRO-002", "ผักกาดหอม 250g", "PRODUCE", "PACK", 16.63, 23.75, 11.88, True, True, True, 250, "G"),
        _product("RTE-001", "สเต็กเนื้อสันนอก พร้อมสลัด 300g", "READY_TO_EAT", "PIECE", 57.33, 169.00, 84.50, False, False, True, 300, "G"),
        _product("RTE-002", "สลัดอกไก่ย่าง 200g", "READY_TO_EAT", "PIECE", 19.67, 59.00, 29.50, False, False, False, 200, "G"),
        _product("RTE-003", "ข้าวหน้าแซลมอนย่าง 300g", "READY_TO_EAT", "PIECE", 34.95, 109.00, 54.50, False, False, True, 300, "G"),
        _product("RTE-004", "สมูทตี้กล้วยโยเกิร์ต 400ml", "READY_TO_EAT", "PIECE", 22.65, 65.00, 32.50, False, False, False, 400, "ML"),
        _product("SEA-001", "ปลาแซลมอนนอร์เวย์ ตัดชิ้น 300g", "SEAFOOD", "PACK", 83.16, 115.50, 57.75, True, True, False, 300, "G"),
    ]
    return {row["product_id"]: row for row in rows}


def _build_recipes():
    rows = [
        ("RCP-001", "สเต็กเนื้อสันนอก พร้อมสลัด", "READY_TO_EAT", "RTE-001", 10, 60, 0, True, "KITCHEN_DELI"),
        ("RCP-002", "สลัดอกไก่ย่าง", "READY_TO_EAT", "RTE-002", 10, 45, 1, True, "KITCHEN_DELI"),
        ("RCP-003", "ข้าวหน้าแซลมอนย่าง", "READY_TO_EAT", "RTE-003", 10, 45, 0, True, "KITCHEN_DELI"),
        ("RCP-004", "สมูทตี้กล้วยโยเกิร์ต", "READY_TO_EAT", "RTE-004", 8, 20, 0, True, "KITCHEN_DELI"),
        ("RCP-005", "เค้กกล้วยหอม", "BAKERY", "BAK-002", 4, 75, 3, True, "BAKERY_DEPT"),
        ("RCP-006", "ขนมปังพุดดิ้ง", "BAKERY", "BAK-003", 12, 50, 3, True, "BAKERY_DEPT"),
    ]
    keys = ["recipe_id", "name", "target_category", "output_product_id", "output_quantity",
            "estimated_prep_time_mins", "shelf_life_days", "is_active", "department_id"]
    return {row[0]: dict(zip(keys, row)) for row in rows}


def _ingredient(recipe_id, name, product_id, quantity, unit, primary):
    return {
        "recipe_id": recipe_id,
        "ingredient_name": name,
        "product_id": product_id,
        "required_quantity": float(quantity),
        "unit": unit,
        "is_primary_ingredient": primary,
    }


def _build_recipe_ingredients():
    rows = []
    add = rows.append
    add(_ingredient("RCP-001", "เนื้อวัวสันนอกดิบ", "MEA-002", 2400, "G", True))
    for name, qty in [("เกลือ", 24), ("พริกไทยดำบด", 7.5), ("กระเทียมสับ", 30), ("น้ำมันมะกอก", 45), ("เนย", 60)]:
        add(_ingredient("RCP-001", name, None, qty, "G", False))
    add(_ingredient("RCP-001", "ผักกาดหอมหรือกรีนโอ๊ค", "PRO-002", 360, "G", False))
    for name, qty in [("มะเขือเทศ", 240), ("แตงกวา", 180), ("พริกหวาน", 150), ("หอมหัวใหญ่", 120)]:
        add(_ingredient("RCP-001", name, None, qty, "G", False))
    for name, qty in [("น้ำมันมะกอก (น้ำสลัด)", 60), ("น้ำมะนาว", 36), ("น้ำผึ้ง", 15), ("มัสตาร์ด Dijon", 15),
                      ("น้ำส้มสายชูบัลซามิก", 15), ("กระเทียมสับ (น้ำสลัด)", 3), ("เกลือ (น้ำสลัด)", 3),
                      ("พริกไทยดำบด (น้ำสลัด)", 1.5), ("น้ำสะอาด", 1.5)]:
        add(_ingredient("RCP-001", name, None, qty, "G", False))
    add(_ingredient("RCP-002", "อกไก่สด", "MEA-001", 1000, "G", True))
    add(_ingredient("RCP-002", "ผักกาดหอม", "PRO-002", 750, "G", False))
    add(_ingredient("RCP-003", "เนื้อปลาแซลมอนดิบ", "SEA-001", 1200, "G", True))
    for name, qty in [("ข้าวญี่ปุ่นดิบ", 650), ("น้ำสำหรับหุงข้าว", 780), ("ซีอิ๊วญี่ปุ่น", 25), ("มิริน", 10),
                      ("น้ำผึ้ง", 8), ("น้ำมันงา", 4), ("กระเทียมสับ", 10), ("เกลือ", 5), ("พริกไทยดำ", 2),
                      ("แตงกวา", 100), ("ต้นหอม", 20), ("งาขาวคั่ว", 10), ("สาหร่ายโนริ", 20)]:
        add(_ingredient("RCP-003", name, None, qty, "G", False))
    add(_ingredient("RCP-004", "กล้วยหอมสุก (ปอกเปลือก)", "PRO-001", 800, "G", True))
    add(_ingredient("RCP-004", "โยเกิร์ต รสธรรมชาติ", "DAI-002", 800, "ML", True))
    add(_ingredient("RCP-004", "นมสด", "DAI-001", 800, "ML", False))
    add(_ingredient("RCP-004", "น้ำผึ้ง", None, 80, "ML", False))
    add(_ingredient("RCP-004", "น้ำแข็ง", None, 400, "G", False))
    add(_ingredient("RCP-005", "กล้วยหอมสุก ปอกเปลือก", "PRO-001", 800, "G", True))
    add(_ingredient("RCP-005", "นมสด", "DAI-001", 250, "G", False))
    for name, qty in [("แป้งสาลีอเนกประสงค์", 700), ("น้ำตาลทราย", 450), ("ไข่ไก่ไม่รวมเปลือก", 400),
                      ("น้ำมันพืช", 350), ("ผงฟู", 20), ("เบกกิ้งโซดา", 10), ("เกลือ", 8), ("กลิ่นวานิลลา", 20)]:
        add(_ingredient("RCP-005", name, None, qty, "G", False))
    add(_ingredient("RCP-006", "ขนมปังแซนด์วิช", "BAK-001", 550, "G", True))
    add(_ingredient("RCP-006", "นมสด", "DAI-001", 750, "ML", True))
    for name, qty, unit in [("ไข่ไก่ไม่รวมเปลือก", 300, "G"), ("น้ำตาลทราย", 180, "G"), ("เนยจืด", 100, "G"),
                            ("ลูกเกด", 100, "G"), ("กลิ่นวานิลลา", 10, "ML"), ("ผงอบเชย", 5, "G"), ("เกลือ", 5, "G")]:
        add(_ingredient("RCP-006", name, None, qty, unit, False))
    return rows


def _partner(partner_id, name, partner_type, distance, fixed, handling, capacity, start, end, min_days, contact):
    return {
        "partner_id": partner_id,
        "name": name,
        "partner_type": partner_type,
        "accepted_categories": list(PRODUCT_CATEGORIES),
        "pickup_days": [1, 2, 3, 4, 5, 6, 7],
        "pickup_time_start": start,
        "pickup_time_end": end,
        "min_days_before_expiry": min_days,
        "max_capacity_kg_per_pickup": capacity,
        "requires_cold_chain": False,
        "contact_name": contact,
        "contact_phone": "000-000-0000",
        "is_active": True,
        "distance_km": distance,
        "fixed_cost_per_trip": fixed,
        "handling_fee_per_kg": handling,
    }


def _build_partners():
    rows = [
        _partner("P-DON-01", "Central Food Bank", "DONATION", 0.0, 550.0, 0.0, 800.0, time(9, 0), time(11, 0), 1, "Donation Desk"),
        _partner("P-ANI-01", "Animal Feed Farm", "ANIMAL_FEED", 6.0, 1000.0, 0.30, 1000.0, time(16, 0), time(18, 0), 0, "Farm Office"),
        _partner("P-CMP-01", "Composting Facility", "COMPOSTING", 8.5, 1600.0, 0.60, 1000.0, time(17, 0), time(19, 0), -30, "Compost Plant"),
        _partner("P-ADG-01", "Anaerobic Digestion Biogas Plant", "ANAEROBIC_DIGESTION", 16.0, 1750.0, 0.90, 950.0, time(8, 0), time(10, 0), -30, "Biogas Plant"),
        _partner("P-LDF-01", "Landfill Site", "LANDFILL", 12.5, 650.0, 1.15, 1000.0, time(18, 0), time(20, 0), -30, "Landfill Gate"),
    ]
    return {row["partner_id"]: row for row in rows}


LOT_SEEDS = [
    ("L-2201", "MEA-001", 220, 4, 1, "IDLE"),
    ("L-2202", "SEA-001", 60, 3, 1, "IDLE"),
    ("L-2203", "PRO-001", 150, 3, 2, "IDLE"),
    ("L-2204", "PRO-002", 100, 2, 1, "IDLE"),
    ("L-2205", "DAI-002", 240, 5, 2, "IDLE"),
    ("L-2206", "BAK-001", 40, 7, -1, "IDLE"),
    ("L-2207", "MEA-002", 36, 3, 1, "IDLE"),
    ("L-2208", "BAK-003", 40, 2, 2, "IDLE"),
    ("L-2209", "DAI-001", 50, 4, 2, "PROCESSING"),
]


class Database:
    def __init__(self, now):
        self.now = now
        self.optimizer_config = json.loads(json.dumps(OPTIMIZER_CONFIG))
        self.products = _build_products()
        self.recipes = _build_recipes()
        self.recipe_ingredients = _build_recipe_ingredients()
        self.donation_partners = _build_partners()
        self.kitchen_capacity = {
            "BAKERY_DEPT": {"department_id": "BAKERY_DEPT", "department_name": "แผนกเบเกอรี่", "daily_processing_capacity_hrs": 8.0},
            "KITCHEN_DELI": {"department_id": "KITCHEN_DELI", "department_name": "ครัวเดลี่", "daily_processing_capacity_hrs": 8.0},
        }
        self.kitchen_capacity_daily = self._build_kitchen_daily()
        self.inventory_lots = self._build_lots()
        self.partner_pickup_bookings = self._build_bookings()
        self.lot_risk_assessments = []
        self.decisions = []
        self.approval_queue = []

    def _build_kitchen_daily(self):
        rows = {}
        plan = {"KITCHEN_DELI": (8.0, 2.0, "BUSY"), "BAKERY_DEPT": (8.0, 3.0, "AVAILABLE")}
        for offset in range(0, 3):
            day = self.now.date() + timedelta(days=offset)
            for department, (available, booked, status) in plan.items():
                rows[(department, day)] = {
                    "department_id": department,
                    "capacity_date": day,
                    "available_hrs": available,
                    "booked_hrs": booked,
                    "remaining_hrs": available - booked,
                    "workload_status": status,
                }
        return rows

    def _build_lots(self):
        lots = {}
        today = self.now.date()
        for lot_id, product_id, quantity, received_ago, expiry_in, status in LOT_SEEDS:
            product = self.products[product_id]
            lots[lot_id] = {
                "lot_id": lot_id,
                "product_id": product_id,
                "batch_number": "B-" + lot_id[-4:],
                "received_date": today - timedelta(days=received_ago),
                "expiration_date": today + timedelta(days=expiry_in),
                "initial_quantity": quantity,
                "current_quantity": quantity,
                "unit_cost": product["base_cost"],
                "ai_status": status,
                "current_selling_price": product["regular_price"],
                "locked_by": None,
            }
        return lots

    def _build_bookings(self):
        today = self.now.date()
        return [{
            "booking_id": "BK-0001",
            "partner_id": "P-CMP-01",
            "pickup_datetime": datetime.combine(today, time(17, 0)),
            "booked_kg": 940.0,
            "status": "CONFIRMED",
        }]

    def get_product(self, product_id):
        return self.products[product_id]

    def get_lot(self, lot_id):
        return self.inventory_lots[lot_id]

    def get_partner(self, partner_id):
        return self.donation_partners[partner_id]

    def get_recipe(self, recipe_id):
        return self.recipes[recipe_id]

    def ingredients_of(self, recipe_id):
        return [row for row in self.recipe_ingredients if row["recipe_id"] == recipe_id]

    def recipes_with_primary(self, product_id):
        ids = {row["recipe_id"] for row in self.recipe_ingredients
               if row["product_id"] == product_id and row["is_primary_ingredient"]}
        return [self.recipes[rid] for rid in sorted(ids) if self.recipes[rid]["is_active"]]

    def kitchen_daily(self, department_id, day):
        return self.kitchen_capacity_daily.get((department_id, day))

    def lots_ready_for_run(self):
        return [lot for lot in self.inventory_lots.values()
                if lot["ai_status"] == "IDLE" and lot["current_quantity"] > 0]

    def lock_lots(self, run_id, lot_ids):
        locked = []
        for lot_id in lot_ids:
            lot = self.inventory_lots[lot_id]
            if lot["ai_status"] == "IDLE" or lot["locked_by"] == run_id:
                lot["ai_status"] = "PROCESSING"
                lot["locked_by"] = run_id
                locked.append(lot_id)
        return locked

    def release_lots(self, run_id, status="CHECKED"):
        for lot in self.inventory_lots.values():
            if lot["locked_by"] == run_id:
                lot["ai_status"] = status
                lot["locked_by"] = None

    def insert_assessment(self, row):
        self.lot_risk_assessments = [r for r in self.lot_risk_assessments if r["assessment_id"] != row["assessment_id"]]
        self.lot_risk_assessments.append(row)

    def get_assessment(self, assessment_id):
        for row in self.lot_risk_assessments:
            if row["assessment_id"] == assessment_id:
                return row
        raise KeyError(assessment_id)

    def booked_kg_at_slot(self, partner_id, day):
        return sum(b["booked_kg"] for b in self.partner_pickup_bookings
                   if b["partner_id"] == partner_id
                   and b["status"] in ACTIVE_BOOKING_STATUSES
                   and b["pickup_datetime"].date() == day)

    def add_booking(self, partner_id, pickup_datetime, booked_kg):
        booking_id = "BK-%04d" % (len(self.partner_pickup_bookings) + 1)
        self.partner_pickup_bookings.append({
            "booking_id": booking_id,
            "partner_id": partner_id,
            "pickup_datetime": pickup_datetime,
            "booked_kg": float(booked_kg),
            "status": "CONFIRMED",
        })
        return booking_id

    def executed_decisions(self, lot_id):
        return [d for d in self.decisions
                if d["lot_id"] == lot_id and d["execution_state"] in ("IN_PROGRESS", "COMPLETED")]

    def insert_decisions(self, rows):
        self.decisions.extend(rows)

    def insert_approvals(self, rows):
        self.approval_queue.extend(rows)

    def fingerprint(self):
        bookings = {}
        for partner_id in self.donation_partners:
            total = sum(b["booked_kg"] for b in self.partner_pickup_bookings
                        if b["partner_id"] == partner_id and b["status"] in ACTIVE_BOOKING_STATUSES)
            bookings[partner_id] = round(total, 3)
        return {
            "lots": {lot_id: [lot["current_quantity"], lot["current_selling_price"]]
                     for lot_id, lot in self.inventory_lots.items()},
            "bookings": bookings,
            "kitchen": {"%s|%s" % (department, day.isoformat()): row["booked_hrs"]
                        for (department, day), row in self.kitchen_capacity_daily.items()},
        }

    def audit_missing(self):
        unpriced = sorted({row["ingredient_name"] for row in self.recipe_ingredients if row["product_id"] is None})
        return list(STATIC_MISSING_ATTRIBUTES) + [
            "recipe_ingredients without price (%d distinct names): %s" % (len(unpriced), ", ".join(unpriced))
        ]


def fingerprint_hash(fingerprint):
    payload = json.dumps(fingerprint, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def build_mock_database(now=None):
    return Database(now or SIMULATION_START)


def new_run_id(now):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "run|" + now.isoformat()))