import math
import uuid
from datetime import datetime, time, timedelta

from database import unit_content_grams, unit_weight_kg

METHOD_FLAGS = {
    "DONATION": "allow_donation",
    "ANIMAL_FEED": "allow_animal_feed",
    "COMPOSTING": "allow_composting",
    "ANAEROBIC_DIGESTION": "allow_anaerobic_digestion",
    "LANDFILL": "allow_landfill",
}
DESTROY_METHODS = ("LANDFILL", "ANAEROBIC_DIGESTION", "COMPOSTING")
ACTION_BY_METHOD = {
    "DONATION": "DONATE",
    "ANIMAL_FEED": "ANIMAL_FEED",
    "COMPOSTING": "COMPOST",
    "ANAEROBIC_DIGESTION": "ANAEROBIC_DIGESTION",
    "LANDFILL": "LANDFILL",
}


def cutoff_time(config):
    hour, minute, second = (int(part) for part in config["expiry_cutoff_time"].split(":"))
    return time(hour, minute, second)


def expiry_datetime(lot, config):
    return datetime.combine(lot["expiration_date"], cutoff_time(config))


def days_to_expiry(lot, now):
    return (lot["expiration_date"] - now.date()).days


def hours_left_at(lot, moment, config):
    return (expiry_datetime(lot, config) - moment).total_seconds() / 3600.0


def next_pickup(partner, now, config):
    ready = now + timedelta(minutes=config["lead_time_minutes"])
    for offset in range(0, 9):
        day = ready.date() + timedelta(days=offset)
        if day.isoweekday() not in partner["pickup_days"]:
            continue
        start = datetime.combine(day, partner["pickup_time_start"])
        end = datetime.combine(day, partner["pickup_time_end"])
        if end < ready:
            continue
        return max(start, ready)
    return None


def partner_eligibility(lot, product, partner, pickup, remaining_capacity_kg, config, now):
    reasons = []
    flag = METHOD_FLAGS[partner["partner_type"]]
    if not product.get(flag, False):
        reasons.append("P1_FLAG_" + flag.upper())
    if product["category"] not in partner["accepted_categories"]:
        reasons.append("P2_CATEGORY_NOT_ACCEPTED")
    if not partner["is_active"]:
        reasons.append("P3_PARTNER_INACTIVE")
    if pickup is None:
        reasons.append("P3_NO_PICKUP_SLOT")
    else:
        days_left = (lot["expiration_date"] - pickup.date()).days
        if days_left < partner["min_days_before_expiry"]:
            reasons.append("P4_NOT_IN_TIME_%dD_LEFT_NEED_%d" % (days_left, partner["min_days_before_expiry"]))
        if partner["partner_type"] == "DONATION":
            if days_to_expiry(lot, now) < 0:
                reasons.append("P5_EXPIRED_FOR_HUMAN_USE")
            elif hours_left_at(lot, pickup, config) < config["donation_min_hours_left"]:
                reasons.append("P5_LESS_THAN_%dH_AT_PICKUP" % int(config["donation_min_hours_left"]))
    if remaining_capacity_kg < unit_weight_kg(product) - 1e-9:
        reasons.append("P6_NO_CAPACITY")
    return reasons


def markdown_tiers(lot, product, assessment, forecast, config, now):
    tiers = []
    excluded = {}
    expired = days_to_expiry(lot, now) < 0
    depth_cap = config["markdown_max_depth_by_risk"].get(assessment["risk_level"], 0)
    for entry in sorted(forecast.get("shelf") or [], key=lambda item: item["discount_pct"]):
        discount = entry["discount_pct"]
        reasons = []
        if expired:
            reasons.append("K5_EXPIRED")
        if discount > 0 and not product["allow_markdown"]:
            reasons.append("K1_MARKDOWN_NOT_ALLOWED")
        if discount > 0 and entry["price"] < product["min_allowed_price"] - 1e-9:
            reasons.append("K2_BELOW_MIN_PRICE")
        if discount > depth_cap:
            reasons.append("K4_RISK_DEPTH_%s" % assessment["risk_level"])
        if entry.get("expected_qty") is None:
            reasons.append("K3_NO_DEMAND_CURVE")
        if reasons:
            excluded["MARKDOWN:%d" % discount] = reasons
        else:
            tiers.append(dict(entry))
    return tiers, excluded


def upcycle_supplier_reasons(lot, product, now):
    reasons = []
    if not product["allow_upcycling"]:
        reasons.append("U1_UPCYCLING_NOT_ALLOWED")
    if days_to_expiry(lot, now) < 0:
        reasons.append("U4_EXPIRED")
    return reasons


