"""PART 6 — แปลงผล solver เป็น Plan ที่อ่านรู้เรื่อง: แต่ละ lot แบ่งไปทางไหนกี่ % ได้เงิน/เสียเงินเท่าไร เพราะอะไร

นิยามเงินต่อ portion:  net_profit = revenue - cost - cogs
  revenue = ขายหน้าร้าน | ส่วนแบ่งรายได้เมนู | buyback_price_per_kg x kg (ANIMAL_FEED)
  cost    = ค่าเที่ยว (fixed + travel แบ่งตาม kg) + handling x kg | ส่วนแบ่ง utility_cost (+ วัตถุดิบหลักจากสต็อกปกติ
            - วัตถุดิบรองที่ได้จาก lot เสี่ยง) | กำไรที่ล็อตอื่นเสียไปเพราะลดราคา (lost_sales_other_lots)
  cogs    = จำนวน x unit_cost ของ lot (ต้นทุนสินค้า; ในครัวคือ Cost_Primary)
net_recovery = revenue - cost  = เงินที่ได้กลับคืนจริง (ไม่นับต้นทุนสินค้าที่จ่ายไปแล้ว)

ของที่วางบนชั้น (shelf_units) แบ่งเป็น 2 portion ที่รวมกันเท่ากับจำนวนบนชั้น:
  SELL_REGULAR / MARKDOWN  units = floor(ยอดที่คาดว่าขายได้)  เงิน = ยอดคาด x ราคา (ค่าคาดหมาย)
  END_OF_LIFE (partner)    units = ที่เหลือ (ปัดขึ้น) แบ่งตาม y ของ solver   kg / เงิน = ค่าคาดหมายจาก solver
  ทุกหน่วยจึงมีทางไปเป็นจำนวนเต็ม (H1) ส่วนเงินใช้ค่าคาดหมายที่ solver ใช้ตัดสิน รวมแล้วตรงกับ objective
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

from ai_engine.optimizer.context import trip_cost, trip_key, trip_min_kg
from ai_engine.optimizer.rules import days_to_expiry
from ai_engine.optimizer.solver import Solution, Switches, solve

SALE_METHODS = ("SELL_REGULAR", "MARKDOWN")
KITCHEN_METHODS = ("KITCHEN", "KITCHEN_INGREDIENT")


def _r(x: float, n: int = 2) -> float:
    return round(float(x), n)


def _portion(lc, method: str, units: int, revenue: float, cost: float, cogs: float, details: dict,
             weight_kg: Optional[float] = None) -> dict:
    kg = units * (lc.weight_kg or 0.0) if weight_kg is None else weight_kg
    return {"method": method, "units": int(units), "share_pct": _r(units / lc.lot.quantity * 100.0),
            "weight_kg": _r(kg, 4), "revenue_thb": _r(revenue), "cost_thb": _r(cost),
            "cogs_thb": _r(cogs), "net_profit_thb": _r(revenue - cost - cogs), "details": details}


# ---------------------------------------------------------------- เที่ยวรับของ
def _trips(ctx, sol: Solution) -> dict:
    """1 เที่ยว = (partner, วันที่รับ) ที่ solver เปิด รวมของที่ดึงออกตอนนี้ (x) + ของที่คาดว่าขายไม่หมด (y)"""
    loads = defaultdict(lambda: {"now": {}, "eol": {}})
    for key in sol.var:
        if key[0] == "x" and sol.count(key) > 0:
            loads[trip_key(ctx, key[1], key[2], "NOW")]["now"][key[1]] = sol.count(key)
        elif key[0] == "y" and sol.amount(key) > 1e-6:
            loads[trip_key(ctx, key[1], key[2], "END_OF_LIFE")]["eol"][key[1]] = sol.amount(key)
    trips = {}
    for (pid, day), ld in sorted(loads.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        kg = sum(u * ctx.lots[lid].weight_kg for part in ld.values() for lid, u in part.items())
        pc, p = ctx.partners[pid], ctx.partners[pid].partner
        handling, buyback = pc.handling * kg, p.buyback * kg
        cost = trip_cost(ctx, pid, day)
        trip_id = f"{pid}@{day.isoformat()}"
        trips[trip_id] = {
            "trip_id": trip_id, "partner_id": pid, "name": p.name, "partner_type": p.partner_type,
            "pickup_at": ctx.slots[(pid, day)].isoformat(), "kg": _r(kg, 3),
            "capacity_kg": _r(pc.cap_kg, 2), "min_kg": trip_min_kg(ctx, pid, day),
            "deferred": pc.pickup is None or day != pc.pickup.date(),
            "fixed_cost_thb": _r(0.0 if pc.trip_cost == 0 else p.fixed),
            "travel_cost_thb": _r(0.0 if pc.trip_cost == 0 or p.partner_type == "DONATION" else p.travel),
            "trip_cost_thb": _r(cost), "handling_thb": _r(handling), "buyback_revenue_thb": _r(buyback),
            "total_cost_thb": _r(cost + handling), "net_cash_thb": _r(buyback - cost - handling),
            "cost_per_kg_thb": _r((cost + handling) / kg) if kg > 0 else 0.0, "_cost": cost,
            "units_now": ld["now"], "expected_units_end_of_life": {k: _r(v, 3) for k, v in ld["eol"].items()},
            "_kg": kg, "_day": day,
        }
    return trips


def _split(total: int, weights: dict) -> dict:
    """แบ่งจำนวนเต็ม total ตามน้ำหนัก (largest remainder) รวมแล้วเท่า total พอดี"""
    w = sum(weights.values())
    if total <= 0 or w <= 1e-12:
        return {k: 0 for k in weights}
    raw = {k: total * v / w for k, v in weights.items()}
    out = {k: int(math.floor(v + 1e-9)) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: -(raw[k] - out[k]))[:total - sum(out.values())]:
        out[k] += 1
    return out


# ---------------------------------------------------------------- งานครัว
def _jobs(ctx, sol: Solution) -> list:
    inp = ctx.inputs
    by_rd = defaultdict(list)
    for j in ctx.jobs:
        if sol.count(("n", j.job_id)) > 0:
            by_rd[(j.recipe_id, j.day)].append(j)
    # ความต้องการวัตถุดิบ FEFO รวมทุกงาน (ไว้แบ่งปริมาณที่ตัดจากแต่ละ lot กลับให้แต่ละงาน)
    totals = defaultdict(float)
    for jobs in by_rd.values():
        for j in jobs:
            n = sol.count(("n", j.job_id))
            for pid, q, primary in j.others:
                totals[(pid, j.day, "P" if primary else "S")] += q * n
    lot_c_total = defaultdict(float)
    for key in sol.var:
        if key[0] == "c":
            lot_c_total[key[2]] += sol.amount(key)

    out = []
    for (rid, day), jobs in by_rd.items():
        r = inp.recipes[rid]
        price = inp.products[r.output_product_id].regular_price
        n_total = sum(sol.count(("n", j.job_id)) for j in jobs)
        rday = ctx.recipe_days[(rid, day)]
        sold_total = sum(p * sol.amount(("sold", rid, day, i)) for i, (_, p) in enumerate(rday.segments))
        for j in jobs:
            n, k = sol.count(("n", j.job_id)), sol.count(("k", j.job_id))
            anchor = ctx.lots[j.anchor_lot_id].lot
            sold = sold_total * n / n_total
            inputs, nonrisk_cost, credit = [], 0.0, 0.0
            inputs.append({"lot_id": anchor.lot_id, "product_id": j.anchor_product_id, "role": "ANCHOR",
                           "units": k, "cogs_thb": k * anchor.unit_cost})
            for pid, q, primary in j.others:
                rho = "P" if primary else "S"
                share = q * n / totals[(pid, day, rho)] if totals[(pid, day, rho)] > 0 else 0.0
                prod = inp.products[pid]
                for fl in ctx.fefo.get(pid, []):
                    c = sol.amount(("c", pid, fl.lot_id, day, rho)) * share          # หน่วยของสินค้า
                    if c <= 1e-9:
                        continue
                    row = {"lot_id": fl.lot_id, "product_id": pid, "role": "PRIMARY" if primary else "SECONDARY",
                           "content": _r(c * prod.content, 1), "at_risk": fl.at_risk}
                    if fl.at_risk:
                        u_total = sol.count(("u", fl.lot_id))
                        row["units"] = u_total * c / lot_c_total[fl.lot_id] if lot_c_total[fl.lot_id] > 0 else 0.0
                        row["cogs_thb"] = row["units"] * ctx.lots[fl.lot_id].lot.unit_cost
                        if not primary:
                            credit += prod.base_cost * c
                    else:
                        row["units"] = c
                        row["cogs_thb"] = 0.0
                        if primary:
                            nonrisk_cost += prod.base_cost * c
                    inputs.append(row)
            revenue, utility = sold * price, n * r.utility_cost
            cogs = 0.0  # คำนวณใหม่ใน _integerize หลังแบ่งหน่วยเป็นจำนวนเต็ม
            out.append({
                "job_id": j.job_id, "recipe_id": rid, "name": r.name, "department_id": r.department_id,
                "date": day.isoformat(), "start_at": j.start.isoformat(), "due_by": j.due_by(n).isoformat(),
                "anchor_lot_id": j.anchor_lot_id,
                "batches": n, "anchor_units": k, "hours": _r(n * j.hours_per_batch),
                "output_units": _r(n * r.output_qty), "expected_sold_units": _r(sold),
                "menu_demand_cap": _r(rday.cap_units), "sale_start": rday.sale_start.isoformat(), "output_product_id": r.output_product_id,
                "revenue_thb": _r(revenue), "utility_cost_thb": _r(utility),
                "primary_from_regular_stock_thb": _r(nonrisk_cost), "secondary_credit_thb": _r(credit),
                "cogs_thb": _r(cogs), "net_profit_thb": _r(revenue - utility - nonrisk_cost + credit - cogs),
                "inputs": [{k2: (_r(v, 3) if isinstance(v, float) else v) for k2, v in x.items()} for x in inputs],
                "_revenue": revenue, "_cost": utility + nonrisk_cost - credit, "_cogs": cogs, "_inputs": inputs,
            })
    _integerize(ctx, sol, out)
    return out


def _integerize(ctx, sol: Solution, jobs: list) -> None:
    """หน่วยของ lot เสี่ยงที่ถูก FEFO ตัด (u) แบ่งให้แต่ละงานเป็นจำนวนเต็มแบบ largest remainder ให้รวมแล้วเท่า u พอดี"""
    by_lot = defaultdict(list)
    for j in jobs:
        for x in j["_inputs"]:
            if x["role"] != "ANCHOR" and x.get("at_risk"):
                by_lot[x["lot_id"]].append(x)
    for lid, rows in by_lot.items():
        total = sol.count(("u", lid))
        base = [int(x["units"]) for x in rows]
        left = total - sum(base)
        order = sorted(range(len(rows)), key=lambda i: -(rows[i]["units"] - base[i]))
        for i in order[:max(0, left)]:
            base[i] += 1
        cost = ctx.lots[lid].lot.unit_cost
        for x, units in zip(rows, base):
            x["units"], x["cogs_thb"] = units, units * cost
    for j in jobs:
        j["_cogs"] = sum(x["cogs_thb"] for x in j["_inputs"])
        j["cogs_thb"] = _r(j["_cogs"])
        j["net_profit_thb"] = _r(j["_revenue"] - j["_cost"] - j["_cogs"])
        j["inputs"] = [{k: (_r(v, 3) if isinstance(v, float) else v) for k, v in x.items()} for x in j["_inputs"]]


def _kitchen_usage(ctx, jobs: list) -> list:
    used = defaultdict(float)
    for j in jobs:
        used[(j["department_id"], j["date"])] += j["hours"]
    out = []
    for (dept, day), hrs in sorted(used.items()):
        budget = next(dc.hours for (d, dy), dc in ctx.hours.items() if d == dept and dy.isoformat() == day)
        smallest = min((ctx.inputs.recipes[j.recipe_id].hours_per_batch for j in ctx.jobs
                        if ctx.inputs.recipes[j.recipe_id].department_id == dept), default=0.0)
        out.append({"department_id": dept, "date": day, "hours_used": _r(hrs), "hours_budget": _r(budget),
                    "utilization": _r(hrs / budget, 3) if budget > 0 else 0.0,
                    "binding": budget - hrs < smallest - 1e-9})
    return out


def _price_options(lc, portions: list) -> list:
    """เทียบทั้ง lot: ถ้าวางทั้ง lot ขายที่ราคาระดับนี้ lot จะได้/เสียเท่าไร (ยอดขายคาดจาก P10/P50/P90
    ส่วนที่ขายไม่หมดคิดด้วยเงินที่ได้คืนต่อหน่วยของทางกำจัดที่แผนใช้จริง) ใช้อธิบายว่าทำไมเลือก/ไม่เลือกลดราคา"""
    lot, c = lc.lot, lc.lot.unit_cost
    rest = [p for p in portions if p["method"] not in SALE_METHODS]
    rest_units = sum(p["details"].get("expected_units", p["units"]) for p in rest)
    # เงินที่ได้คืนต่อหน่วยของทางกำจัด: ไม่นับค่าเที่ยวที่แบ่งมา (เที่ยวเปิดอยู่แล้ว) ถ้าต้องเปิดเที่ยวใหม่ดู trips
    per_unit = sum(p["revenue_thb"] - p["cost_thb"] + p["details"].get("trip_allocated_thb", 0.0)
                   for p in rest) / rest_units if rest_units else 0.0
    chosen = next((p["details"]["discount_pct"] for p in portions if p["method"] in SALE_METHODS), None)
    out = []
    for t in lc.tiers:
        sold = t["expected_sold"]
        net = sold * t["price"] - t["lost_sales_cost"] - lot.quantity * c + (lot.quantity - sold) * per_unit
        out.append({"discount_pct": t["discount_pct"], "price": t["price"], "expected_sold": _r(sold),
                    "lot_net_profit_thb": _r(net), "chosen": t["discount_pct"] == chosen,
                    "note": "ไม่รวมค่าเที่ยวรถ partner ที่อาจต้องเปิดเพิ่ม"})
    return out


# ---------------------------------------------------------------- Plan
def build_plan(ctx, sol: Solution, baselines: Optional[dict] = None) -> dict:
    cfg = ctx.cfg
    trips, jobs = _trips(ctx, sol), _jobs(ctx, sol)
    usage = _kitchen_usage(ctx, jobs)
    lots_out, warnings = [], list(ctx.warnings)

    for lid, lc in ctx.lots.items():
        lot, c = lc.lot, lc.lot.unit_cost
        portions = []
        tier = next((t for t in lc.tiers if sol.count(("t", lid, t["discount_pct"])) == 1), None)
        shelf = sol.count(("shelf", lid))
        if tier is not None and shelf > 0:
            d = tier["discount_pct"]
            segs = tier["segments"] + [(float(lot.quantity), 0.0)]
            exp_sold = sum(p * sol.amount(("s", lid, d, i)) for i, (_, p) in enumerate(segs))
            sold_units = min(shelf, int(math.floor(exp_sold + 1e-6)))
            parts = {("y", pid): sol.amount(("y", lid, pid)) for pid in lc.eol}
            parts[("rese",)] = sol.amount(("rese", lid))
            parts = {k: v for k, v in parts.items() if v > 1e-6}
            eol_units = _split(shelf - sold_units, parts)
            if shelf - sold_units > 0 and not parts:            # ปัดเศษล้วน ๆ: คืนให้ฝั่งขาย
                sold_units = shelf
            portions.append(_portion(lc, "SELL_REGULAR" if d == 0 else "MARKDOWN", sold_units, exp_sold * tier["price"],
                                     tier["lost_sales_cost"], sold_units * c, {
                "discount_pct": d, "unit_price": tier["price"], "shelf_units": shelf,
                "expected_sold": _r(exp_sold, 3), "expected_sold_whole_lot": tier["expected_sold"],
                "forecast_expected": tier["expected"], "forecast_low": tier["low"], "forecast_high": tier["high"],
                "lost_sales_cost_thb": tier["lost_sales_cost"],
                "discount_value_thb": _r(exp_sold * (lot.price - tier["price"]))}))
            for key, units in eol_units.items():
                exp_units = parts[key]
                if key[0] == "rese":
                    portions.append(_portion(lc, "UNRESOLVED", units, 0.0, 0.0, units * c, {
                        "timing": "END_OF_LIFE", "expected_units": _r(exp_units, 3),
                        "reason": "ของที่ขายไม่หมดไม่มี partner รับหลังหมดเวลาขาย ต้องทิ้งเองในร้าน / ให้ผู้จัดการตัดสินใจ"},
                        weight_kg=exp_units * (lc.weight_kg or 0.0)))
                    warnings.append(f"A2_EOL_NO_ROUTE: {lid} คาดว่าเหลือ {exp_units:.1f} หน่วยหลังหมดเวลาขาย ไม่มี partner รับ")
                    continue
                pid = key[1]
                pc = ctx.partners[pid]
                trip = trips[f"{pid}@{lc.eol[pid].date().isoformat()}"]
                kg = exp_units * lc.weight_kg
                alloc = trip["_cost"] * kg / trip["_kg"]
                # เที่ยววันถัดไปที่ไม่ได้คิดค่าเที่ยวเต็ม = แผนชั่วคราว (rolling horizon) ไม่ออก decision รอบนี้
                provisional = trip["deferred"] and ctx.cfg.deferred_trip_cost_share < 1.0
                portions.append(_portion(lc, trip["partner_type"], units, pc.partner.buyback * kg, alloc + pc.handling * kg,
                                         units * c, {"timing": "END_OF_LIFE", "expected_units": _r(exp_units, 3),
                                                     "provisional": provisional,
                                                     "partner_id": pid, "partner_name": trip["name"],
                                                     "trip_id": trip["trip_id"], "pickup_at": trip["pickup_at"],
                                                     "kg": _r(kg, 3), "trip_allocated_thb": _r(alloc),
                                                     "handling_thb": _r(pc.handling * kg),
                                                     "buyback_thb": _r(pc.partner.buyback * kg)}, weight_kg=kg))
        for j in jobs:                                         # ส่วนที่เข้าครัว (lot หลัก หรือถูก FEFO ตัดเป็นวัตถุดิบ)
            mine = [x for x in j["_inputs"] if x["lot_id"] == lid and "cogs_thb" in x and x.get("at_risk", True)]
            if not mine:
                continue
            units = int(sum(x["units"] for x in mine))
            cogs = sum(x["cogs_thb"] for x in mine)
            share = cogs / j["_cogs"] if j["_cogs"] > 0 else 0.0
            role = "ANCHOR" if any(x["role"] == "ANCHOR" for x in mine) else mine[0]["role"]
            portions.append(_portion(lc, "KITCHEN" if role == "ANCHOR" else "KITCHEN_INGREDIENT", units,
                                     j["_revenue"] * share, j["_cost"] * share, cogs,
                                     {"job_id": j["job_id"], "recipe_id": j["recipe_id"], "role": role,
                                      "batches": j["batches"], "due_by": j["due_by"], "anchor_lot_id": j["anchor_lot_id"]}))
        for pid in lc.partner_ok:                              # ดึงออกจากชั้นตอนนี้
            u = sol.count(("x", lid, pid))
            if u == 0:
                continue
            pc = ctx.partners[pid]
            trip = trips[f"{pid}@{pc.pickup.date().isoformat()}"]
            kg = u * lc.weight_kg
            alloc = trip["_cost"] * kg / trip["_kg"]
            portions.append(_portion(lc, trip["partner_type"], u, pc.partner.buyback * kg, alloc + pc.handling * kg,
                                     u * c, {"timing": "NOW", "partner_id": pid, "partner_name": trip["name"],
                                             "trip_id": trip["trip_id"], "pickup_at": trip["pickup_at"], "kg": _r(kg, 3),
                                             "trip_allocated_thb": _r(alloc), "handling_thb": _r(pc.handling * kg),
                                             "buyback_thb": _r(pc.partner.buyback * kg)}))
        # แผนกำจัดวันถัดไปเป็น "ชั่วคราว" ได้ก็ต่อเมื่อทั้ง lot ถูกคืน IDLE ให้สแกนใหม่ (ไม่มีทางอื่นที่ออก decision)
        # ถ้า lot มี decision อื่น (ลดราคา / ครัว / partner วันนี้) lot จะไม่ถูกสแกนอีก -> ต้องออก decision กำจัดเลย
        if any(p["details"].get("provisional") for p in portions) and not all(
                p["method"] == "SELL_REGULAR" or p["details"].get("provisional") for p in portions):
            for p in portions:
                if p["details"].get("provisional"):
                    p["details"]["provisional"] = False
                    p["details"]["committed_because"] = "lot มี decision อื่นแล้ว จะไม่ถูกสแกนซ้ำ"
        r_units = sol.count(("res", lid))
        if r_units:
            portions.append(_portion(lc, "UNRESOLVED", r_units, 0.0, 0.0, r_units * c,
                                     {"reason": "ไม่มี partner หรือวิธีใดรับได้ภายในกฎ ต้องให้ผู้จัดการตัดสินใจ"}))
            warnings.append(f"A2_UNRESOLVED: {lid} เหลือ {r_units} หน่วยที่ไม่มีทางไป")

        binding = sorted({f"SHELF_WHOLE_LOT:{p['details']['discount_pct']}%" for p in portions
                          if p["method"] in SALE_METHODS and p["details"]["shelf_units"] >= lot.quantity}
                         | {f"KITCHEN_HOURS:{j['department_id']}@{j['date']}" for p in portions
                            if p["method"] in KITCHEN_METHODS for j in jobs
                            if j["job_id"] == p["details"]["job_id"] and any(
                                u["binding"] and u["department_id"] == j["department_id"] and u["date"] == j["date"]
                                for u in usage)})
        lots_out.append({
            "lot_id": lid, "assessment_id": lot.assessment_id, "product_id": lot.product_id, "name": lc.product.name,
            "category": lc.product.category, "quantity": lot.quantity, "unit_cost": lot.unit_cost,
            "current_price": lot.price, "location": f"{lot.aisle or '-'} / {lot.shelf_loc or '-'}",
            "expiration_date": lot.expiration_date.isoformat(),
            "days_to_expiry": days_to_expiry(lot, ctx.now.date()), "risk_level": lot.risk_level,
            "risk_score": lot.risk_score, "demand_source": lc.demand_source, "demand_fraction": lc.demand_fraction,
            "cogs_thb": _r(lot.quantity * c), "units_planned": sum(p["units"] for p in portions),
            "portions": portions, "net_profit_thb": _r(sum(p["net_profit_thb"] for p in portions)),
            "explain": {"excluded": lc.excluded, "binding": binding, "notes": lc.notes,
                        "price_options": _price_options(lc, portions)},
        })

    units_by, kg_by = defaultdict(int), defaultdict(float)
    for lo in lots_out:
        for p in lo["portions"]:
            key = f"MARKDOWN {p['details']['discount_pct']}%" if p["method"] == "MARKDOWN" else p["method"]
            units_by[key] += p["units"]
            kg_by[key] += p["weight_kg"]
    total_units = sum(units_by.values())
    revenue = sum(p["revenue_thb"] for lo in lots_out for p in lo["portions"])
    costs = sum(p["cost_thb"] for lo in lots_out for p in lo["portions"])
    cogs = sum(lo["cogs_thb"] for lo in lots_out)
    net = sum(lo["net_profit_thb"] for lo in lots_out)
    n_portions = sum(len(lo["portions"]) for lo in lots_out) + 1

    for t in trips.values():
        if t["cost_per_kg_thb"] > cfg.warn_trip_cost_per_kg:
            warnings.append(f"A3_TRIP_COST_PER_KG {t['partner_id']}: {t['cost_per_kg_thb']} บาท/kg ({t['kg']} kg)")
    for u in usage:
        if u["utilization"] >= cfg.warn_kitchen_utilization:
            warnings.append(f"W1_KITCHEN_NEAR_FULL {u['department_id']} {u['date']} {u['utilization'] * 100:.0f}%")
    for lo in lots_out:
        for note in lo["explain"]["notes"]:
            warnings.append(f"{lo['lot_id']}: {note}")
    if sol.status != "optimal":
        warnings.append(f"A4_SOLVER_NOT_OPTIMAL status={sol.status} gap={sol.gap}")

    for t in trips.values():
        t.pop("_kg")
        t.pop("_day")
        t.pop("_cost")
    for j in jobs:
        for k in [k for k in j if k.startswith("_")]:
            j.pop(k)

    return {
        "run_id": ctx.inputs.run_id, "reference_date": ctx.inputs.reference_date.isoformat(),
        "simulated_now": ctx.now.isoformat(), "model_version": cfg.model_version,
        "solver": {"name": "HiGHS", "status": sol.status, "gap": sol.gap, "time_ms": sol.time_ms},
        "lots": lots_out, "skipped_lots": ctx.skipped, "trips": list(trips.values()), "kitchen_jobs": jobs,
        "kitchen_usage": usage,
        "recipes": {rid: s for rid, s in ctx.recipe_status.items()},
        "summary": {
            "lots": len(lots_out), "units": total_units,
            "split_pct_by_method": {k: _r(v / total_units * 100.0) for k, v in sorted(units_by.items(), key=lambda kv: -kv[1])}
            if total_units else {},
            "units_by_method": dict(units_by), "kg_by_method": {k: _r(v, 3) for k, v in kg_by.items()},
            "gross_revenue_thb": _r(revenue), "route_costs_thb": _r(costs), "cogs_thb": _r(cogs),
            "net_recovery_thb": _r(revenue - costs), "net_profit_thb": _r(net),
            "unresolved_units": sol.unresolved_units,
            "shelf_units": sum(p["details"]["shelf_units"] for lo in lots_out for p in lo["portions"] if p["method"] in SALE_METHODS),
            "expected_sold_units": _r(sum(p["details"]["expected_sold"] for lo in lots_out for p in lo["portions"]
                                          if p["method"] in SALE_METHODS), 2),
            "expected_end_of_life_units": _r(sum(p["details"]["expected_units"] for lo in lots_out for p in lo["portions"]
                                                 if p["details"].get("timing") == "END_OF_LIFE"), 2),
            "reconciliation_gap_thb": _r(abs(sol.net_profit - net), 4),
            "reconciliation_ok": abs(sol.net_profit - net) <= 0.01 * n_portions,
        },
        "baselines": baselines or {}, "warnings": warnings,
    }


# ---------------------------------------------------------------- Baseline
def compute_baselines(ctx, sol: Solution) -> dict:
    """ผลถ้าไม่ใช้ Optimizer เทียบกำไรสุทธิ (รวมต้นทุนสินค้า) ทุกตัวใช้โมเดลยอดขายเดียวกัน (P10/P50/P90)"""
    do_nothing = 0.0
    for lc in ctx.lots.values():
        t0 = next((t for t in lc.tiers if t["discount_pct"] == 0), None)
        sold = t0["expected_sold"] if t0 else 0.0
        do_nothing += (sold * t0["price"] if t0 else 0.0) - lc.lot.quantity * lc.lot.unit_cost
    landfill = frozenset({"LANDFILL"})
    a = solve(ctx, Switches(discounts=frozenset({0}), kitchen=False, partner_types=landfill))
    b = solve(ctx, Switches(kitchen=False, partner_types=landfill))
    row = lambda s: {"net_profit_thb": _r(s.net_profit), "unresolved_units": s.unresolved_units}
    return {
        "do_nothing_no_disposal_cost": {"net_profit_thb": _r(do_nothing)},
        "regular_price_then_landfill": row(a),
        "markdown_then_landfill": row(b),
        "optimized": row(sol),
        "improvement_vs_regular_then_landfill_thb": _r(sol.net_profit - a.net_profit),
    }