"""
Mock optimization decisions for local LLM Task Agent development.

All records are fictional and for testing only.
"""

from models import OptimizationDecision


MOCK_DECISIONS = [
    # Case 1: Markdown — reduce the selling price
    OptimizationDecision(
        decision_id="mock-decision-001",
        run_id="mock-run-001",
        assessment_id="mock-assessment-001",
        lot_id="mock-lot-001",
        action_type="MARKDOWN",
        action_quantity=20,
        discount_pct=15,
        new_recommended_price=42.50,
        due_by="2026-10-18T12:00:00Z",
        expected_profit_impact=150,
        decision_score=0.91,
        status="PENDING",
        optimizer_version="mock-v1",
        created_at="2026-10-17T06:00:00Z",
        assessment={
            "days_to_expiry": 2,
            "quantity_at_assessment": 20,
            "predicted_leftover_units": 12,
            "risk_score": 0.85,
            "risk_level": "HIGH",
        },
        lot={
            "lot_id": "mock-lot-001",
            "product_id": "mock-product-001",
            "current_quantity": 20,
            "current_selling_price": 50.0,
            "expiration_date": "2026-10-19",
            "location_aisle": "A1",
            "location_shelf": "S2",
        },
        product={
            "product_id": "mock-product-001",
            "name": "Fresh Sandwich",
            "category": "Ready-to-eat",
            "unit_of_measure": "piece",
            "regular_price": 50.0,
            "min_allowed_price": 35.0,
        },
    ),

    # Case 2: Processing — use a recipe to process ingredients
    OptimizationDecision(
        decision_id="mock-decision-002",
        run_id="mock-run-001",
        assessment_id="mock-assessment-002",
        lot_id="mock-lot-002",
        action_type="PROCESSING",
        action_quantity=10,
        target_recipe_id="mock-recipe-001",
        batch_count=2,
        due_by="2026-10-18T10:00:00Z",
        expected_profit_impact=200,
        decision_score=0.87,
        status="PENDING",
        optimizer_version="mock-v1",
        created_at="2026-10-17T06:00:00Z",
        assessment={
            "days_to_expiry": 3,
            "quantity_at_assessment": 10,
            "predicted_leftover_units": 6,
            "risk_score": 0.72,
            "risk_level": "HIGH",
        },
        lot={
            "lot_id": "mock-lot-002",
            "product_id": "mock-product-002",
            "current_quantity": 10,
            "current_selling_price": 80.0,
            "expiration_date": "2026-10-20",
            "location_aisle": "B1",
            "location_shelf": "S3",
        },
        product={
            "product_id": "mock-product-002",
            "name": "Ripe Bananas",
            "category": "Fresh Produce",
            "unit_of_measure": "kg",
            "regular_price": 80.0,
            "min_allowed_price": 40.0,
        },
        recipe={
            "recipe_id": "mock-recipe-001",
            "name": "Banana Bread",
            "department_id": "mock-dept-001",
            "department_name": "Bakery",
            "output_product_id": "mock-output-001",
            "output_quantity": 2,
            "estimated_prep_time_mins": 45,
            "shelf_life_days": 1,
        },
    ),

    # Case 3: Partner — transfer to a partner, subject to eligibility checks
    OptimizationDecision(
        decision_id="mock-decision-003",
        run_id="mock-run-001",
        assessment_id="mock-assessment-003",
        lot_id="mock-lot-003",
        action_type="DONATION",
        action_quantity=8,
        target_partner_id="mock-partner-001",
        due_by="2026-10-18T09:00:00Z",
        expected_profit_impact=0,
        decision_score=0.78,
        status="PENDING",
        optimizer_version="mock-v1",
        created_at="2026-10-17T06:00:00Z",
        assessment={
            "days_to_expiry": 1,
            "quantity_at_assessment": 8,
            "predicted_leftover_units": 8,
            "risk_score": 0.90,
            "risk_level": "HIGH",
        },
        lot={
            "lot_id": "mock-lot-003",
            "product_id": "mock-product-003",
            "current_quantity": 8,
            "current_selling_price": 30.0,
            "expiration_date": "2026-10-18",
            "location_aisle": "C1",
            "location_shelf": "S1",
        },
        product={
            "product_id": "mock-product-003",
            "name": "Packaged Bread",
            "category": "Bakery",
            "unit_of_measure": "pack",
            "regular_price": 30.0,
            "min_allowed_price": 15.0,
        },
        partner={
            "partner_id": "mock-partner-001",
            "name": "Mock Community Partner",
            "partner_type": "DONATION",
            "pickup_days": [6, 7],
            "pickup_time_start": "09:00",
            "pickup_time_end": "12:00",
            "contact_name": "Mock Contact",
            "contact_phone": "0000000000",
        },
    ),
]


def get_mock_decisions() -> list[OptimizationDecision]:
    """Return fictional decisions for local development."""
    return MOCK_DECISIONS.copy()