def recipe_eligibility(recipe, ingredients, lot_pairs, kitchen_row, demand, now):
    reasons = []
    if not recipe["is_active"]:
        reasons.append("U0_RECIPE_INACTIVE")
    if demand <= 0:
        reasons.append("U5_NO_MENU_DEMAND")
    hours_needed = recipe["estimated_prep_time_mins"] / 60.0
    if kitchen_row is None:
        reasons.append("U3_NO_CAPACITY_ROW")
    elif kitchen_row["workload_status"] == "FULL":
        reasons.append("U3_KITCHEN_FULL")
    elif kitchen_row["remaining_hrs"] < hours_needed - 1e-9:
        reasons.append("U3_NOT_ENOUGH_HOURS")
    suppliers = {}
    for ingredient in ingredients:
        product_id = ingredient["product_id"]
        if product_id is None:
            continue
        for lot, product in lot_pairs:
            if product["product_id"] == product_id and not upcycle_supplier_reasons(lot, product, now):
                suppliers.setdefault(product_id, []).append(lot["lot_id"])
        if ingredient["is_primary_ingredient"] and product_id not in suppliers:
            reasons.append("U2_PRIMARY_MISSING_" + product_id)
    return reasons, suppliers


def _hard(rule, detail):
    return {"rule": rule, "detail": detail}


def _partner_hard_checks(portion, lot, product, db, now, config, partner_totals):
    failures = []
    details = portion["details"]
    partner = db.get_partner(details["partner_id"])
    pickup = next_pickup(partner, now, config)
    reasons = partner_eligibility(lot, product, partner, pickup, partner["max_capacity_kg_per_pickup"], config, now)
    for reason in reasons:
        if reason.startswith("P1") or reason.startswith("P2"):
            failures.append(_hard("H3_FLAG_OR_CATEGORY", reason))
        elif reason.startswith("P3") or reason.startswith("P4"):
            failures.append(_hard("H4_PARTNER_NOT_READY", reason))
        elif reason.startswith("P5"):
            rule = "H1_EXPIRED" if "EXPIRED" in reason else "H2_DONATION_MIN_HOURS"
            failures.append(_hard(rule, reason))
    if pickup is not None:
        booked = db.booked_kg_at_slot(partner["partner_id"], pickup.date())
        total = partner_totals.get(partner["partner_id"], 0.0) + booked
        if total > partner["max_capacity_kg_per_pickup"] + 1e-6:
            failures.append(_hard("H5_PARTNER_CAPACITY", "%.2f kg > %.2f kg" % (total, partner["max_capacity_kg_per_pickup"])))
    return failures


def _upcycle_hard_checks(portion, lot, product, db, now, kitchen, recipe_entries):
    failures = []
    details = portion["details"]
    recipe = db.get_recipe(details["recipe_id"])
    if days_to_expiry(lot, now) < 0:
        failures.append(_hard("H1_EXPIRED", "expired lot sent to kitchen"))
    if not product["allow_upcycling"]:
        failures.append(_hard("H3_FLAG_OR_CATEGORY", "allow_upcycling is FALSE"))
    if not recipe["is_active"]:
        failures.append(_hard("H6_KITCHEN", "recipe inactive"))
    row = db.kitchen_daily(recipe["department_id"], now.date())
    if row is None or row["workload_status"] == "FULL":
        failures.append(_hard("H6_KITCHEN", "department unavailable"))
    elif kitchen[recipe["department_id"]]["hours_used"] > row["remaining_hrs"] + 1e-6:
        failures.append(_hard("H6_KITCHEN", "hours %.2f > remaining %.2f" % (kitchen[recipe["department_id"]]["hours_used"], row["remaining_hrs"])))
    entry = recipe_entries.get(details["recipe_id"])
    if entry is not None:
        if entry["portions"] > entry["demand_cap"] + 1e-6:
            failures.append(_hard("H6_KITCHEN", "portions %d > demand %d" % (entry["portions"], entry["demand_cap"])))
        for line in entry["coverage"]:
            if line["is_primary"] and line["purchased_g"] > 1e-6:
                failures.append(_hard("H6_KITCHEN", "primary ingredient purchased: " + line["product_id"]))
            if line["supplied_g"] + line["purchased_g"] < line["needed_g"] - 1e-6:
                failures.append(_hard("H6_KITCHEN", "ingredient shortfall: " + line["product_id"]))
    return failures


