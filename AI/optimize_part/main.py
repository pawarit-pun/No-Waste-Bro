import argparse
import json
import sys
from datetime import datetime

import database
import rules
from database import build_mock_database, new_run_id
from forecaster import Forecaster
from optimizer import RunOptimizer


def money(value):
    return "{:,.2f}".format(value)


def format_table(headers, rows, right=()):
    widths = [len(str(header)) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))
    def line(cells):
        parts = []
        for index, cell in enumerate(cells):
            text = str(cell)
            parts.append(text.rjust(widths[index]) if index in right else text.ljust(widths[index]))
        return "  ".join(parts)
    out = [line(headers), "  ".join("-" * width for width in widths)]
    out.extend(line(row) for row in rows)
    return "\n".join(out)


def section(title):
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)


def inject_stale_capacity(db, plan, now):
    for trip in plan["trips"]:
        if trip["sunk_trip"]:
            partner = db.get_partner(trip["partner_id"])
            remaining = partner["max_capacity_kg_per_pickup"] - trip["booked_kg_before"]
            db.add_booking(trip["partner_id"], datetime.fromisoformat(trip["pickup_dt"]), remaining)
            return trip["partner_id"]
    return None


def run_pipeline(db, now, scenario):
    run_id = new_run_id(now)
    forecaster = Forecaster(db, now)
    forecasts = forecaster.run(run_id)
    optimizer = RunOptimizer(db, now)
    limits = db.optimizer_config["guardrails"]
    exclusions = set()
    history = []
    stale_partner = None    
    plan = None
    verdicts = None
    for round_index in range(limits["max_resolve_rounds"] + 1):
        plan = optimizer.run(run_id, forecasts, exclusions)
        if scenario == "stale" and round_index == 0:
            stale_partner = inject_stale_capacity(db, plan, now)
        verdicts = rules.evaluate_plan(plan, db, now, plan["snapshot_fingerprint"])
        blocked = [verdict for verdict in verdicts if verdict["status"] == "BLOCKED"]
        history.append({
            "round": round_index,
            "net_recovery_thb": plan["run_summary"]["net_recovery_thb"],
            "blocked_portions": [(v["lot_id"], v["portion_no"], [f["rule"] for f in v["hard_failures"]]) for v in blocked],
            "exclusions_before": sorted(str(item) for item in exclusions),
        })
        if not blocked or round_index == limits["max_resolve_rounds"]:
            break
        exclusions |= rules.exclusions_from_blocked(plan, verdicts)
    records = rules.build_decision_records(plan, verdicts, run_id, plan["snapshot_version"], optimizer.model_version)
    db.insert_decisions(records)
    approvals = rules.build_approval_queue(records, plan, db, now)
    db.insert_approvals(approvals)
    db.release_lots(run_id)
    return {
        "run_id": run_id,
        "forecaster": forecaster,
        "forecasts": forecasts,
        "plan": plan,
        "verdicts": verdicts,
        "records": records,
        "approvals": approvals,
        "history": history,
        "stale_partner": stale_partner,
    }


def print_environment(db, now, outcome, scenario):
    section("SIMULATION CLOCK")
    print("start            : %s (ISO weekday %d, 1 = Monday)" % (now.strftime("%Y-%m-%d %H:%M"), now.isoweekday()))
    print("run_id           : %s" % outcome["run_id"])
    print("scenario         : %s" % scenario)
    print("lead time        : %d minutes before a partner can pick up" % db.optimizer_config["lead_time_minutes"])
    print("expiry cutoff    : end of expiration_date at %s" % db.optimizer_config["expiry_cutoff_time"])
    section("SCHEMA CHANGES APPLIED TO THE MOCK DATABASE")
    for item in database.SCHEMA_CHANGES:
        print("- " + item)
    section("MISSING OR ASSUMED ATTRIBUTES (needs your instruction)")
    for item in db.audit_missing():
        print("- " + item)
    section("PARTNERS")
    rows = []
    for partner_id, partner in db.donation_partners.items():
        pickup = rules.next_pickup(partner, now, db.optimizer_config)
        booked = db.booked_kg_at_slot(partner_id, pickup.date()) if pickup else 0.0
        trip = partner["fixed_cost_per_trip"] + partner["distance_km"] * db.optimizer_config["variable_cost_per_km"]
        rows.append([
            partner_id, partner["partner_type"], partner["distance_km"], money(partner["fixed_cost_per_trip"]),
            money(partner["handling_fee_per_kg"]), partner["max_capacity_kg_per_pickup"],
            "%s-%s" % (partner["pickup_time_start"].strftime("%H:%M"), partner["pickup_time_end"].strftime("%H:%M")),
            partner["min_days_before_expiry"], pickup.strftime("%m-%d %H:%M") if pickup else "none",
            booked, money(trip),
        ])
    print(format_table(["partner", "type", "km", "fixed", "handling/kg", "cap kg", "window", "min_days", "next pickup", "booked kg", "trip cost"],
                       rows, right=(2, 3, 4, 5, 7, 9, 10)))
    print("trip cost = fixed_cost_per_trip + distance_km x %.2f baht/km, paid once per pickup and shared by every lot on it" %
          db.optimizer_config["variable_cost_per_km"])


