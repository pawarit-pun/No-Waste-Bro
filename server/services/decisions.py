from collections import defaultdict
from datetime import date
from typing import Optional

from fastapi import HTTPException
from postgrest.exceptions import APIError

from core.dates import today_bkk
from db.helpers import fetch_by_ids
from db.supabase import supabase
from schemas.decision import DecisionCreate
from schemas.enums import ActionType, DecisionStatus

STATUS_VIEW = "optimization_decisions_status"


def _fail(i: int, msg: str):
    raise HTTPException(422, f"decisions[{i}]: {msg}")


def create_decisions(decisions: list[DecisionCreate], optimizer_version: Optional[str]) -> dict:
    """ตรวจผลของ Optimizer กับข้อมูลจริงใน DB แล้วบันทึก (ทั้งหมดหรือไม่บันทึกเลย)"""
    assessments = fetch_by_ids("lot_risk_assessments", "assessment_id",
                               {d.assessment_id for d in decisions}, "assessment_id, run_id, lot_id")
    lots = fetch_by_ids("inventory_lots", "lot_id", {a["lot_id"] for a in assessments.values()},
                        "lot_id, product_id, current_quantity, current_selling_price, expiration_date")
    products = fetch_by_ids("products", "product_id", {l["product_id"] for l in lots.values()},
                            "product_id, category, min_allowed_price, "
                            "allow_markdown, allow_kitchen_repurposing, allow_donation")
    recipes = fetch_by_ids("recipes", "recipe_id", {d.target_recipe_id for d in decisions},
                           "recipe_id, is_active, ingredients:recipe_ingredients(ingredient_product_id)")
    partners = fetch_by_ids("donation_partners", "partner_id", {d.target_partner_id for d in decisions},
                            "partner_id, is_active, accepted_categories, min_days_before_expiry")
    today = today_bkk()

    rows = []
    qty_per_lot: dict[str, int] = defaultdict(int)
    for i, d in enumerate(decisions):
        assessment = assessments.get(str(d.assessment_id))
        if assessment is None:
            _fail(i, f"assessment_id '{d.assessment_id}' not found")
        lot = lots[assessment["lot_id"]]
        product = products[lot["product_id"]]

        qty_per_lot[lot["lot_id"]] += d.action_quantity
        if qty_per_lot[lot["lot_id"]] > lot["current_quantity"]:
            _fail(i, f"total action_quantity for lot '{lot['lot_id']}' exceeds current_quantity "
                     f"({lot['current_quantity']})")

        new_price = d.new_recommended_price
        if d.action_type == ActionType.MARKDOWN:
            if not product["allow_markdown"]:
                _fail(i, f"product '{product['product_id']}' does not allow markdown")
            if new_price is None:
                new_price = round(lot["current_selling_price"] * (1 - d.discount_pct / 100), 2)
            min_price = product["min_allowed_price"]
            if min_price is not None and new_price < min_price:
                _fail(i, f"new price {new_price} is below min_allowed_price {min_price}")

        elif d.action_type == ActionType.KITCHEN_REPURPOSE:
            if not product["allow_kitchen_repurposing"]:
                _fail(i, f"product '{product['product_id']}' does not allow kitchen repurposing")
            recipe = recipes.get(d.target_recipe_id)
            if recipe is None or not recipe["is_active"]:
                _fail(i, f"recipe '{d.target_recipe_id}' not found or inactive")
            if product["product_id"] not in {x["ingredient_product_id"] for x in recipe["ingredients"]}:
                _fail(i, f"product '{product['product_id']}' is not an ingredient of recipe '{d.target_recipe_id}'")

        elif d.action_type == ActionType.DONATE:
            if not product["allow_donation"]:
                _fail(i, f"product '{product['product_id']}' does not allow donation")
            partner = partners.get(d.target_partner_id)
            if partner is None or not partner["is_active"]:
                _fail(i, f"donation partner '{d.target_partner_id}' not found or inactive")
            if product["category"] not in partner["accepted_categories"]:
                _fail(i, f"partner '{d.target_partner_id}' does not accept category {product['category']}")
            days_left = (date.fromisoformat(lot["expiration_date"]) - today).days
            if days_left < partner["min_days_before_expiry"]:
                _fail(i, f"lot expires in {days_left} day(s), partner requires at least "
                         f"{partner['min_days_before_expiry']}")

        row = d.model_dump(mode="json", exclude_none=True)
        row.update(run_id=assessment["run_id"], lot_id=lot["lot_id"])
        if new_price is not None:
            row["new_recommended_price"] = new_price
        if optimizer_version:
            row["optimizer_version"] = optimizer_version
        rows.append(row)

    try:
        res = supabase.table("optimization_decisions").insert(rows).execute()
    except APIError as e:
        raise HTTPException(400, f"Failed to save decisions: {e.message}")

    return {
        "created": len(res.data),
        "decisions": [
            {k: r[k] for k in ("decision_id", "run_id", "assessment_id", "lot_id", "action_type")}
            for r in res.data
        ],
    }


def list_decisions(run_id: Optional[str], status: Optional[DecisionStatus]) -> dict:
    """decision ของ run พร้อม context ที่ LLM ใช้เขียนคำสั่งงาน"""
    if run_id is None:
        latest = (supabase.table("optimization_decisions").select("run_id")
                    .order("created_at", desc=True).limit(1).execute())
        if not latest.data:
            return {"run_id": None, "decisions": []}
        run_id = latest.data[0]["run_id"]

    query = supabase.table(STATUS_VIEW).select("*").eq("run_id", str(run_id))
    if status is not None:
        query = query.eq("status", status.value)
    decisions = query.order("created_at").execute().data

    assessments = fetch_by_ids("lot_risk_assessments", "assessment_id",
                               {d["assessment_id"] for d in decisions},
                               "assessment_id, days_to_expiry, quantity_at_assessment, "
                               "predicted_leftover_units, risk_score, risk_level")
    lots = fetch_by_ids("inventory_lots", "lot_id", {d["lot_id"] for d in decisions},
                        "lot_id, product_id, current_quantity, current_selling_price, "
                        "expiration_date, location_aisle, location_shelf")
    products = fetch_by_ids("products", "product_id", {l["product_id"] for l in lots.values()},
                            "product_id, name, category, unit_of_measure, regular_price, min_allowed_price")
    recipes = fetch_by_ids("recipes", "recipe_id", {d.get("target_recipe_id") for d in decisions},
                           "recipe_id, name, department_id, output_product_id, output_quantity, "
                           "estimated_prep_time_mins, shelf_life_days")
    partners = fetch_by_ids("donation_partners", "partner_id", {d.get("target_partner_id") for d in decisions},
                            "partner_id, name, partner_type, pickup_days, pickup_time_start, "
                            "pickup_time_end, requires_cold_chain, contact_name, contact_phone")

    for d in decisions:
        lot = lots.get(d["lot_id"])
        d["assessment"] = assessments.get(d["assessment_id"])
        d["lot"] = lot
        d["product"] = products.get(lot["product_id"]) if lot else None
        d["recipe"] = recipes.get(d.get("target_recipe_id"))
        d["partner"] = partners.get(d.get("target_partner_id"))

    return {"run_id": str(run_id), "decisions": decisions}