def _markdown_hard_checks(portion, lot, product, now):
    failures = []
    if days_to_expiry(lot, now) < 0:
        failures.append(_hard("H1_EXPIRED", "expired lot on shelf"))
    if portion["kind"] == "MARKDOWN_DISCOUNTED":
        if not product["allow_markdown"]:
            failures.append(_hard("H3_FLAG_OR_CATEGORY", "allow_markdown is FALSE"))
        for tier in portion["details"]["tiers"]:
            if tier["unit_price"] < product["min_allowed_price"] - 1e-9:
                failures.append(_hard("H3_FLAG_OR_CATEGORY", "price %.2f below min %.2f" % (tier["unit_price"], product["min_allowed_price"])))
    return failures


def _soft_checks(portion, plan, db, config, trips, kitchen, recipe_entries):
    limits = config["guardrails"]
    flags = []
    warnings = []
    solver = plan["solver"]
    if solver["status"] != "optimal" or (solver["gap"] is not None and solver["gap"] > limits["solver_gap_cap"]):
        flags.append({"rule": "A5_SOLVER_QUALITY", "detail": "status %s gap %s" % (solver["status"], solver["gap"])})
    if db.executed_decisions(portion["lot_id"]):
        flags.append({"rule": "A7_PLAN_CHANGE", "detail": "lot has executed decisions"})
    kind = portion["kind"]
    details = portion["details"]
    if kind == "MARKDOWN_DISCOUNTED":
        if details["discount_value_thb"] > limits["markdown_discount_cap_thb"]:
            flags.append({"rule": "A1_DISCOUNT_TOTAL",
                          "detail": "%.2f > %.2f" % (details["discount_value_thb"], limits["markdown_discount_cap_thb"])})
        worst = max(tier["band_ratio"] for tier in details["tiers"])
        if worst > limits["forecast_band_cap"]:
            flags.append({"rule": "A6_FORECAST_UNCERTAINTY", "detail": "band %.2f" % worst})
    if kind == "UNRESOLVED":
        flags.append({"rule": "A2_UNRESOLVED", "detail": "%d units without route" % portion["units"]})
    if kind == "PARTNER":
        trip = trips[details["partner_id"]]
        if portion["action"] in DESTROY_METHODS and portion["inventory_cost_thb"] > limits["destroy_value_cap_thb"]:
            flags.append({"rule": "A3_VALUE_DESTROYED",
                          "detail": "%.2f > %.2f" % (portion["inventory_cost_thb"], limits["destroy_value_cap_thb"])})
        if trip["total_cost_thb"] > limits["trip_cost_cap_thb"] or trip["cost_per_kg_thb"] > limits["trip_cost_per_kg_cap_thb"]:
            flags.append({"rule": "A4_TRIP_COST",
                          "detail": "%.2f thb, %.2f thb/kg" % (trip["total_cost_thb"], trip["cost_per_kg_thb"])})
    if kind == "UPCYCLE":
        department = db.get_recipe(details["recipe_id"])["department_id"]
        entry = kitchen[department]
        if entry["utilization"] >= limits["kitchen_utilization_warning"]:
            warnings.append({"rule": "W1_KITCHEN_NEAR_FULL", "detail": "%s %.0f%%" % (department, entry["utilization"] * 100)})
    return flags, warnings


def evaluate_plan(plan, db, now, baseline_fingerprint):
    config = db.optimizer_config
    fresh = db.fingerprint()
    trips = {trip["partner_id"]: trip for trip in plan["trips"]}
    kitchen = {entry["department_id"]: entry for entry in plan["kitchen"]}
    recipe_entries = {recipe["recipe_id"]: recipe for entry in plan["kitchen"] for recipe in entry["recipes"]}
    partner_totals = {pid: trip["kg"] for pid, trip in trips.items()}
    verdicts = []
    for lot_entry in plan["lots"]:
        lot = db.get_lot(lot_entry["lot_id"])
        product = db.get_product(lot["product_id"])
        shared_failures = []
        units = [portion["units"] for portion in lot_entry["plan"]]
        if sum(units) != lot["current_quantity"] or any(u < 0 or int(u) != u for u in units):
            shared_failures.append(_hard("H7_MASS_BALANCE", "%s units vs %s in stock" % (sum(units), lot["current_quantity"])))
        if baseline_fingerprint["lots"].get(lot["lot_id"]) != fresh["lots"].get(lot["lot_id"]):
            shared_failures.append(_hard("H8_STALE_SNAPSHOT", "lot quantity or price changed since the optimizer snapshot"))
        for portion in lot_entry["plan"]:
            failures = list(shared_failures)
            kind = portion["kind"]
            if kind in ("MARKDOWN_REGULAR", "MARKDOWN_DISCOUNTED"):
                failures += _markdown_hard_checks(portion, lot, product, now)
            elif kind == "UPCYCLE":
                failures += _upcycle_hard_checks(portion, lot, product, db, now, kitchen, recipe_entries)
            elif kind == "PARTNER":
                failures += _partner_hard_checks(portion, lot, product, db, now, config, partner_totals)
            flags, warnings = _soft_checks(portion, plan, db, config, trips, kitchen, recipe_entries)
            if failures:
                status = "BLOCKED"
            elif flags:
                status = "PENDING_APPROVAL"
            else:
                status = "AUTO"
            verdicts.append({
                "lot_id": lot["lot_id"],
                "portion_no": portion["portion_no"],
                "kind": kind,
                "action": portion["action"],
                "status": status,
                "hard_failures": failures,
                "soft_flags": flags,
                "warnings": warnings,
            })
    return verdicts