def print_forecaster(db, outcome):
    section("FORECASTER OUTPUT (simulated scraped data, forwarded lots only)")
    forecaster = outcome["forecaster"]
    print("scraped rows aggregated: %d" % forecaster.signals["row_count"])
    rows = []
    for forecast in outcome["forecasts"]:
        assessment = db.get_assessment(forecast["assessment_id"])
        lot = db.get_lot(forecast["lot_id"])
        kitchen = forecast["kitchen"]
        rows.append([
            forecast["lot_id"], forecast["product_id"], forecast["quantity"], forecast["unit"],
            lot["expiration_date"].isoformat(), assessment["risk_score"], assessment["risk_level"],
            len(forecast["shelf"]), "%s x%d" % (kitchen["recipe_id"], kitchen["menu_qty"]) if kitchen else "-",
        ])
    print(format_table(["lot", "product", "qty", "unit", "expires", "risk %", "level", "tiers", "kitchen"], rows, right=(2, 5, 7)))
    for item in forecaster.not_forwarded:
        print("not forwarded to the optimizer: %s risk_score %.1f (%s)" % (item["lot_id"], item["risk_score"], item["risk_level"]))
    print()
    print("example forecaster JSON (lot %s):" % outcome["forecasts"][0]["lot_id"])
    print(json.dumps(outcome["forecasts"][0], ensure_ascii=False, indent=2))


def print_eligibility(plan, outcome):
    section("ELIGIBILITY PRE-CHECK (rules module) - OK or first blocking reason")
    methods = database.PARTNER_TYPES
    forecasts = {forecast["lot_id"]: forecast for forecast in outcome["forecasts"]}
    rows = []
    for lot in plan["lots"]:
        excluded = lot["explain"]["excluded"]
        forecast = forecasts[lot["lot_id"]]
        tiers = len(forecast["shelf"]) - sum(1 for key in excluded if key.startswith("MARKDOWN:"))
        kitchen = forecast["kitchen"]
        upcycle = "-"
        if kitchen:
            key = "UPCYCLE:" + kitchen["recipe_id"]
            upcycle = kitchen["recipe_id"] if key not in excluded else "NO:" + excluded[key][0]
        row = [lot["lot_id"], lot["product_id"], "%d tiers" % tiers, upcycle]
        for method in methods:
            row.append("OK" if method not in excluded else "NO:" + excluded[method][0])
        rows.append(row)
    print(format_table(["lot", "product", "markdown", "upcycle"] + ["DON", "ANI", "CMP", "AD", "LDF"], rows))
    print()
    print("reason codes: P1 product flag, P2 category, P3 partner closed, P4 expiry before pickup, P5 donation shelf life,")
    print("P6 capacity, K markdown rules, U upcycling rules")
    legend = []
    for lot in plan["lots"]:
        for key, reasons in lot["explain"]["excluded"].items():
            if len(reasons) > 1:
                legend.append("%s %s: %s" % (lot["lot_id"], key, ", ".join(reasons)))
    for line in legend:
        print("  " + line)


