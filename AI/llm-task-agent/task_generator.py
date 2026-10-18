from models import (
    OptimizationDecision,
    TaskCreate,
    TaskBatchCreate,
)


def calculate_priority(decision: OptimizationDecision) -> int:
    """Calculate task priority from expiry and risk information."""

    assessment = decision.assessment
    risk_level = str(assessment.get("risk_level", "")).upper()
    risk_score = float(assessment.get("risk_score", 0))
    days_to_expiry = assessment.get("days_to_expiry")

    # Priority 1 is the most urgent; priority 5 is the least urgent.
    if days_to_expiry is not None and days_to_expiry <= 1:
        return 1

    if risk_level == "HIGH" or risk_score >= 0.8:
        return 2

    if days_to_expiry is not None and days_to_expiry <= 3:
        return 2

    if risk_level == "MEDIUM" or risk_score >= 0.5:
        return 3

    return 4


def generate_reasoning(decision: OptimizationDecision) -> str:
    """Generate an initial explanation without calling an LLM."""

    assessment = decision.assessment
    product_name = decision.product.get("name", "Unknown product")
    action_type = decision.action_type.upper()
    days_to_expiry = assessment.get("days_to_expiry")
    predicted_leftover = assessment.get("predicted_leftover_units")
    risk_level = assessment.get("risk_level", "UNKNOWN")

    reasons = [
        f"Recommended action: {action_type} for {product_name}.",
        f"Current risk level: {risk_level}.",
    ]

    if days_to_expiry is not None:
        reasons.append(f"Days to expiry: {days_to_expiry}.")

    if predicted_leftover is not None:
        reasons.append(
            f"Predicted leftover quantity: {predicted_leftover} units."
        )

    if decision.expected_profit_impact is not None:
        reasons.append(
            "Expected profit impact: "
            f"{decision.expected_profit_impact}."
        )

    return " ".join(reasons)


def generate_instructions(decision: OptimizationDecision) -> str:
    """Generate staff instructions according to the decision type."""

    action_type = decision.action_type.upper()
    product_name = decision.product.get("name", "Unknown product")
    quantity = decision.action_quantity

    if action_type == "MARKDOWN":
        price = decision.new_recommended_price
        discount = decision.discount_pct

        return (
            f"Locate {product_name} and verify the affected stock. "
            f"Prepare {quantity:g} units for markdown. "
            f"Recommended discount: {discount:g}%. "
            f"Recommended selling price: "
            f"{price:.2f} per unit. "
            "Verify the approved price and update the shelf label "
            "and selling system according to store procedures."
            if price is not None
            else
            f"Locate {product_name}, verify {quantity:g} units, "
            f"and prepare them for a {discount:g}% markdown. "
            "Confirm the approved selling price before updating "
            "the shelf label and selling system."
        )

    if action_type == "PROCESSING":
        recipe = decision.recipe
        recipe_name = recipe.get("name", "the recommended recipe")
        batch_count = decision.batch_count
        prep_time = recipe.get("estimated_prep_time_mins")

        instructions = (
            f"Locate {product_name} and verify {quantity:g} units "
            f"for processing using {recipe_name}. "
            f"Planned batches: {batch_count}. "
            "Confirm ingredient condition, recipe requirements, "
            "and kitchen capacity before starting."
        )

        if prep_time is not None:
            instructions += (
                f" Estimated preparation time: {prep_time} minutes."
            )

        instructions += (
            " Follow the approved food-safety and kitchen procedures."
        )
        return instructions

    if action_type == "DONATION":
        partner_name = decision.partner.get(
            "name", "the designated donation partner"
        )

        return (
            f"Locate {product_name} and verify {quantity:g} units "
            f"for donation to {partner_name}. "
            "Check product condition, expiry, donation eligibility, "
            "and the partner's confirmed pickup schedule. "
            "Record the handover according to store procedures."
        )

    return (
        f"Review decision {decision.decision_id} for {product_name}. "
        f"Verify the recommended quantity of {quantity:g} units "
        f"and confirm the appropriate procedure for "
        f"action type {action_type} before execution."
    )


def generate_task(decision: OptimizationDecision) -> TaskCreate:
    """Convert one optimization decision into one staff task."""

    return TaskCreate(
        decision_id=decision.decision_id,
        priority=calculate_priority(decision),
        ai_reasoning=generate_reasoning(decision),
        staff_instructions=generate_instructions(decision),
    )


def generate_tasks(
    decisions: list[OptimizationDecision],
) -> TaskBatchCreate:
    """Convert multiple decisions into a validated task batch."""

    tasks = [generate_task(decision) for decision in decisions]

    return TaskBatchCreate(tasks=tasks)