def exclusions_from_blocked(plan, verdicts):
    lookup = {(lot["lot_id"], portion["portion_no"]): portion for lot in plan["lots"] for portion in lot["plan"]}
    exclusions = set()
    for verdict in verdicts:
        if verdict["status"] != "BLOCKED":
            continue
        portion = lookup[(verdict["lot_id"], verdict["portion_no"])]
        if portion["kind"] == "PARTNER":
            exclusions.add(("PARTNER", verdict["lot_id"], portion["details"]["partner_id"]))
        elif portion["kind"] == "UPCYCLE":
            exclusions.add(("UPCYCLE", verdict["lot_id"], portion["details"]["recipe_id"]))
        elif portion["kind"] == "MARKDOWN_DISCOUNTED":
            for tier in portion["details"]["tiers"]:
                exclusions.add(("MARKDOWN", verdict["lot_id"], tier["discount_pct"]))
    return exclusions


def build_decision_records(plan, verdicts, run_id, snapshot_version, model_version):
    lookup = {(lot["lot_id"], portion["portion_no"]): (lot, portion) for lot in plan["lots"] for portion in lot["plan"]}
    rows = []
    for verdict in verdicts:
        lot, portion = lookup[(verdict["lot_id"], verdict["portion_no"])]
        action_type = {
            "MARKDOWN_REGULAR": "MARKDOWN",
            "MARKDOWN_DISCOUNTED": "MARKDOWN",
            "UPCYCLE": "KITCHEN_REPURPOSE",
            "UNRESOLVED": "DISCARD",
        }.get(portion["kind"]) or ACTION_BY_METHOD[portion["action"]]
        rows.append({
            "decision_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "%s|%s|%s" % (run_id, lot["lot_id"], portion["portion_no"]))),
            "run_id": run_id,
            "lot_id": lot["lot_id"],
            "portion_no": portion["portion_no"],
            "action_type": action_type,
            "units": portion["units"],
            "share_pct": portion["share_pct"],
            "weight_kg": portion["kg"],
            "net_value_thb": portion["net_thb"],
            "cost_breakdown": portion["details"],
            "score_factors": {"excluded": lot["explain"]["excluded"], "binding": lot["explain"]["binding"],
                              "alt_cost_per_kg": lot["explain"]["alt_cost_per_kg"]},
            "guardrail_results": {"hard": verdict["hard_failures"], "soft": verdict["soft_flags"], "warnings": verdict["warnings"]},
            "status": verdict["status"],
            "execution_state": "NOT_STARTED",
            "model_version": model_version,
            "snapshot_version": snapshot_version,
        })
    return rows


def build_approval_queue(records, plan, db, now):
    config = db.optimizer_config
    buffer_hours = config["guardrails"]["approval_deadline_buffer_hours"]
    lead = timedelta(minutes=config["lead_time_minutes"])
    lookup = {(lot["lot_id"], portion["portion_no"]): portion for lot in plan["lots"] for portion in lot["plan"]}
    rows = []
    for record in records:
        if record["status"] != "PENDING_APPROVAL":
            continue
        portion = lookup[(record["lot_id"], record["portion_no"])]
        lot = db.get_lot(record["lot_id"])
        deadline = expiry_datetime(lot, config) - timedelta(hours=buffer_hours)
        if portion["kind"] == "PARTNER":
            deadline = min(deadline, datetime.fromisoformat(portion["details"]["pickup_dt"]) - lead)
        value = portion["inventory_cost_thb"] if portion["kind"] == "UNRESOLVED" else portion["net_thb"]
        rows.append({
            "approval_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "approval|" + record["decision_id"])),
            "decision_id": record["decision_id"],
            "lot_id": record["lot_id"],
            "reason_codes": [flag["rule"] for flag in record["guardrail_results"]["soft"]],
            "value_at_stake_thb": round(value, 2),
            "deadline_at": max(deadline, now),
            "state": "OPEN",
            "decision": None,
            "comment": None,
        })
    return rows