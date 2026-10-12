import math
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

import rules
from database import fingerprint_hash, unit_content_grams, unit_weight_kg


class ModelBuilder:
    def __init__(self):
        self.lower = []
        self.upper = []
        self.integer = []
        self.profit = []
        self.rows = []

    def add_var(self, lower=0.0, upper=np.inf, integer=False, profit=0.0):
        self.lower.append(lower)
        self.upper.append(upper)
        self.integer.append(1 if integer else 0)
        self.profit.append(profit)
        return len(self.profit) - 1

    def add_constraint(self, coefficients, lower=-np.inf, upper=np.inf):
        self.rows.append((coefficients, lower, upper))

    def solve(self, time_limit, mip_gap):
        matrix = lil_matrix((len(self.rows), len(self.profit)))
        lows = []
        highs = []
        for index, (coefficients, low, high) in enumerate(self.rows):
            for column, value in coefficients.items():
                matrix[index, column] = value
            lows.append(low)
            highs.append(high)
        return milp(
            c=-np.array(self.profit),
            constraints=LinearConstraint(matrix.tocsr(), lows, highs),
            integrality=np.array(self.integer),
            bounds=Bounds(self.lower, self.upper),
            options={"time_limit": time_limit, "mip_rel_gap": mip_gap},
        )


