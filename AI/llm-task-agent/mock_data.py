"""
Sample decisions in the same shape as GET /optimization-decisions, for offline runs and tests.

Product names come from the demo catalogue; decision IDs, lots, recipes and partners are
fictional. Covers all four action types plus the edge cases the agent must handle:
  1. MARKDOWN                 normal case with alternatives
  2. KITCHEN_REPURPOSE        lot without a shelf location
  3. DONATE                   partner context present
  4. DISCARD with a partner   partner context missing (the server only sends it for DONATE)
  5. DISCARD, no partner      no assessment and no due time
"""

from models import OptimizationDecision

RUN_ID = "11111111-1111-1111-1111-111111111111"


def _decision(n: int, **fields) -> dict:
    """Fields every action shares; unused action fields are null like in the API."""
    base = {
        "decision_id": f"00000000-0000-0000-0000-{n:012d}",
        "run_id": RUN_ID,
        "assessment_id": f"aaaaaaaa-0000-0000-0000-{n:012d}",
        "discount_pct": None,
        "new_recommended_price": None,
        "target_recipe_id": None,
        "batch_count": None,
        "target_partner_id": None,
        "decision_score": 0.8,
        "optimizer_version": "mock-v2",
        "created_at": "2026-10-16T06:00:00+07:00",
        "status": "PENDING",
        "task_id": None,
        "alternatives": [],
        "recipe": None,
        "partner": None,
    }
    base.update(fields)
    return base


RAW_DECISIONS = [
    _decision(
        1,
        lot_id="LOT-900001",
        action_type="MARKDOWN",
        action_quantity=30,
        discount_pct=30,
        new_recommended_price=33.25,
        due_by="2026-10-16T20:00:00+07:00",
        expected_profit_impact=-300,
        alternatives=[
            {"action_type": "MARKDOWN", "discount_pct": 50, "expected_profit_impact": -450},
            {"action_type": "DISCARD", "expected_profit_impact": -1168.5},
        ],
        assessment={"days_to_expiry": 1, "quantity_at_assessment": 42,
                    "predicted_leftover_units": 30, "risk_score": 0.86, "risk_level": "CRITICAL"},
        lot={"lot_id": "LOT-900001", "product_id": "DAI-001", "current_quantity": 42,
             "current_selling_price": 47.5, "expiration_date": "2026-10-17",
             "location_aisle": "CHILL-A", "location_shelf": "A-01"},
        product={"product_id": "DAI-001", "name": "นมสดพาสเจอร์ไรส์ รสจืด 830ml", "category": "DAIRY",
                 "unit_of_measure": "PIECE", "regular_price": 47.5, "min_allowed_price": 23.75},
    ),
    _decision(
        2,
        lot_id="LOT-900002",
        action_type="KITCHEN_REPURPOSE",
        action_quantity=8,
        target_recipe_id="RCP-901",
        batch_count=1,
        due_by="2026-10-16T15:00:00+07:00",
        expected_profit_impact=96,
        alternatives=[{"action_type": "MARKDOWN", "discount_pct": 40, "expected_profit_impact": -128}],
        assessment={"days_to_expiry": 1, "quantity_at_assessment": 8,
                    "predicted_leftover_units": 8, "risk_score": 0.72, "risk_level": "HIGH"},
        lot={"lot_id": "LOT-900002", "product_id": "BAK-001", "current_quantity": 8,
             "current_selling_price": 40.0, "expiration_date": "2026-10-17",
             "location_aisle": None, "location_shelf": None},
        product={"product_id": "BAK-001", "name": "ขนมปังแซนวิช 480g", "category": "BAKERY",
                 "unit_of_measure": "PIECE", "regular_price": 40.0, "min_allowed_price": 20.0},
        recipe={"recipe_id": "RCP-901", "name": "ขนมปังพุดดิ้ง", "department_id": "DEPT-BAKERY",
                "output_product_id": "BAK-003", "output_quantity": 12,
                "estimated_prep_time_mins": 45, "shelf_life_days": 2},
    ),
    _decision(
        3,
        lot_id="LOT-900003",
        action_type="DONATE",
        action_quantity=10,
        target_partner_id="P-901",
        due_by="2026-10-17T10:00:00+07:00",
        expected_profit_impact=-245,
        alternatives=[{"action_type": "DISCARD", "expected_profit_impact": -350}],
        assessment={"days_to_expiry": 2, "quantity_at_assessment": 18,
                    "predicted_leftover_units": 10, "risk_score": 0.64, "risk_level": "HIGH"},
        lot={"lot_id": "LOT-900003", "product_id": "PRO-001", "current_quantity": 18,
             "current_selling_price": 35.0, "expiration_date": "2026-10-18",
             "location_aisle": "PRODUCE-B", "location_shelf": "B-02"},
        product={"product_id": "PRO-001", "name": "กล้วยหอม 1kg", "category": "PRODUCE",
                 "unit_of_measure": "PACK", "regular_price": 35.0, "min_allowed_price": 17.5},
        partner={"partner_id": "P-901", "name": "มูลนิธิอาหารเพื่อชุมชน (ตัวอย่าง)",
                 "partner_type": "FOOD_BANK", "pickup_days": [1, 3, 5],
                 "pickup_time_start": "09:00", "pickup_time_end": "11:00",
                 "contact_name": None, "contact_phone": None},
    ),
    _decision(
        4,
        lot_id="LOT-900004",
        action_type="DISCARD",
        action_quantity=6,
        target_partner_id="P-905",
        due_by="2026-10-16T18:00:00+07:00",
        expected_profit_impact=-290.4,
        alternatives=[{"disposal_method": "SELF_DISCARD", "expected_profit_impact": -267,
                       "note": "ไม่รวมค่าขนย้าย"}],
        assessment={"days_to_expiry": 0, "quantity_at_assessment": 6,
                    "predicted_leftover_units": 6, "risk_score": 0.95, "risk_level": "CRITICAL"},
        lot={"lot_id": "LOT-900004", "product_id": "MEA-001", "current_quantity": 6,
             "current_selling_price": 44.5, "expiration_date": "2026-10-16",
             "location_aisle": "MEAT-C", "location_shelf": "C-03"},
        product={"product_id": "MEA-001", "name": "อกไก่สด 500g", "category": "MEAT",
                 "unit_of_measure": "PACK", "regular_price": 44.5, "min_allowed_price": 22.25},
    ),
    _decision(
        5,
        assessment_id=None,
        lot_id="LOT-900005",
        action_type="DISCARD",
        action_quantity=3,
        due_by=None,
        expected_profit_impact=None,
        assessment=None,
        lot={"lot_id": "LOT-900005", "product_id": "RTE-002", "current_quantity": 3,
             "current_selling_price": 59.0, "expiration_date": "2026-10-16",
             "location_aisle": "RTE-D", "location_shelf": "D-01"},
        product={"product_id": "RTE-002", "name": "สลัดอกไก่ย่าง 200g", "category": "READY_TO_EAT",
                 "unit_of_measure": "PIECE", "regular_price": 59.0, "min_allowed_price": 29.5},
    ),
]


def get_mock_decisions() -> list[OptimizationDecision]:
    """Return fictional decisions for local development (validated like API data)."""
    return [OptimizationDecision.model_validate(d) for d in RAW_DECISIONS]
