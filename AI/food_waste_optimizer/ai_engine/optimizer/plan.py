"""PART 6 — แปลงคำตอบของ solver เป็น Plan ที่อ่านรู้เรื่อง (สัดส่วน % ต่อ lot, เงินที่ได้/เสีย, เหตุผล)

นิยามเงิน (ต่อ portion):  net_profit = revenue − cost − cogs
  revenue = ขายหน้าร้าน | ราคาขายเมนู (+เครดิตวัตถุดิบรอง) | buyback_price_per_kg × kg
  cost    = ค่าเที่ยว (fixed+travel แบ่งตาม kg) + handling×kg | utility_cost ของครัว
  cogs    = จำนวน × lot.unit_cost  (Cost_Primary ของครัวก็คือ cogs ของวัตถุดิบหลัก)
net_recovery = revenue − cost  (เงินที่ได้กลับคืนจริง ไม่นับต้นทุนสินค้าที่จมไปแล้ว)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from ai_engine.optimizer.rules import days_to_expiry
from ai_engine.optimizer.solver import Solution, Switches, solve

SALE_METHODS = ("SELL_REGULAR", "MARKDOWN")


def _r(x: float, n: int = 2) -> float:
    return round(float(x), n)


def _portion(lc, method: str, units: int, revenue: float, cost: float, details: dict) -> dict:
    cogs = units * lc.lot.unit_cost
    return {
        "method": method, "units": units,
        "share_pct": _r(units / lc.lot.quantity * 100.0),
        "weight_kg": _r(units * (lc.weight_kg or 0.0), 4),
        "revenue_thb": _r(revenue), "cost_thb": _r(cost), "cogs_thb": _r(cogs),
        "net_profit_thb": _r(revenue - cost - cogs), "details": details,
    }


# ---------------------------------------------------------------- เที่ยวรับของ partner
def _trips(ctx, sol: Solution) -> dict:
    trips = {}
    for pid, pc in ctx.partners.items():
        units = {lid: sol.count(("x", lid, pid)) for lid in ctx.lots}
        units = {k: v for k, v in units.items() if v > 0}
        if not units:
            continue
        kg = sum(u * ctx.lots[lid].weight_kg for lid, u in units.items())
        incurred = 0.0 if pc.sunk else pc.trip_cost
        handling, revenue = pc.handling * kg, pc.partner.buyback * kg
        p = pc.partner
        trips[pid] = {
            "partner_id": pid, "name": p.name, "partner_type": p.partner_type,
            "pickup_at": pc.pickup.isoformat() if pc.pickup else None,
            "kg": _r(kg, 3), "capacity_kg": _r(pc.cap_kg, 2), "min_kg": p.min_kg,
            "fixed_cost_thb": _r(p.fixed), "travel_cost_thb": _r(0.0 if p.partner_type == "DONATION" else p.travel),
            "trip_cost_thb": _r(incurred), "handling_thb": _r(handling), "buyback_revenue_thb": _r(revenue),
            "total_cost_thb": _r(incurred + handling),
            "net_cash_thb": _r(revenue - incurred - handling),
            "cost_per_kg_thb": _r((incurred + handling) / kg),
            "_incurred": incurred, "_kg": kg, "units": units,
        }
    return trips


# ---------------------------------------------------------------- งานครัว
def _kitchen_jobs(ctx, sol: Solution) -> list:
    jobs = []
    for rid, rc in ctx.recipes.items():
        if not rc.eligible:
            continue
        r = rc.recipe
        for day in rc.days:
            n = sol.count(("n", rid, day))
            if n == 0:
                continue
            prim = {lid: sol.count(("k", lid, rid, day)) for lid in ctx.lots if ("k", lid, rid, day) in sol.var}
            sec = {lid: sol.count(("k2", lid, rid, day)) for lid in ctx.lots if ("k2", lid, rid, day) in sol.var}
            prim = {k: v for k, v in prim.items() if v > 0}
            sec = {k: v for k, v in sec.items() if v > 0}
            revenue, utility = n * r.output_qty * rc.out_price, n * r.utility_cost
            cost_primary = sum(u * ctx.lots[l].lot.unit_cost for l, u in prim.items())
            sec_credit = {l: u * ctx.inputs.products[ctx.lots[l].product.product_id].base_cost for l, u in sec.items()}
            sec_cogs = sum(u * ctx.lots[l].lot.unit_cost for l, u in sec.items())
            net = revenue - utility - cost_primary + sum(sec_credit.values()) - sec_cogs
            anchor = max(prim, key=lambda l: (prim[l] * ctx.lots[l].lot.unit_cost, -ctx.lots[l].lot.expiration_date.toordinal()))
            jobs.append({
                "job_id": f"{rid}@{day.isoformat()}", "recipe_id": rid, "name": r.name,
                "department_id": r.department_id, "date": day.isoformat(),
                "due_by": ctx.hours[(r.department_id, day)].due.isoformat(),
                "batches": n, "hours": _r(n * rc.hours_per_batch), "output_units": _r(n * r.output_qty),
                "output_product_id": r.output_product_id,
                "revenue_thb": _r(revenue), "utility_cost_thb": _r(utility), "cost_primary_thb": _r(cost_primary),
                "secondary_credit_thb": _r(sum(sec_credit.values())), "net_profit_thb": _r(net),
                "primary_lots": prim, "secondary_lots": sec, "anchor_lot_id": anchor,
                "_revenue": revenue, "_utility": utility, "_cost_primary": cost_primary, "_sec_credit": sec_credit,
            })
    return jobs


def _kitchen_usage(ctx, jobs: list) -> list:
    used: dict = defaultdict(float)
    for j in jobs:
        used[(j["department_id"], j["date"])] += j["hours"]
    out = []
    for (dept, day), hrs in sorted(used.items()):
        budget = next(dc.hours for (d, dy), dc in ctx.hours.items() if d == dept and dy.isoformat() == day)
        smallest = min((rc.hours_per_batch for rc in ctx.recipes.values()
                        if rc.eligible and rc.recipe.department_id == dept), default=0.0)
        out.append({"department_id": dept, "date": day, "hours_used": _r(hrs), "hours_budget": _r(budget),
                    "utilization": _r(hrs / budget, 3) if budget > 0 else 0.0,
                    "binding": budget - hrs < smallest - 1e-9})
    return out


# ---------------------------------------------------------------- Plan
def build_plan(ctx, sol: Solution, run_id: Optional[str] = None, baselines: Optional[dict] = None) -> dict:
    cfg = ctx.cfg
    trips, jobs = _trips(ctx, sol), _kitchen_jobs(ctx, sol)
    usage = _kitchen_usage(ctx, jobs)
    lots_out, warnings = [], list(ctx.warnings)

    for lid, lc in ctx.lots.items():
        lot, c = lc.lot, lc.lot.unit_cost
        portions: list = []
        for t in lc.tiers:
            d = t["discount_pct"]
            u = sol.count(("s", lid, d))
            if u > 0:
                portions.append(_portion(lc, "SELL_REGULAR" if d == 0 else "MARKDOWN", u, u * t["price"], 0.0, {
                    "discount_pct": d, "unit_price": t["price"], "demand_cap": t["cap"],
                    "band_ratio": t["band_ratio"], "discount_value_thb": _r(u * (lot.price - t["price"]))}))
        k_units = k_rev = k_cost = 0.0
        k_jobs = []
        for j in jobs:
            k, k2 = j["primary_lots"].get(lid, 0), j["secondary_lots"].get(lid, 0)
            if k + k2 == 0:
                continue
            share = (k * c / j["_cost_primary"]) if (k and j["_cost_primary"] > 0) else 0.0
            k_units += k + k2
            k_rev += j["_revenue"] * share + j["_sec_credit"].get(lid, 0.0)
            k_cost += j["_utility"] * share
            k_jobs.append({"job_id": j["job_id"], "recipe_id": j["recipe_id"], "batches": j["batches"],
                           "primary_units": k, "secondary_units": k2, "due_by": j["due_by"]})
        if k_units:
            portions.append(_portion(lc, "KITCHEN", int(k_units), k_rev, k_cost, {"jobs": k_jobs}))
        for pid, trip in trips.items():
            u = trip["units"].get(lid, 0)
            if u == 0:
                continue
            kg = u * lc.weight_kg
            alloc = trip["_incurred"] * kg / trip["_kg"]
            pc = ctx.partners[pid]
            portions.append(_portion(lc, trip["partner_type"], u, pc.partner.buyback * kg, alloc + pc.handling * kg, {
                "partner_id": pid, "partner_name": trip["name"], "pickup_at": trip["pickup_at"], "kg": _r(kg, 3),
                "trip_allocated_thb": _r(alloc), "handling_thb": _r(pc.handling * kg),
                "buyback_thb": _r(pc.partner.buyback * kg)}))
        r_units = sol.count(("res", lid))
        if r_units:
            portions.append(_portion(lc, "UNRESOLVED", r_units, 0.0, 0.0, {"reason": "ไม่มี partner/วิธีใดรับได้ ต้องให้คนตัดสินใจ"}))
            warnings.append(f"A1_UNRESOLVED: lot {lid} เหลือ {r_units} หน่วยที่ไม่มีทางไป")

        total_units = sum(p["units"] for p in portions)
        binding = []
        for p in portions:
            if p["method"] in SALE_METHODS and p["units"] >= p["details"]["demand_cap"]:
                binding.append(f"DEMAND_CAP_REACHED:{p['details']['discount_pct']}%")
            if p["method"] == "KITCHEN":
                job_ids = {j["job_id"] for j in p["details"]["jobs"]}
                for j in jobs:
                    if j["job_id"] in job_ids and any(u["binding"] and u["department_id"] == j["department_id"]
                                                      and u["date"] == j["date"] for u in usage):
                        binding.append(f"KITCHEN_HOURS:{j['department_id']}@{j['date']}")
        lots_out.append({
            "lot_id": lid, "assessment_id": lot.assessment_id, "product_id": lot.product_id, "name": lc.product.name,
            "category": lc.product.category, "quantity": lot.quantity, "unit_cost": lot.unit_cost,
            "current_price": lot.price, "location": f"{lot.aisle or '-'} / {lot.shelf or '-'}",
            "expiration_date": lot.expiration_date.isoformat(), "days_to_expiry": days_to_expiry(lot, ctx.now),
            "risk_level": lot.risk_level, "risk_score": lot.risk_score,
            "cogs_thb": _r(lot.quantity * c), "units_planned": total_units, "portions": portions,
            "net_profit_thb": _r(sum(p["net_profit_thb"] for p in portions)),
            "explain": {"excluded": lc.excluded, "binding": sorted(set(binding))},
        })

    # ---- สรุปทั้ง run ----
    units_by: dict = defaultdict(int)
    kg_by: dict = defaultdict(float)
    for lo in lots_out:
        for p in lo["portions"]:
            key = f"MARKDOWN {p['details']['discount_pct']}%" if p["method"] == "MARKDOWN" else p["method"]
            units_by[key] += p["units"]
            kg_by[key] += p["weight_kg"]
    total_units = sum(units_by.values()) or 1
    revenue = sum(p["revenue_thb"] for lo in lots_out for p in lo["portions"])
    costs = sum(p["cost_thb"] for lo in lots_out for p in lo["portions"])
    cogs = sum(lo["cogs_thb"] for lo in lots_out)
    net = sum(lo["net_profit_thb"] for lo in lots_out)
    n_portions = sum(len(lo["portions"]) for lo in lots_out) + 1

    for t in trips.values():
        if t["cost_per_kg_thb"] > cfg.warn_trip_cost_per_kg:
            warnings.append(f"A2_TRIP_COST_PER_KG: {t['partner_id']} {t['cost_per_kg_thb']} บาท/kg ({t['kg']} kg)")
    for u in usage:
        if u["utilization"] >= cfg.warn_kitchen_utilization:
            warnings.append(f"W1_KITCHEN_NEAR_FULL: {u['department_id']} {u['date']} {u['utilization'] * 100:.0f}%")
    if sol.status != "optimal":
        warnings.append(f"A3_SOLVER_NOT_OPTIMAL: status={sol.status} gap={sol.gap}")

    for t in trips.values():
        t.pop("_incurred"); t.pop("_kg")
    for j in jobs:
        for k in [k for k in j if k.startswith("_")]:
            j.pop(k)

    return {
        "run_id": run_id or ctx.inputs.run_id, "reference_date": ctx.inputs.reference_date.isoformat(),
        "simulated_now": ctx.now.isoformat(), "model_version": cfg.model_version,
        "solver": {"name": "HiGHS", "status": sol.status, "gap": sol.gap, "time_ms": sol.time_ms},
        "lots": lots_out, "trips": list(trips.values()), "kitchen_jobs": jobs, "kitchen_usage": usage,
        "summary": {
            "lots": len(lots_out), "units": total_units if lots_out else 0,
            "split_pct_by_method": {k: _r(v / total_units * 100.0) for k, v in sorted(units_by.items(), key=lambda kv: -kv[1])},
            "units_by_method": dict(units_by), "kg_by_method": {k: _r(v, 3) for k, v in kg_by.items()},
            "gross_revenue_thb": _r(revenue), "route_costs_thb": _r(costs), "cogs_thb": _r(cogs),
            "net_recovery_thb": _r(revenue - costs), "net_profit_thb": _r(net),
            "unresolved_units": sol.unresolved_units,
            "reconciliation_gap_thb": _r(abs(sol.net_profit - net), 4),
            "reconciliation_ok": abs(sol.net_profit - net) <= 0.01 * n_portions,
        },
        "baselines": baselines or {}, "warnings": warnings,
    }


# ---------------------------------------------------------------- Baseline เปรียบเทียบ
def compute_baselines(ctx, sol: Solution) -> dict:
    """ผลถ้าไม่ใช้ Optimizer — ใช้บอกว่าแผนนี้ได้เงินดีกว่าเท่าไหร่ (กำไรสุทธิรวม COGS)"""
    do_nothing = 0.0
    for lc in ctx.lots.values():
        t0 = next((t for t in lc.tiers if t["discount_pct"] == 0), None)
        sold = min(lc.lot.quantity, t0["cap"]) if t0 else 0
        do_nothing += (sold * t0["price"] if t0 else 0.0) - lc.lot.quantity * lc.lot.unit_cost
    landfill = frozenset({"LANDFILL"})
    a = solve(ctx, Switches(markdown_levels=frozenset({0}), kitchen=False, partner_types=landfill))
    b = solve(ctx, Switches(kitchen=False, partner_types=landfill))
    row = lambda s: {"net_profit_thb": _r(s.net_profit), "unresolved_units": s.unresolved_units}
    return {
        "do_nothing_no_disposal_cost": {"net_profit_thb": _r(do_nothing)},
        "regular_price_then_landfill": row(a),
        "markdown_then_landfill": row(b),
        "optimized": row(sol),
        "improvement_vs_regular_then_landfill_thb": _r(sol.net_profit - a.net_profit),
    }
