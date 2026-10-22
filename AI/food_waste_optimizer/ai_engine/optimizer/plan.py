"""PART 6 — แปลงผล solver เป็น Plan ที่อ่านรู้เรื่อง: แต่ละ lot แบ่งไปทางไหนกี่ % ได้เงิน/เสียเงินเท่าไร เพราะอะไร

นิยามเงินต่อ portion:  net_profit = revenue - cost - cogs
  revenue = ขายหน้าร้าน | ส่วนแบ่งรายได้เมนู | buyback_price_per_kg x kg (ANIMAL_FEED)
  cost    = ค่าเที่ยว (fixed + travel แบ่งตาม kg) + handling x kg | ส่วนแบ่ง utility_cost (+ วัตถุดิบหลักจากสต็อกปกติ
            - วัตถุดิบรองที่ได้จาก lot เสี่ยง) | เงินที่ล็อตอื่นเสียไปเพราะลดราคา (lost_sales_other_lots
            x (ราคาเต็ม + ค่ากำจัดของที่เหลือเพิ่ม))
  cogs    = จำนวน x unit_cost ของ lot (ต้นทุนสินค้า; ในครัวคือ Cost_Primary)
net_recovery = revenue - cost  = เงินที่ได้กลับคืนจริง (ไม่นับต้นทุนสินค้าที่จ่ายไปแล้ว)

ของที่วางบนชั้น (shelf_units):
  ราคาปกติ: แบ่งเป็น 2 portion ที่รวมกันเท่ากับจำนวนบนชั้น
    SELL_REGULAR             units = floor(ยอดที่คาดว่าขายได้)  เงิน = ยอดคาด x ราคา (ค่าคาดหมาย)
    END_OF_LIFE (partner)    units = ที่เหลือ (ปัดขึ้น) แบ่งตาม y ของ solver   kg / เงิน = ค่าคาดหมายจาก solver
  ลดราคา: 1 portion MARKDOWN units = ทุกหน่วยบนชั้น (staff ติดป้ายทุกชิ้น, share_pct = สัดส่วนของ lot ที่ solver ให้ลดราคา)
    server แยกหน่วยที่ติดป้ายเป็น lot ใหม่ (IDLE) ของที่ขายไม่หมดถูกสแกน/วางแผนกำจัดใหม่รอบถัดไปด้วยจำนวนจริง
    เงินของส่วนที่คาดว่าเหลือ (ym ของ solver) เป็นค่าประมาณ อยู่ใน details.leftover_plan และรวมในเงินของ portion
  ทุกหน่วยจึงมีทางไปเป็นจำนวนเต็ม (H1) ส่วนเงินใช้ค่าคาดหมายที่ solver ใช้ตัดสิน รวมแล้วตรงกับ objective

partner (on-call) ดู config: โหมด BIN ค่าเที่ยวคิดเฉลี่ยต่อ kg และ partner_bins บอกว่าถังถึง min_kg_per_pickup แล้วหรือยัง
(call_now = เรียกรถได้เลย) โหมด DEDICATED เรียกรถเฉพาะของรอบนี้ จ่ายค่าเที่ยวเต็ม
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta
from typing import Optional

from ai_engine.optimizer.context import trip_key
from ai_engine.optimizer.rules import EPS, bin_pickup, ceil_minute, days_to_expiry, first_slot
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
def _provisional_lots(ctx, sol: Solution) -> set:
    """แผนชั่วคราว (rolling horizon): lot ขายราคาปกติที่หมดอายุวันอื่น และของที่คาดว่าเหลือไปถังของ partner โหมด BIN เท่านั้น
    -> ไม่มี decision รอบนี้ lot คืน IDLE ให้รอบสแกนวันถัดไปตัดสินใจใหม่ด้วยจำนวนจริง
    ค่ากำจัดต่อ kg เท่ากันไม่ว่าจะออก decision ตอนนี้หรือรอบหน้า จึงไม่มีเที่ยวฟรีที่กลายเป็น decision จริง (บั๊กเดิม)
    lot ที่มีทางอื่น (ดึงออก / ครัว / ทิ้ง) ของเหลือไปรถ DEDICATED หรือไปเที่ยวเต็มของถัง (w = 1: เรียกรถจริงรอบนี้
    และค่าเที่ยวถูกคิดรวมของ lot นี้แล้ว) ต้องออก decision รอบนี้"""
    out = set()
    for lid, lc in ctx.lots.items():
        if lc.lot.expiration_date <= ctx.now.date() or sol.count(("t", lid, 0)) != 1:
            continue
        leftover = [pid for pid in lc.eol if sol.amount(("y", lid, pid)) > 1e-6]
        others = any(k[1] == lid and sol.amount(k) > 1e-6 for k in sol.var if k[0] in ("x", "res", "rese", "u"))
        kitchen = any(sol.count(("k", j.job_id)) > 0 for j in ctx.jobs if j.anchor_lot_id == lid)
        full_call = any(_full_call(sol, p, lc.eol[p].date()) for p in leftover)
        if (leftover and not others and not kitchen and not full_call
                and all(ctx.partners[p].mode == "BIN" for p in leftover)):
            out.add(lid)
    return out


def _full_call(sol: Solution, pid: str, day) -> bool:
    """ถังของ partner วันนั้นเรียกรถเต็มเที่ยว (ของถึงปริมาณที่คุ้ม จ่ายค่าเรียกรถครั้งเดียว) ดู solver._full_call_cap"""
    return sol.count(("w", "bin", pid, day)) == 1


def _capped_kg(ctx, sol: Solution) -> dict:
    """kg ที่อยู่ใต้เพดานเที่ยวเต็มต่อ (partner BIN, วันรับ) ให้ตรงกับ solver._full_call_cap:
    ดึงออกจาก lot ที่ขายไม่ได้แล้ว (x ของ lot ไม่มี tier) + ของเหลือราคาปกติ (y) + ค่าประมาณของเหลือจากการลดราคา (ym)
    ใช้แบ่งค่าเรียกรถ 1 ครั้งตาม kg เมื่อเที่ยวนั้นเต็ม"""
    kg = defaultdict(float)
    for key in sol.var:
        if key[0] not in ("x", "y", "ym") or ctx.partners[key[2]].mode != "BIN" or sol.amount(key) <= 1e-6:
            continue
        lc = ctx.lots[key[1]]
        if key[0] == "x" and lc.tiers:
            continue
        day = ctx.partners[key[2]].pickup.date() if key[0] == "x" else lc.eol[key[2]].date()
        kg[(key[2], day)] += sol.amount(key) * lc.weight_kg
    return dict(kg)


def _trips(ctx, sol: Solution, provisional: set, capped: dict) -> dict:
    """1 เที่ยว = (partner, วันที่รับ) ของที่ออก decision รอบนี้: ดึงออกตอนนี้ (x) + ขายราคาปกติแล้วคาดว่าเหลือ (y)
    DEDICATED: เรียกรถเฉพาะ ค่าเที่ยวเต็ม
    BIN: ของเข้าถัง ค่าเที่ยว = ค่าเฉลี่ยต่อ kg x kg (เรียกรถเมื่อไรดู partner_bins)
         ถ้าของวันนั้นถึงปริมาณที่คุ้ม (full_call) = เรียกรถเต็มเที่ยว ค่าเรียกรถ 1 ครั้งแบ่งตาม kg ของที่ขายไม่ได้แล้ว
         (รวมของเหลือจากการลดราคาที่รอบหน้าตัดสินใจ: next_run_kg) ของที่ยังขายได้แต่ดึงออกตอนนี้จ่ายค่าเฉลี่ยต่อ kg
    ค่าเที่ยวจ่ายครั้งเดียวต่อเที่ยว ของเกินความจุ = รอบขนเพิ่ม (rounds) ไม่มีค่าเที่ยวเพิ่ม"""
    loads = defaultdict(lambda: {"now": {}, "eol": {}})
    for key in sol.var:
        if key[0] == "x" and sol.count(key) > 0:
            loads[trip_key(ctx, key[1], key[2], "NOW")]["now"][key[1]] = sol.count(key)
        elif key[0] == "y" and sol.amount(key) > 1e-6 and key[1] not in provisional:
            loads[trip_key(ctx, key[1], key[2], "END_OF_LIFE")]["eol"][key[1]] = sol.amount(key)
    trips = {}
    for (pid, day), ld in sorted(loads.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        kg_now = sum(u * ctx.lots[lid].weight_kg for lid, u in ld["now"].items())
        kg = kg_now + sum(u * ctx.lots[lid].weight_kg for lid, u in ld["eol"].items())
        # ของที่ยังขายได้แต่ดึงออกตอนนี้ไม่เข้าเพดานเที่ยวเต็ม (solver._full_call_cap) จ่ายค่าเฉลี่ยต่อ kg เสมอ
        kg_sellable = sum(u * ctx.lots[lid].weight_kg for lid, u in ld["now"].items() if ctx.lots[lid].tiers)
        pc, p = ctx.partners[pid], ctx.partners[pid].partner
        handling, buyback = pc.handling * kg, p.buyback * kg
        full = pc.mode == "BIN" and _full_call(sol, pid, day)
        group_kg = capped.get((pid, day), 0.0)
        if pc.mode == "DEDICATED":
            cost = pc.trip_cost
        elif full:                                         # ส่วนของรอบนี้ในค่าเรียกรถ + ของที่ยังขายได้ต่อ kg
            cost = pc.trip_cost * (kg - kg_sellable) / group_kg + pc.fee_per_kg * kg_sellable
        else:
            cost = pc.fee_per_kg * kg
        rounds = max(1, math.ceil(kg / pc.cap_kg - 1e-9))
        trip_id = f"{pid}@{day.isoformat()}"
        trips[trip_id] = {
            "trip_id": trip_id, "partner_id": pid, "name": p.name, "partner_type": p.partner_type, "mode": pc.mode,
            "full_call": full, "next_run_kg": _r(group_kg - (kg - kg_sellable), 3) if full else 0.0,
            "pickup_at": ctx.slots[(pid, day)].isoformat(), "kg": _r(kg, 3),
            "capacity_kg": _r(pc.cap_kg, 2), "min_kg": pc.min_kg if pc.mode == "DEDICATED" else 0.0,
            "rounds": rounds, "extra_rounds_free": rounds - 1,
            "fixed_cost_thb": _r(0.0 if pc.trip_cost == 0 else p.fixed),
            "travel_cost_thb": _r(0.0 if pc.trip_cost == 0 or p.partner_type == "DONATION" else p.travel),
            "fee_per_kg_thb": _r(pc.fee_per_kg),
            "trip_cost_thb": _r(cost), "handling_thb": _r(handling), "buyback_revenue_thb": _r(buyback),
            "total_cost_thb": _r(cost + handling), "net_cash_thb": _r(buyback - cost - handling),
            "cost_per_kg_thb": _r((cost + handling) / kg) if kg > 0 else 0.0, "_cost": cost,
            "units_now": ld["now"], "expected_units_end_of_life": {k: _r(v, 3) for k, v in ld["eol"].items()},
            "_kg": kg, "_kg_now": kg_now, "_day": day,
        }
    return trips


def _alloc(ctx, sol: Solution, pid: str, day, kg: float, trip: Optional[dict], capped: dict,
           under_cap: bool = True) -> float:
    """ค่าเที่ยวที่ส่วนนี้รับ
    DEDICATED = ค่าเที่ยวเต็มแบ่งตาม kg ของเที่ยวนั้น
    BIN = ค่าเฉลี่ยต่อ kg x kg ยกเว้นเที่ยวเต็ม: ของใต้เพดาน (ขายไม่ได้แล้ว) แบ่งค่าเรียกรถ 1 ครั้งตาม kg ของกลุ่ม"""
    pc = ctx.partners[pid]
    if pc.mode == "BIN":
        if under_cap and _full_call(sol, pid, day) and capped.get((pid, day), 0.0) > 0:
            return pc.trip_cost * kg / capped[(pid, day)]
        return pc.fee_per_kg * kg
    return trip["_cost"] * kg / trip["_kg"] if trip and trip["_kg"] > 0 else 0.0


def _partner_bins(ctx, trips: dict) -> list:
    """สถานะถังสะสมของต่อ partner (ของในถังแล้ว + ของที่ดึงออกรอบนี้)
    BIN เรียกรถเมื่อถังถึงปริมาณที่คุ้มที่สุด (ECONOMIC_SIZE) หรือของชิ้นที่รอนานสุดใกล้เกินเพดานเวลา (HOLD_LIMIT)
    call_now = รอบรับที่ควรเรียกคือรอบถัดไปเลย; ของที่ขายไม่หมด (END_OF_LIFE) เข้าถังทีหลัง ไม่นับในการเรียกรถรอบนี้"""
    now_kg, eol_kg, full_days = defaultdict(float), defaultdict(float), defaultdict(list)
    for t in trips.values():
        now_kg[t["partner_id"]] += t["_kg_now"]
        eol_kg[t["partner_id"]] += t["_kg"] - t["_kg_now"]
        if t["full_call"]:                                 # ของวันนั้นถึงปริมาณที่คุ้มเอง: เรียกรถเต็มเที่ยว
            full_days[t["partner_id"]].append(t["_day"].isoformat())
    lead = ctx.now + timedelta(minutes=ctx.cfg.lead_time_minutes)
    out = []
    for pid, pc in sorted(ctx.partners.items()):
        after = pc.bin_kg + now_kg[pid]
        # ของในถังรอตั้งแต่เมื่อไร (ไม่เกินตอนนี้: โหมด DEMO_DATE วันจำลองอาจก่อน created_at จริงของ decision)
        since = min(pc.bin_since, lead) if pc.bin_kg > EPS and pc.bin_since else (lead if after > EPS else None)
        must_call_by = since + timedelta(days=pc.max_wait_days) if since and pc.mode == "BIN" else None
        reason, call_at = None, None
        if pc.mode == "DEDICATED":
            call_at = pc.pickup if now_kg[pid] > 0 else None
            reason = "THIS_RUN" if call_at else None
        elif since is not None:
            size_wait = 0.0 if pc.trip_cost <= 0 else max(0.0, pc.expected_kg - after) / pc.daily_kg
            size_slot = first_slot(pc.partner, ceil_minute(lead + timedelta(days=size_wait)), ctx.cfg)
            if must_call_by <= lead:                       # ของรอเกินเพดานแล้ว: เรียกรอบที่เร็วที่สุด
                call_at, reason = first_slot(pc.partner, lead, ctx.cfg), "OVERDUE"
            else:                                          # รอบหลังถังถึงปริมาณที่คุ้ม ถ้าเกินเพดานใช้รอบสุดท้ายก่อนเพดาน
                call_at = bin_pickup(pc.partner, lead, size_wait,
                                     (must_call_by - lead).total_seconds() / 86400, ctx.cfg)
                reason = "ECONOMIC_SIZE" if call_at == size_slot else "HOLD_LIMIT"
        call_now = call_at is not None and call_at == first_slot(pc.partner, lead, ctx.cfg)
        out.append({
            "partner_id": pid, "partner_type": pc.partner.partner_type, "mode": pc.mode,
            "waste_kg_per_day": _r(pc.daily_kg, 3), "days_between_pickups": _r(pc.gap_days, 2),
            "calls_per_week": pc.calls_per_week,
            "call_interval_days": _r(pc.call_interval_days, 2) if math.isfinite(pc.call_interval_days) else None,
            "max_wait_days": _r(pc.max_wait_days, 2) if math.isfinite(pc.max_wait_days) else None,
            "economic_call_kg": _r(pc.expected_kg, 3), "expected_kg_per_trip": _r(pc.expected_kg, 3),
            "trip_cost_thb": _r(pc.trip_cost), "fee_per_kg_thb": _r(pc.fee_per_kg), "cost_per_kg_thb": _r(pc.cost_per_kg),
            "min_kg": pc.min_kg, "bin_before_kg": _r(pc.bin_kg, 3), "now_kg": _r(now_kg[pid], 3),
            "bin_after_kg": _r(after, 3), "end_of_life_kg_later": _r(eol_kg[pid], 3),
            "oldest_waiting_since": since.isoformat() if since else None,
            "must_call_by": must_call_by.isoformat() if must_call_by else None,
            "call_now": call_now, "call_reason": reason, "below_min_kg": bool(call_at) and after < pc.min_kg - 1e-6,
            "expected_call_at": call_at.isoformat() if call_at else None,
            "full_call_dates": sorted(full_days[pid]),
        })
    return out


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


def _markdown_portion(ctx, lc, sol: Solution, tier: dict, shelf: int, warnings: list, capped: dict) -> dict:
    """ลดราคา: staff ติดป้ายราคา tier["price"] ทุกหน่วยที่ solver ให้วางบนชั้น (shelf) ไม่ใช่เฉพาะยอดที่คาดว่าขายได้
    ของที่คาดว่าเหลืออยู่ใน lot ใหม่ที่ server แยกตอนติดป้าย (IDLE) รอบถัดไปวางแผนกำจัดใหม่ด้วยจำนวนจริง
    เงินของส่วนนั้นเป็นค่าประมาณจาก ym ของ solver (ถังของ partner โหมด BIN ค่าเที่ยวเฉลี่ยต่อ kg หรือส่วนแบ่งค่าเรียกรถ
    ถ้าของเหลือวันนั้นรวมกันถึงปริมาณที่คุ้ม) รวมในเงินของ portion นี้"""
    lot, lid, c, d = lc.lot, lc.lot.lot_id, lc.lot.unit_cost, tier["discount_pct"]
    segs = tier["segments"] + [(float(lot.quantity), 0.0)]
    exp_sold = sum(p * sol.amount(("s", lid, d, i)) for i, (_, p) in enumerate(segs))
    routes, buyback, cost = [], 0.0, 0.0
    for pid, when in lc.eol.items():
        units = sol.amount(("ym", lid, pid))
        if units <= 1e-6:
            continue
        pc = ctx.partners[pid]
        kg = units * lc.weight_kg
        alloc = _alloc(ctx, sol, pid, when.date(), kg, None, capped)
        buyback += pc.partner.buyback * kg
        cost += alloc + pc.handling * kg
        routes.append({"partner_id": pid, "partner_type": pc.partner.partner_type, "mode": pc.mode,
                       "full_call": _full_call(sol, pid, when.date()),
                       "pickup_at_estimate": ctx.slots[(pid, when.date())].isoformat(),
                       "expected_units": _r(units, 3), "kg": _r(kg, 3),
                       "trip_allocated_thb": _r(alloc), "handling_thb": _r(pc.handling * kg),
                       "buyback_thb": _r(pc.partner.buyback * kg)})
    no_route = sol.amount(("resem", lid))
    if no_route > 1e-6:
        warnings.append(f"A2_EOL_NO_ROUTE_NEXT_RUN: {lid} ลดราคาแล้วคาดว่าเหลือ {no_route:.1f} หน่วย ไม่มี partner รับ "
                        "รอบถัดไปต้องวางแผนกำจัดใหม่ / ให้ผู้จัดการตัดสินใจ")
    return _portion(lc, "MARKDOWN", shelf, exp_sold * tier["price"] + buyback, tier["lost_sales_cost"] + cost, shelf * c, {
        "discount_pct": d, "unit_price": tier["price"], "shelf_units": shelf,
        "expected_sold": _r(exp_sold, 3), "expected_sold_whole_lot": tier["expected_sold"],
        "forecast_expected": tier["expected"], "forecast_low": tier["low"], "forecast_high": tier["high"],
        "lost_sales_cost_thb": tier["lost_sales_cost"],
        "discount_value_thb": _r(exp_sold * (lot.price - tier["price"])),
        "expected_leftover": _r(shelf - exp_sold, 3),
        "leftover_plan": {
            "handled_by": "NEXT_RUN", "routes": routes, "no_route_units": _r(no_route, 3),
            "estimated_net_thb": _r(buyback - cost),
            "note": "ของที่ติดป้ายแล้วขายไม่หมดอยู่ใน lot ใหม่ (IDLE) รอบถัดไปสแกนและวางแผนกำจัดใหม่ด้วยจำนวนจริง "
                    "ตัวเลขที่นี่เป็นค่าประมาณ (ค่าเที่ยวเฉลี่ยต่อ kg ของถัง partner)"}})


# ---------------------------------------------------------------- Plan
def build_plan(ctx, sol: Solution, baselines: Optional[dict] = None) -> dict:
    cfg = ctx.cfg
    provisional_lots = _provisional_lots(ctx, sol)
    capped = _capped_kg(ctx, sol)
    trips, jobs = _trips(ctx, sol, provisional_lots, capped), _jobs(ctx, sol)
    usage = _kitchen_usage(ctx, jobs)
    lots_out, warnings = [], list(ctx.warnings)

    for lid, lc in ctx.lots.items():
        lot, c = lc.lot, lc.lot.unit_cost
        portions = []
        tier = next((t for t in lc.tiers if sol.count(("t", lid, t["discount_pct"])) == 1), None)
        shelf = sol.count(("shelf", lid))
        if tier is not None and shelf > 0 and tier["discount_pct"] > 0:
            portions.append(_markdown_portion(ctx, lc, sol, tier, shelf, warnings, capped))
        elif tier is not None and shelf > 0:
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
            portions.append(_portion(lc, "SELL_REGULAR", sold_units, exp_sold * tier["price"], 0.0, sold_units * c, {
                "discount_pct": d, "unit_price": tier["price"], "shelf_units": shelf,
                "expected_sold": _r(exp_sold, 3), "expected_sold_whole_lot": tier["expected_sold"],
                "forecast_expected": tier["expected"], "forecast_low": tier["low"], "forecast_high": tier["high"],
                "lost_sales_cost_thb": 0.0, "discount_value_thb": 0.0}))
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
                # แผนชั่วคราว: lot ไม่มี decision รอบนี้ คืน IDLE ให้รอบหน้าตัดสินใจใหม่ (ดู _provisional_lots)
                provisional = lid in provisional_lots
                day = lc.eol[pid].date()
                trip = None if provisional else trips[f"{pid}@{day.isoformat()}"]
                kg = exp_units * lc.weight_kg
                alloc = _alloc(ctx, sol, pid, day, kg, trip, capped)
                portions.append(_portion(lc, pc.partner.partner_type, units, pc.partner.buyback * kg,
                                         alloc + pc.handling * kg,
                                         units * c, {"timing": "END_OF_LIFE", "expected_units": _r(exp_units, 3),
                                                     "provisional": provisional, "mode": pc.mode,
                                                     "partner_id": pid, "partner_name": pc.partner.name,
                                                     "trip_id": trip["trip_id"] if trip else None,
                                                     "pickup_at": ctx.slots[(pid, day)].isoformat(),
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
            alloc = _alloc(ctx, sol, pid, pc.pickup.date(), kg, trip, capped, under_cap=not lc.tiers)
            portions.append(_portion(lc, trip["partner_type"], u, pc.partner.buyback * kg, alloc + pc.handling * kg,
                                     u * c, {"timing": "NOW", "mode": pc.mode,
                                             "partner_id": pid, "partner_name": trip["name"],
                                             "trip_id": trip["trip_id"], "pickup_at": trip["pickup_at"], "kg": _r(kg, 3),
                                             "trip_allocated_thb": _r(alloc), "handling_thb": _r(pc.handling * kg),
                                             "buyback_thb": _r(pc.partner.buyback * kg)}))
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

    bins = _partner_bins(ctx, trips)
    why = {"ECONOMIC_SIZE": "คาดว่าถึงปริมาณที่คุ้มก่อนรอบรับนี้", "HOLD_LIMIT": "ของรอใกล้เกินเพดานเวลา",
           "OVERDUE": "ของรอเกินเพดานเวลาแล้ว"}
    for b in bins:
        if b["call_reason"] == "ECONOMIC_SIZE" and b["bin_after_kg"] >= b["economic_call_kg"] - 1e-6:
            why_text = "ถึงปริมาณที่คุ้มแล้ว"
        else:
            why_text = why.get(b["call_reason"], "")
        if b["mode"] == "BIN" and b["call_now"]:
            warnings.append(f"A5_CALL_PARTNER {b['partner_id']}: ถัง {b['bin_after_kg']} kg (ปริมาณที่คุ้ม "
                            f"{b['economic_call_kg']} kg) {why_text} เรียกรถรอบ {b['expected_call_at']}")
        if b["below_min_kg"]:
            warnings.append(f"A6_BIN_BELOW_MIN_KG {b['partner_id']}: ต้องเรียกรถเพราะเพดานเวลาแต่ถังมี {b['bin_after_kg']} kg "
                            f"< ขั้นต่ำ {b['min_kg']:g} kg ให้ผู้จัดการคุยกับ partner")
    for t in trips.values():
        for k in [k for k in t if k.startswith("_")]:
            t.pop(k)
    for j in jobs:
        for k in [k for k in j if k.startswith("_")]:
            j.pop(k)

    return {
        "run_id": ctx.inputs.run_id, "reference_date": ctx.inputs.reference_date.isoformat(),
        "simulated_now": ctx.now.isoformat(), "model_version": cfg.model_version,
        "solver": {"name": "HiGHS", "status": sol.status, "gap": sol.gap, "time_ms": sol.time_ms},
        "lots": lots_out, "skipped_lots": ctx.skipped, "trips": list(trips.values()),
        "partner_bins": bins, "kitchen_jobs": jobs,
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
            "expected_leftover_next_run_units": _r(sum(p["details"]["expected_leftover"] for lo in lots_out
                                                       for p in lo["portions"] if p["method"] == "MARKDOWN"), 2),
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