class RunOptimizer:
    model_version = "optimizer_v1"

    def __init__(self, db, now):
        self.db = db
        self.now = now
        self.config = db.optimizer_config

    def run(self, run_id, forecasts, exclusions=None, include_baselines=True):
        started = time.perf_counter()
        exclusions = set(exclusions or [])
        fingerprint = self.db.fingerprint()
        self.db.lock_lots(run_id, [forecast["lot_id"] for forecast in forecasts])
        context = self._prepare(run_id, forecasts, exclusions)
        solution = self._solve(context["lots"], context["recipes"], context["partners"], dict(context["hours"]))
        report = self._report(solution)
        plan = {
            "run_id": run_id,
            "solved_at": self.now.isoformat(),
            "model_version": self.model_version,
            "snapshot_version": fingerprint_hash(fingerprint),
            "snapshot_fingerprint": fingerprint,
            "solver": {
                "name": "HiGHS",
                "status": solution["status"],
                "gap": solution["gap"],
                "time_ms": int((time.perf_counter() - started) * 1000),
            },
            "skipped": context["skipped"],
            "exclusions_applied": sorted([list(item) for item in exclusions], key=str),
            "lots": report["lots"],
            "trips": list(report["trips"].values()),
            "kitchen": report["kitchen"],
            "run_summary": {
                "lots": len(report["lots"]),
                "inventory_cost_thb": round(report["inventory_cost"], 2),
                "net_recovery_thb": round(report["net_recovery"], 2),
                "net_vs_cost_thb": round(report["net_recovery"] - report["inventory_cost"], 2),
                "unresolved_units": report["unresolved_units"],
                "reconciliation_gap_thb": round(report["reconciliation_gap"], 6),
            },
        }
        self._attach_hour_values(plan, context, solution)
        if include_baselines:
            plan["baselines"] = self._baselines(context, report)
        return plan

    def _prepare(self, run_id, forecasts, exclusions):
        skipped = []
        lots = []
        for forecast in forecasts:
            lot = self.db.get_lot(forecast["lot_id"])
            if lot["locked_by"] != run_id:
                skipped.append({"lot_id": lot["lot_id"], "reason": "LOT_NOT_AVAILABLE"})
                continue
            if forecast["quantity"] != lot["current_quantity"]:
                skipped.append({"lot_id": lot["lot_id"], "reason": "FORECAST_STALE"})
                continue
            lots.append(self._lot_context(forecast, lot, exclusions))
        partners = self._partner_contexts()
        for lot_context in lots:
            self._attach_partner_options(lot_context, partners, exclusions)
        recipes, hours = self._recipe_contexts(lots, exclusions)
        return {"lots": lots, "partners": partners, "recipes": recipes, "hours": hours, "skipped": skipped}

    def _lot_context(self, forecast, lot, exclusions):
        product = self.db.get_product(lot["product_id"])
        assessment = self.db.get_assessment(forecast["assessment_id"])
        tiers, excluded = rules.markdown_tiers(lot, product, assessment, forecast, self.config, self.now)
        kept = []
        for tier in tiers:
            if ("MARKDOWN", lot["lot_id"], tier["discount_pct"]) in exclusions:
                excluded["MARKDOWN:%d" % tier["discount_pct"]] = ["X_EXCLUDED_BY_GUARDRAILS"]
            else:
                kept.append(tier)
        previous = 0
        quantity = lot["current_quantity"]
        for tier in kept:
            expected = tier["expected_qty"]
            cap = expected - self.config["kappa"] * (expected - tier["low"])
            cap = int(min(quantity, max(previous, math.floor(cap + 1e-9))))
            tier["cap"] = cap
            tier["band_ratio"] = (tier["high"] - tier["low"]) / expected if expected > 0 else 0.0
            previous = cap
        return {
            "lot_id": lot["lot_id"],
            "product_id": product["product_id"],
            "name": product["name"],
            "category": product["category"],
            "unit": product["unit_of_measure"],
            "quantity": quantity,
            "unit_cost": lot["unit_cost"],
            "regular_price": product["regular_price"],
            "min_allowed_price": product["min_allowed_price"],
            "weight_kg": unit_weight_kg(product),
            "content_g": unit_content_grams(product),
            "risk_level": assessment["risk_level"],
            "risk_score": assessment["risk_score"],
            "days_to_expiry": rules.days_to_expiry(lot, self.now),
            "tiers": kept,
            "partner_ok": [],
            "excluded": excluded,
            "forecast": forecast,
            "lot": lot,
            "product": product,
        }

    def _partner_contexts(self):
        contexts = {}
        for partner_id, partner in self.db.donation_partners.items():
            pickup = rules.next_pickup(partner, self.now, self.config)
            booked = self.db.booked_kg_at_slot(partner_id, pickup.date()) if pickup else 0.0
            context = dict(partner)
            context.update({
                "pickup": pickup,
                "booked_kg": booked,
                "capacity_remaining_kg": max(0.0, partner["max_capacity_kg_per_pickup"] - booked),
                "trip_cost": partner["fixed_cost_per_trip"] + partner["distance_km"] * self.config["variable_cost_per_km"],
                "trip_sunk": booked > 0,
            })
            contexts[partner_id] = context
        return contexts

    def _attach_partner_options(self, lot_context, partners, exclusions):
        for partner_id, partner in partners.items():
            reasons = rules.partner_eligibility(
                lot_context["lot"], lot_context["product"], partner, partner["pickup"],
                partner["capacity_remaining_kg"], self.config, self.now)
            if ("PARTNER", lot_context["lot_id"], partner_id) in exclusions:
                reasons.append("X_EXCLUDED_BY_GUARDRAILS")
            if reasons:
                lot_context["excluded"][partner["partner_type"]] = reasons
            else:
                lot_context["partner_ok"].append(partner_id)

    def _recipe_contexts(self, lots, exclusions):
        named = {}
        for lot_context in lots:
            kitchen = lot_context["forecast"].get("kitchen")
            if kitchen:
                named.setdefault(kitchen["recipe_id"], []).append(lot_context)
        pairs = [(lot_context["lot"], lot_context["product"]) for lot_context in lots]
        recipes = {}
        hours = {}
        for recipe_id, named_lots in named.items():
            recipe = self.db.get_recipe(recipe_id)
            ingredients = []
            for row in self.db.ingredients_of(recipe_id):
                product = self.db.get_product(row["product_id"]) if row["product_id"] else None
                multiplier = 1000.0 if row["unit"] in ("KG", "L") else 1.0
                content = unit_content_grams(product) if product else None
                ingredients.append({
                    "name": row["ingredient_name"],
                    "product_id": row["product_id"],
                    "is_primary": row["is_primary_ingredient"],
                    "need_g": row["required_quantity"] * multiplier,
                    "content_g": content,
                    "cost_per_gram": (product["base_cost"] / content) if product else 0.0,
                })
            demand = max(lot_context["forecast"]["kitchen"]["menu_qty"] for lot_context in named_lots)
            row = self.db.kitchen_daily(recipe["department_id"], self.now.date())
            reasons, suppliers = rules.recipe_eligibility(recipe, self.db.ingredients_of(recipe_id), pairs, row, demand, self.now)
            for product_id in list(suppliers):
                suppliers[product_id] = [lot_id for lot_id in suppliers[product_id]
                                         if ("UPCYCLE", lot_id, recipe_id) not in exclusions]
            for ingredient in ingredients:
                if ingredient["is_primary"] and ingredient["product_id"] and not suppliers.get(ingredient["product_id"]):
                    if not any(reason.startswith("U2_") for reason in reasons):
                        reasons.append("U2_PRIMARY_MISSING_" + ingredient["product_id"])
            for lot_context in named_lots:
                if reasons:
                    lot_context["excluded"]["UPCYCLE:" + recipe_id] = reasons
            department = recipe["department_id"]
            hours[department] = 0.0 if row is None or row["workload_status"] == "FULL" else row["remaining_hrs"]
            output_price = self.db.get_product(recipe["output_product_id"])["regular_price"]
            recipes[recipe_id] = {
                "recipe_id": recipe_id,
                "name": recipe["name"],
                "department_id": department,
                "minutes": recipe["estimated_prep_time_mins"],
                "hours_per_batch": recipe["estimated_prep_time_mins"] / 60.0,
                "yield": recipe["output_quantity"],
                "output_price": output_price,
                "demand_cap": demand,
                "ingredients": ingredients,
                "suppliers": suppliers,
                "eligible": not reasons,
                "reasons": reasons,
            }
        return recipes, hours

    def _batch_profit(self, recipe):
        electricity = recipe["hours_per_batch"] * self.config["electricity_cost_per_hour"]
        labor = recipe["minutes"] * self.config["labor_cost_per_minute"]
        return recipe["yield"] * recipe["output_price"] - electricity - labor

    def _active_recipes(self, lots_by_id, recipes, hours):
        active = {}
        for recipe_id, recipe in recipes.items():
            if not recipe["eligible"]:
                continue
            if hours.get(recipe["department_id"], 0.0) < recipe["hours_per_batch"] - 1e-9:
                continue
            complete = True
            for ingredient in recipe["ingredients"]:
                if ingredient["is_primary"] and ingredient["product_id"] is not None:
                    present = [lot_id for lot_id in recipe["suppliers"].get(ingredient["product_id"], []) if lot_id in lots_by_id]
                    if not present:
                        complete = False
            if complete:
                active[recipe_id] = recipe
        return active

    def _solve(self, lots, recipes, partners, hours, mip_gap=None):
        started = time.perf_counter()
        builder = ModelBuilder()
        variables = {}
        lots_by_id = {lot["lot_id"]: lot for lot in lots}
        for lot in lots:
            lot_id = lot["lot_id"]
            quantity = lot["quantity"]
            for tier in lot["tiers"]:
                variables[("s", lot_id, tier["discount_pct"])] = builder.add_var(
                    upper=quantity, integer=True, profit=tier["price"])
            for partner_id in lot["partner_ok"]:
                partner = partners[partner_id]
                profit = -partner["handling_fee_per_kg"] * lot["weight_kg"]
                if partner["partner_type"] == "DONATION":
                    profit += self.config["donation_tax_rate"] * lot["unit_cost"]
                upper = min(quantity, int(math.floor(partner["capacity_remaining_kg"] / lot["weight_kg"] + 1e-9)))
                variables[("x", lot_id, partner_id)] = builder.add_var(upper=upper, integer=True, profit=profit)
            variables[("r", lot_id)] = builder.add_var(
                upper=quantity, integer=True, profit=-self.config["big_m_per_unit"])
        active = self._active_recipes(lots_by_id, recipes, hours)
        for recipe_id, recipe in active.items():
            batch_cap = min(
                int(math.floor(recipe["demand_cap"] / recipe["yield"] + 1e-9)),
                int(math.floor(hours[recipe["department_id"]] / recipe["hours_per_batch"] + 1e-9)),
            )
            batches = builder.add_var(upper=batch_cap, integer=True, profit=self._batch_profit(recipe))
            variables[("n", recipe_id)] = batches
            for ingredient in recipe["ingredients"]:
                product_id = ingredient["product_id"]
                if product_id is None:
                    continue
                coverage = {}
                supply = {}
                for lot_id in recipe["suppliers"].get(product_id, []):
                    if lot_id not in lots_by_id:
                        continue
                    key = ("u", lot_id, recipe_id)
                    if key not in variables:
                        variables[key] = builder.add_var(upper=lots_by_id[lot_id]["quantity"], integer=True)
                    coverage[variables[key]] = lots_by_id[lot_id]["content_g"]
                    supply[variables[key]] = lots_by_id[lot_id]["content_g"]
                if not ingredient["is_primary"]:
                    purchase = builder.add_var(profit=-ingredient["cost_per_gram"])
                    variables[("b", recipe_id, product_id)] = purchase
                    coverage[purchase] = 1.0
                coverage[batches] = -ingredient["need_g"]
                builder.add_constraint(coverage, lower=0.0)
                if supply:
                    supply[batches] = -ingredient["need_g"]
                    builder.add_constraint(supply, upper=ingredient["content_g"] - 1.0)
        for department, available in hours.items():
            row = {variables[("n", rid)]: recipe["hours_per_batch"]
                   for rid, recipe in active.items() if recipe["department_id"] == department}
            if row:
                builder.add_constraint(row, upper=available)
        for lot in lots:
            lot_id = lot["lot_id"]
            balance = {variables[("s", lot_id, tier["discount_pct"])]: 1.0 for tier in lot["tiers"]}
            for partner_id in lot["partner_ok"]:
                balance[variables[("x", lot_id, partner_id)]] = 1.0
            for recipe_id in active:
                if ("u", lot_id, recipe_id) in variables:
                    balance[variables[("u", lot_id, recipe_id)]] = 1.0
            balance[variables[("r", lot_id)]] = 1.0
            builder.add_constraint(balance, lower=lot["quantity"], upper=lot["quantity"])
            cumulative = {}
            for tier in lot["tiers"]:
                cumulative[variables[("s", lot_id, tier["discount_pct"])]] = 1.0
                builder.add_constraint(dict(cumulative), upper=tier["cap"])
        for partner_id, partner in partners.items():
            loads = {variables[("x", lot["lot_id"], partner_id)]: lot["weight_kg"]
                     for lot in lots if ("x", lot["lot_id"], partner_id) in variables}
            if not loads:
                continue
            cost = 0.0 if partner["trip_sunk"] else partner["trip_cost"]
            trip = builder.add_var(upper=1, integer=True, profit=-cost)
            variables[("z", partner_id)] = trip
            loads[trip] = -partner["capacity_remaining_kg"]
            builder.add_constraint(loads, upper=0.0)
        gap_limit = self.config["solver_mip_gap"] if mip_gap is None else mip_gap
        result = builder.solve(self.config["solver_time_limit_seconds"], gap_limit)
        if result.x is None:
            raise RuntimeError("solver failed: " + str(result.message))
        gap = getattr(result, "mip_gap", None)
        return {
            "x": result.x,
            "variables": variables,
            "objective": -result.fun,
            "status": "optimal" if result.status == 0 else "feasible_not_optimal",
            "gap": None if gap is None or not np.isfinite(gap) else float(gap),
            "lots": lots,
            "active": active,
            "partners": partners,
            "hours": hours,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    def _report(self, solution):
        x = solution["x"]
        variables = solution["variables"]
        lots = solution["lots"]
        partners = solution["partners"]
        active = solution["active"]
        hours = solution["hours"]
        config = self.config
        lots_by_id = {lot["lot_id"]: lot for lot in lots}

        def count(key):
            return int(round(x[variables[key]])) if key in variables else 0

        def amount(key):
            return float(x[variables[key]]) if key in variables else 0.0

        trips = {}
        for partner_id, partner in partners.items():
            key = ("z", partner_id)
            if key not in variables or round(x[variables[key]]) < 1:
                continue
            kg = sum(lot["weight_kg"] * count(("x", lot["lot_id"], partner_id)) for lot in lots)
            if kg <= 0:
                continue
            incurred = 0.0 if partner["trip_sunk"] else partner["trip_cost"]
            handling = partner["handling_fee_per_kg"] * kg
            tax = 0.0
            if partner["partner_type"] == "DONATION":
                tax = config["donation_tax_rate"] * sum(
                    lot["unit_cost"] * count(("x", lot["lot_id"], partner_id)) for lot in lots)
            trips[partner_id] = {
                "partner_id": partner_id,
                "partner_type": partner["partner_type"],
                "pickup_dt": partner["pickup"].isoformat(),
                "kg": round(kg, 4),
                "capacity_kg": partner["max_capacity_kg_per_pickup"],
                "booked_kg_before": partner["booked_kg"],
                "sunk_trip": partner["trip_sunk"],
                "full_trip_cost_thb": round(partner["trip_cost"], 2),
                "trip_cost_thb": round(incurred, 2),
                "handling_thb": round(handling, 2),
                "tax_saving_thb": round(tax, 2),
                "total_cost_thb": round(incurred + handling, 2),
                "cost_per_kg_thb": round((incurred + handling) / kg, 2),
                "_incurred": incurred,
                "_handling": handling,
            }
        recipe_entries = {}
        for recipe_id, recipe in active.items():
            batches = count(("n", recipe_id))
            if batches == 0:
                continue
            revenue = batches * recipe["yield"] * recipe["output_price"]
            electricity = batches * recipe["hours_per_batch"] * config["electricity_cost_per_hour"]
            labor = batches * recipe["minutes"] * config["labor_cost_per_minute"]
            purchase = 0.0
            coverage = []
            for ingredient in recipe["ingredients"]:
                product_id = ingredient["product_id"]
                if product_id is None:
                    continue
                supplied = sum(lots_by_id[lot_id]["content_g"] * count(("u", lot_id, recipe_id))
                               for lot_id in recipe["suppliers"].get(product_id, []) if lot_id in lots_by_id)
                purchased = amount(("b", recipe_id, product_id))
                purchase += purchased * ingredient["cost_per_gram"]
                coverage.append({
                    "product_id": product_id,
                    "is_primary": ingredient["is_primary"],
                    "needed_g": ingredient["need_g"] * batches,
                    "supplied_g": supplied,
                    "purchased_g": round(purchased, 4),
                })
            recipe_entries[recipe_id] = {
                "recipe_id": recipe_id,
                "name": recipe["name"],
                "department_id": recipe["department_id"],
                "batches": batches,
                "hours": batches * recipe["hours_per_batch"],
                "portions": batches * recipe["yield"],
                "demand_cap": recipe["demand_cap"],
                "revenue_thb": round(revenue, 2),
                "electricity_thb": round(electricity, 2),
                "labor_thb": round(labor, 2),
                "purchase_thb": round(purchase, 2),
                "net_thb": revenue - electricity - labor - purchase,
                "coverage": coverage,
            }
        kitchen = []
        for department, available in hours.items():
            entries = [entry for entry in recipe_entries.values() if entry["department_id"] == department]
            if not entries:
                continue
            used = sum(entry["hours"] for entry in entries)
            smallest = min(recipe["hours_per_batch"] for recipe in active.values() if recipe["department_id"] == department)
            kitchen.append({
                "department_id": department,
                "hours_used": round(used, 4),
                "hours_available": available,
                "utilization": used / available if available > 0 else 0.0,
                "binding": available - used < smallest - 1e-9,
                "recipes": entries,
            })
        credits = {}
        primary_value = {}
        for recipe_id, entry in recipe_entries.items():
            recipe = active[recipe_id]
            for ingredient in recipe["ingredients"]:
                product_id = ingredient["product_id"]
                if product_id is None:
                    continue
                for lot_id in recipe["suppliers"].get(product_id, []):
                    if lot_id not in lots_by_id:
                        continue
                    units = count(("u", lot_id, recipe_id))
                    if units == 0:
                        continue
                    lot = lots_by_id[lot_id]
                    if ingredient["is_primary"]:
                        primary_value.setdefault(recipe_id, {})
                        primary_value[recipe_id][lot_id] = primary_value[recipe_id].get(lot_id, 0.0) + units * lot["unit_cost"]
                    else:
                        credits[(lot_id, recipe_id)] = units * lot["content_g"] * ingredient["cost_per_gram"]
        recipe_distributable = {}
        for recipe_id, entry in recipe_entries.items():
            total_credit = sum(value for (lot_id, rid), value in credits.items() if rid == recipe_id)
            recipe_distributable[recipe_id] = entry["net_thb"] - total_credit
        report_lots = []
        total_net = 0.0
        total_inventory = 0.0
        total_unresolved = 0
        for lot in lots:
            lot_id = lot["lot_id"]
            quantity = lot["quantity"]
            portions = []

            def add(kind, action, units, net, details):
                raw_nets.append(net)
                portions.append({
                    "portion_no": len(portions) + 1,
                    "lot_id": lot_id,
                    "kind": kind,
                    "action": action,
                    "units": units,
                    "share_pct": round(units / quantity * 100.0, 2),
                    "kg": round(units * lot["weight_kg"], 4),
                    "net_thb": round(net, 2),
                    "inventory_cost_thb": round(units * lot["unit_cost"], 2),
                    "details": details,
                })

            raw_nets = []
            discounted = []
            for tier in lot["tiers"]:
                units = count(("s", lot_id, tier["discount_pct"]))
                if units == 0:
                    continue
                if tier["discount_pct"] == 0:
                    add("MARKDOWN_REGULAR", "SELL_REGULAR", units, units * tier["price"],
                        {"unit_price": tier["price"], "band_ratio": round(tier["band_ratio"], 3)})
                else:
                    discounted.append((tier, units))
            if discounted:
                tier_rows = []
                for tier, units in discounted:
                    tier_rows.append({
                        "discount_pct": tier["discount_pct"],
                        "units": units,
                        "unit_price": tier["price"],
                        "net_thb": round(units * tier["price"], 2),
                        "band_ratio": round(tier["band_ratio"], 3),
                    })
                add("MARKDOWN_DISCOUNTED", "MARKDOWN", sum(units for _, units in discounted),
                    sum(units * tier["price"] for tier, units in discounted),
                    {"tiers": tier_rows,
                     "discount_value_thb": round(sum(units * (lot["regular_price"] - tier["price"]) for tier, units in discounted), 2)})
            for recipe_id, entry in recipe_entries.items():
                units = count(("u", lot_id, recipe_id))
                if units == 0:
                    continue
                recipe = active[recipe_id]
                role = "secondary"
                net = credits.get((lot_id, recipe_id), 0.0)
                if lot_id in primary_value.get(recipe_id, {}):
                    role = "primary"
                    share = primary_value[recipe_id][lot_id] / sum(primary_value[recipe_id].values())
                    net = recipe_distributable[recipe_id] * share
                add("UPCYCLE", "UPCYCLE", units, net, {
                    "recipe_id": recipe_id,
                    "department_id": recipe["department_id"],
                    "role": role,
                    "batches": entry["batches"],
                    "supplied_grams": units * lot["content_g"],
                })
            for partner_id, trip in trips.items():
                units = count(("x", lot_id, partner_id))
                if units == 0:
                    continue
                kg = units * lot["weight_kg"]
                share = kg / trip["kg"]
                trip_alloc = trip["_incurred"] * share
                handling = partners[partner_id]["handling_fee_per_kg"] * kg
                tax = config["donation_tax_rate"] * lot["unit_cost"] * units if trip["partner_type"] == "DONATION" else 0.0
                add("PARTNER", trip["partner_type"], units, tax - trip_alloc - handling, {
                    "partner_id": partner_id,
                    "pickup_dt": trip["pickup_dt"],
                    "trip_allocated_thb": round(trip_alloc, 2),
                    "handling_thb": round(handling, 2),
                    "tax_saving_thb": round(tax, 2),
                    "sunk_trip": trip["sunk_trip"],
                })
            unresolved = count(("r", lot_id))
            if unresolved:
                add("UNRESOLVED", "UNRESOLVED", unresolved, 0.0, {"reason": "no eligible route"})
            lot_net = sum(raw_nets)
            report_lots.append({
                "lot_id": lot_id,
                "product_id": lot["product_id"],
                "name": lot["name"],
                "unit": lot["unit"],
                "quantity": quantity,
                "weight_kg_total": round(quantity * lot["weight_kg"], 4),
                "risk_level": lot["risk_level"],
                "risk_score": lot["risk_score"],
                "best_action": self._best_action(portions),
                "net_recovery_thb": round(lot_net, 2),
                "inventory_cost_thb": round(quantity * lot["unit_cost"], 2),
                "plan": portions,
                "explain": self._explain(lot, portions, trips, kitchen, partners, solution),
            })
            total_net += lot_net
            total_inventory += quantity * lot["unit_cost"]
            total_unresolved += unresolved
        penalty = config["big_m_per_unit"] * total_unresolved
        for trip in trips.values():
            trip.pop("_incurred")
            trip.pop("_handling")
        return {
            "lots": report_lots,
            "trips": trips,
            "kitchen": kitchen,
            "net_recovery": total_net,
            "inventory_cost": total_inventory,
            "unresolved_units": total_unresolved,
            "reconciliation_gap": abs(solution["objective"] + penalty - total_net),
        }

    def _best_action(self, portions):
        if not portions:
            return "NONE"
        labels = {}
        for portion in portions:
            label = {"MARKDOWN_REGULAR": "SELL_REGULAR", "MARKDOWN_DISCOUNTED": "MARKDOWN"}.get(portion["kind"], portion["action"])
            labels[label] = labels.get(label, 0) + portion["units"]
        ordered = sorted(labels, key=lambda name: -labels[name])
        return ordered[0] if len(ordered) == 1 else "MIXED: " + " + ".join(ordered)

    def _explain(self, lot, portions, trips, kitchen, partners, solution):
        binding = []
        for entry in kitchen:
            if entry["binding"] and any(
                    portion["kind"] == "UPCYCLE" and portion["details"]["department_id"] == entry["department_id"]
                    for portion in portions):
                binding.append("KITCHEN_HOURS:%s %.2f/%.2f" % (entry["department_id"], entry["hours_used"], entry["hours_available"]))
        for portion in portions:
            if portion["kind"] == "PARTNER":
                trip = trips[portion["details"]["partner_id"]]
                if trip["kg"] + trip["booked_kg_before"] >= trip["capacity_kg"] - 1e-6:
                    binding.append("PARTNER_CAPACITY:" + trip["partner_id"])
        tier_units = {portion_tier["discount_pct"]: portion_tier["units"]
                      for portion in portions if portion["kind"] == "MARKDOWN_DISCOUNTED"
                      for portion_tier in portion["details"]["tiers"]}
        regular = sum(portion["units"] for portion in portions if portion["kind"] == "MARKDOWN_REGULAR")
        if lot["tiers"]:
            sold = regular + sum(tier_units.values())
            if sold >= lot["tiers"][-1]["cap"] - 0 and sold > 0:
                binding.append("DEMAND_LADDER_FULLY_USED:%d" % sold)
        reference_kg = max([trips[portion["details"]["partner_id"]]["kg"] for portion in portions if portion["kind"] == "PARTNER"] or [0.0])
        alternatives = {}
        if reference_kg > 0:
            for partner_id in lot["partner_ok"]:
                partner = partners[partner_id]
                trip_cost = 0.0 if partner["trip_sunk"] else partner["trip_cost"]
                alternatives[partner["partner_type"]] = round((trip_cost + partner["handling_fee_per_kg"] * reference_kg) / reference_kg, 2)
        return {"excluded": lot["excluded"], "binding": binding, "alt_cost_per_kg": alternatives,
                "reference_load_kg": round(reference_kg, 3)}

    def _attach_hour_values(self, plan, context, solution):
        base = None
        for entry in plan["kitchen"]:
            department = entry["department_id"]
            entry["extra_hour_value_thb"] = None
            if not entry["binding"]:
                continue
            if base is None:
                base = self._solve(context["lots"], context["recipes"], context["partners"], dict(context["hours"]), 1e-7)
            hours = dict(context["hours"])
            hours[department] = hours[department] + 1.0
            more = self._solve(context["lots"], context["recipes"], context["partners"], hours, 1e-7)
            entry["extra_hour_value_thb"] = round(more["objective"] - base["objective"], 2)

    def _baselines(self, context, joint_report):
        lots = context["lots"]
        inventory = sum(lot["quantity"] * lot["unit_cost"] for lot in lots)
        do_nothing = 0.0
        for lot in lots:
            regular = next((tier for tier in lot["tiers"] if tier["discount_pct"] == 0), None)
            if regular:
                do_nothing += min(lot["quantity"], regular["cap"]) * regular["price"]
        hours = dict(context["hours"])
        sequential_net = 0.0
        sequential_trip_cost = 0.0
        sequential_unresolved = 0
        sequential_kg = {}
        for lot in sorted(lots, key=lambda item: item["lot_id"]):
            solution = self._solve([lot], context["recipes"], context["partners"], dict(hours))
            report = self._report(solution)
            sequential_net += report["net_recovery"]
            sequential_unresolved += report["unresolved_units"]
            sequential_trip_cost += sum(trip["total_cost_thb"] for trip in report["trips"].values())
            for partner_id, trip in report["trips"].items():
                sequential_kg[partner_id] = sequential_kg.get(partner_id, 0.0) + trip["kg"]
            for entry in report["kitchen"]:
                hours[entry["department_id"]] -= entry["hours_used"]
        overbooked = {}
        for partner_id, kg in sequential_kg.items():
            remaining = context["partners"][partner_id]["capacity_remaining_kg"]
            if kg > remaining + 1e-6:
                overbooked[partner_id] = round(kg - remaining, 2)
        joint_trip_cost = sum(trip["total_cost_thb"] for trip in joint_report["trips"].values())
        return {
            "inventory_cost_thb": round(inventory, 2),
            "joint": {
                "net_recovery_thb": round(joint_report["net_recovery"], 2),
                "net_vs_cost_thb": round(joint_report["net_recovery"] - inventory, 2),
                "trip_cost_thb": round(joint_trip_cost, 2),
                "unresolved_units": joint_report["unresolved_units"],
            },
            "sequential_lot_by_lot": {
                "net_recovery_thb": round(sequential_net, 2),
                "net_vs_cost_thb": round(sequential_net - inventory, 2),
                "trip_cost_thb": round(sequential_trip_cost, 2),
                "unresolved_units": sequential_unresolved,
                "partner_kg_overbooked": overbooked,
            },
            "do_nothing": {
                "net_recovery_thb": round(do_nothing, 2),
                "net_vs_cost_thb": round(do_nothing - inventory, 2),
            },
        }