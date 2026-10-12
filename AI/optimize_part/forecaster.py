import math
import random
import uuid

import rules
from database import unit_content_grams

SCRAPE_SOURCES = {"retail_portal_a": 1.05, "retail_portal_b": 0.95}

SCRAPED_BASELINE = {
    "daily_units": {
        "MEA-001": 56.0,
        "MEA-002": 8.0,
        "SEA-001": 8.5,
        "PRO-001": 12.0,
        "PRO-002": 14.0,
        "DAI-001": 20.0,
        "DAI-002": 40.0,
        "BAK-001": 12.0,
        "BAK-003": 30.0,
    },
    "category_elasticity": {
        "MEAT": 2.4,
        "SEAFOOD": 3.2,
        "PRODUCE": 3.0,
        "DAIRY": 2.6,
        "BAKERY": 2.8,
        "READY_TO_EAT": 2.0,
    },
    "daily_menu_demand": {
        "RCP-001": 30.0,
        "RCP-002": 60.0,
        "RCP-003": 30.0,
        "RCP-004": 24.0,
        "RCP-005": 12.0,
        "RCP-006": 24.0,
    },
}


def scrape_market_signals():
    rows = []
    for source, factor in SCRAPE_SOURCES.items():
        for product_id, units in SCRAPED_BASELINE["daily_units"].items():
            rows.append({"source": source, "key": ("product", product_id), "value": units * factor})
        for recipe_id, demand in SCRAPED_BASELINE["daily_menu_demand"].items():
            rows.append({"source": source, "key": ("menu", recipe_id), "value": demand * factor})
    grouped = {}
    for row in rows:
        grouped.setdefault(row["key"], []).append(row["value"])
    averaged = {key: round(sum(values) / len(values), 6) for key, values in grouped.items()}
    return {
        "daily_units": {key[1]: value for key, value in averaged.items() if key[0] == "product"},
        "daily_menu_demand": {key[1]: value for key, value in averaged.items() if key[0] == "menu"},
        "category_elasticity": dict(SCRAPED_BASELINE["category_elasticity"]),
        "row_count": len(rows),
    }


def ceil_to_satang(value):
    return math.ceil(value * 100.0 - 1e-9) / 100.0


class Forecaster:
    model_version = "forecaster_v1"

    def __init__(self, db, now, seed=11):
        self.db = db
        self.now = now
        self.seed = seed
        self.signals = scrape_market_signals()
        self.not_forwarded = []

    def run(self, run_id):
        forecasts = []
        self.not_forwarded = []
        for lot in self.db.lots_ready_for_run():
            forecast = self._forecast_lot(run_id, lot)
            if forecast is not None:
                forecasts.append(forecast)
        return forecasts

    def _risk_level(self, score):
        for threshold, name in self.db.optimizer_config["risk_levels"]:
            if score >= threshold:
                return name
        return "LOW"

    def _forecast_lot(self, run_id, lot):
        config = self.db.optimizer_config
        product = self.db.get_product(lot["product_id"])
        quantity = lot["current_quantity"]
        expired = rules.days_to_expiry(lot, self.now) < 0
        remaining_hours = max(0.0, rules.hours_left_at(lot, self.now, config))
        rng = random.Random("%s-%s" % (self.seed, lot["lot_id"]))
        daily_units = self.signals["daily_units"].get(product["product_id"], 10.0) * (1.0 + rng.uniform(-0.03, 0.03))
        predicted_float = 0.0 if expired else min(float(quantity), daily_units * remaining_hours / 24.0)
        predicted = int(round(predicted_float))
        leftover = quantity - predicted
        risk_score = 100.0 if expired else round(leftover / quantity * 100.0, 1)
        risk_level = self._risk_level(risk_score)
        assessment_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "%s|%s" % (run_id, lot["lot_id"])))
        self.db.insert_assessment({
            "assessment_id": assessment_id,
            "run_id": run_id,
            "lot_id": lot["lot_id"],
            "assessed_at": self.now,
            "days_to_expiry": rules.days_to_expiry(lot, self.now),
            "quantity_at_assessment": quantity,
            "forecast_daily_demand": round(daily_units, 2),
            "predicted_units_sold_before_expiry": predicted,
            "predicted_leftover_units": leftover,
            "sell_through_probability": round(predicted / quantity, 3),
            "risk_score": risk_score,
            "risk_level": risk_level,
            "model_version": self.model_version,
        })
        if not expired and risk_score < config["risk_forward_threshold"]:
            self.not_forwarded.append({"lot_id": lot["lot_id"], "risk_score": risk_score, "risk_level": risk_level})
            return None
        return {
            "assessment_id": assessment_id,
            "lot_id": lot["lot_id"],
            "product_id": product["product_id"],
            "unit": product["unit_of_measure"],
            "quantity": quantity,
            "shelf": [] if expired else self._shelf(product, quantity, predicted_float, rng),
            "kitchen": None if expired or not product["allow_upcycling"] else self._kitchen(product, quantity),
            "model_version": self.model_version,
        }

    def _shelf(self, product, quantity, base_demand, rng):
        config = self.db.optimizer_config
        elasticity = self.signals["category_elasticity"][product["category"]]
        shelf = []
        previous = 0
        for discount in config["markdown_discount_levels"]:
            price = ceil_to_satang(product["regular_price"] * (1.0 - discount / 100.0))
            if discount > 0 and price < product["min_allowed_price"]:
                continue
            noise = 1.0 + rng.uniform(-0.03, 0.03)
            expected = int(round(min(float(quantity), base_demand * (1.0 + elasticity * discount / 100.0) * noise)))
            expected = max(expected, previous)
            band = 0.10 + 0.002 * discount
            low = max(0, int(round(expected * (1.0 - band))))
            high = min(quantity, int(round(expected * (1.0 + band))))
            shelf.append({
                "discount_pct": discount,
                "price": price,
                "expected_qty": expected,
                "low": min(low, expected),
                "high": max(high, expected),
            })
            previous = expected
        return shelf

    def _kitchen(self, product, quantity):
        best = None
        content = unit_content_grams(product)
        for recipe in self.db.recipes_with_primary(product["product_id"]):
            demand = self.signals["daily_menu_demand"].get(recipe["recipe_id"], 0.0)
            yield_per_batch = recipe["output_quantity"]
            need_grams = sum(row["required_quantity"] for row in self.db.ingredients_of(recipe["recipe_id"])
                             if row["product_id"] == product["product_id"] and row["is_primary_ingredient"])
            units_per_batch = need_grams / content
            batches = min(int(math.ceil(demand / yield_per_batch - 1e-9)), int(quantity // units_per_batch))
            if batches <= 0:
                continue
            menu_qty = int(min(math.floor(demand + 1e-9), batches * yield_per_batch))
            output_price = self.db.get_product(recipe["output_product_id"])["regular_price"]
            value = menu_qty * output_price
            if best is None or value > best[0]:
                ingredient_qty = int(math.ceil(batches * units_per_batch - 1e-9))
                best = (value, {"recipe_id": recipe["recipe_id"], "menu_qty": menu_qty, "ingredient_qty": ingredient_qty})
        return None if best is None else best[1]