def print_plan(plan, outcome):
    section("OPTIMIZER RESULT - best action per lot, split by share, net money recovered")
    status = {(v["lot_id"], v["portion_no"]): v for v in outcome["verdicts"]}
    for lot in plan["lots"]:
        print()
        print("%s  %s  qty %d %s  weight %.2f kg  risk %s (%.1f)" % (
            lot["lot_id"], lot["product_id"], lot["quantity"], lot["unit"], lot["weight_kg_total"], lot["risk_level"], lot["risk_score"]))
        print("best action: %s" % lot["best_action"])
        rows = []
        for portion in lot["plan"]:
            details = portion["details"]
            if portion["kind"] == "MARKDOWN_REGULAR":
                label = "sell at regular price %.2f" % details["unit_price"]
            elif portion["kind"] == "MARKDOWN_DISCOUNTED":
                label = "markdown " + ", ".join("%d%% x%d" % (t["discount_pct"], t["units"]) for t in details["tiers"])
            elif portion["kind"] == "UPCYCLE":
                label = "upcycle %s (%s, %d batch)" % (details["recipe_id"], details["role"], details["batches"])
            elif portion["kind"] == "PARTNER":
                label = "%s via %s" % (portion["action"], details["partner_id"])
            else:
                label = "no route"
            verdict = status[(lot["lot_id"], portion["portion_no"])]
            tag = verdict["status"] + (" + warning" if verdict["warnings"] and verdict["status"] == "AUTO" else "")
            rows.append([portion["portion_no"], label, portion["units"], "%.1f%%" % portion["share_pct"],
                         "%.2f" % portion["kg"], money(portion["net_thb"]), tag])
        rows.append(["", "TOTAL", lot["quantity"], "100.0%", "%.2f" % lot["weight_kg_total"], money(lot["net_recovery_thb"]), ""])
        print(format_table(["#", "action", "units", "share", "kg", "net thb", "guardrails"], rows, right=(2, 3, 4, 5)))
        if lot["explain"]["binding"]:
            print("binding: " + "; ".join(lot["explain"]["binding"]))
        if lot["explain"]["alt_cost_per_kg"]:
            print("route cost per kg at trip load %.2f kg: %s" % (
                lot["explain"]["reference_load_kg"],
                ", ".join("%s %.2f" % (k, v) for k, v in lot["explain"]["alt_cost_per_kg"].items())))
    section("TRIPS (fixed cost and distance paid once per trip, shared by lots)")
    rows = []
    for trip in plan["trips"]:
        rows.append([trip["partner_id"], trip["partner_type"], trip["pickup_dt"][5:16].replace("T", " "), "%.2f" % trip["kg"],
                     "%.0f" % trip["booked_kg_before"], "yes" if trip["sunk_trip"] else "no", money(trip["trip_cost_thb"]),
                     money(trip["handling_thb"]), money(trip["tax_saving_thb"]), money(trip["cost_per_kg_thb"])])
    print(format_table(["partner", "type", "pickup", "kg", "booked", "paid", "trip cost", "handling", "tax saving", "cost/kg"], rows, right=(3, 4, 6, 7, 8, 9)))
    section("KITCHEN (hours, labor 1.53 baht/min, electricity, ingredients)")
    rows = []
    for entry in plan["kitchen"]:
        for recipe in entry["recipes"]:
            rows.append([entry["department_id"], recipe["recipe_id"], recipe["batches"], recipe["portions"], recipe["demand_cap"],
                         "%.2f" % recipe["hours"], money(recipe["revenue_thb"]), money(recipe["labor_thb"]),
                         money(recipe["electricity_thb"]), money(recipe["purchase_thb"]), money(recipe["net_thb"])])
    print(format_table(["dept", "recipe", "batches", "portions", "demand", "hours", "revenue", "labor", "electricity", "bought", "net"],
                       rows, right=(2, 3, 4, 5, 6, 7, 8, 9, 10)))
    for entry in plan["kitchen"]:
        extra = entry["extra_hour_value_thb"]
        print("%s: %.2f of %.2f hours used%s" % (
            entry["department_id"], entry["hours_used"], entry["hours_available"],
            ", one more hour would add %s baht to the run" % money(extra) if extra is not None else ""))


def print_comparison(plan):
    section("WHY A JOINT RUN-LEVEL MODEL (same data, three ways of deciding)")
    base = plan["baselines"]
    rows = [
        ["MILP over every lot in the run", money(base["joint"]["net_recovery_thb"]), money(base["joint"]["net_vs_cost_thb"]),
         money(base["joint"]["trip_cost_thb"]), base["joint"]["unresolved_units"]],
        ["lot by lot, no shared resources", money(base["sequential_lot_by_lot"]["net_recovery_thb"]),
         money(base["sequential_lot_by_lot"]["net_vs_cost_thb"]), money(base["sequential_lot_by_lot"]["trip_cost_thb"]),
         base["sequential_lot_by_lot"]["unresolved_units"]],
        ["do nothing (regular price only)", money(base["do_nothing"]["net_recovery_thb"]), money(base["do_nothing"]["net_vs_cost_thb"]), "-", "-"],
    ]
    print("inventory cost of the run: %s baht" % money(base["inventory_cost_thb"]))
    print(format_table(["strategy", "net recovery", "vs inventory cost", "trip cost", "unresolved"], rows, right=(1, 2, 3, 4)))
    overbooked = base["sequential_lot_by_lot"]["partner_kg_overbooked"]
    if overbooked:
        print("lot by lot also books partner capacity twice: %s" % ", ".join("%s +%.2f kg over" % (k, v) for k, v in overbooked.items()))
    print("net recovery maximised = loss from food waste minimised, because inventory cost is already sunk")


def print_guardrails(outcome):
    section("GUARDRAILS - per portion verdict")
    counts = {}
    for verdict in outcome["verdicts"]:
        counts[verdict["status"]] = counts.get(verdict["status"], 0) + 1
    print("portions: %d  %s" % (len(outcome["verdicts"]), "  ".join("%s=%d" % item for item in sorted(counts.items()))))
    rows = []
    for verdict in outcome["verdicts"]:
        notes = [item["rule"] + " (" + item["detail"] + ")" for item in verdict["hard_failures"] + verdict["soft_flags"]]
        notes += [item["rule"] + " (" + item["detail"] + ")" for item in verdict["warnings"]]
        if notes:
            rows.append([verdict["lot_id"], verdict["portion_no"], verdict["kind"], verdict["status"], "; ".join(notes)])
    if rows:
        print(format_table(["lot", "#", "portion", "status", "rules hit"], rows))
    section("APPROVAL QUEUE")
    if not outcome["approvals"]:
        print("empty")
    else:
        rows = [[a["lot_id"], ", ".join(a["reason_codes"]), money(a["value_at_stake_thb"]), a["deadline_at"].strftime("%m-%d %H:%M"), a["state"]]
                for a in outcome["approvals"]]
        print(format_table(["lot", "reasons", "net thb (cost if unresolved)", "deadline", "state"], rows, right=(2,)))
    print()
    print("decision records written: %d" % len(outcome["records"]))
    if len(outcome["history"]) > 1 or outcome["stale_partner"]:
        section("RE-SOLVE LOOP (BLOCKED portions are excluded and the model is solved again)")
        for item in outcome["history"]:
            print("round %d: net recovery %s, blocked %s, exclusions %s" % (
                item["round"], money(item["net_recovery_thb"]), item["blocked_portions"] or "none", item["exclusions_before"] or "none"))
        if outcome["stale_partner"]:
            print("injected change: partner %s capacity was booked by someone else after the optimizer snapshot" % outcome["stale_partner"])


def write_output(path, outcome):
    plan = dict(outcome["plan"])
    plan.pop("snapshot_fingerprint", None)
    payload = {
        "run_id": outcome["run_id"],
        "forecaster_output": outcome["forecasts"],
        "optimizer_plan": plan,
        "guardrail_verdicts": outcome["verdicts"],
        "decision_records": outcome["records"],
        "approval_queue": outcome["approvals"],
        "resolve_history": outcome["history"],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=database.SIMULATION_START.isoformat())
    parser.add_argument("--scenario", choices=["normal", "stale"], default="normal")
    parser.add_argument("--kappa", type=float, default=None)
    parser.add_argument("--output", default="plan_output.json")
    parser.add_argument("--quiet-forecast", action="store_true")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    now = datetime.fromisoformat(args.start)
    db = build_mock_database(now)
    if args.kappa is not None:
        db.optimizer_config["kappa"] = args.kappa
    outcome = run_pipeline(db, now, args.scenario)
    print_environment(db, now, outcome, args.scenario)
    print_forecaster(db, outcome)
    print_eligibility(outcome["plan"], outcome)
    print_plan(outcome["plan"], outcome)
    print_comparison(outcome["plan"])
    print_guardrails(outcome)
    summary = outcome["plan"]["run_summary"]
    section("RUN SUMMARY")
    print("lots optimised        : %d" % summary["lots"])
    print("inventory cost        : %s baht" % money(summary["inventory_cost_thb"]))
    print("net recovery          : %s baht" % money(summary["net_recovery_thb"]))
    print("net vs inventory cost : %s baht" % money(summary["net_vs_cost_thb"]))
    print("unresolved units      : %d" % summary["unresolved_units"])
    gap = outcome["plan"]["solver"]["gap"]
    print("solver                : %s, gap %s, %d ms" % (outcome["plan"]["solver"]["status"], "n/a" if gap is None else "%.4f%%" % (gap * 100), outcome["plan"]["solver"]["time_ms"]))
    print("reconciliation gap    : %.6f baht between solver objective and per-portion accounting" % summary["reconciliation_gap_thb"])
    write_output(args.output, outcome)
    print("full output written to %s" % args.output)


if __name__ == "__main__":
    main()