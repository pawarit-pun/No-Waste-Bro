"""Risk Scanner: ล็อตไหนจะขายไม่ทันก่อนหมดอายุ

ต่อล็อต:
  days_to_expiry  = expiration_date - reference_date
  วันที่ยังขายได้   = days_to_expiry + 1 (ขายได้ถึงสิ้นวันหมดอายุ: ประกาศ สธ. ฉบับ 367 "หลังจากวันที่ระบุไว้นั้น วางจำหน่ายไม่ได้")
  sellable_hours  = ชั่วโมงร้านเปิดที่เหลือจนสิ้นวันหมดอายุ (ร้านเปิด 08:00-22:00)
  สินค้าเดียวกันหลายล็อต แบ่งความต้องการทีละวัน: NEWEST_PICK_SHARE ไปที่ล็อตใหม่สุด ที่เหลือแบบ FIFO
  risk_score      = ของที่คาดว่าจะเหลือ / จำนวนคงเหลือ x 100
ระดับ: cutoff MEDIUM / HIGH / CRITICAL จาก models/risk_thresholds.json (calibrate_risk.py)
       หมดอายุแล้ว = CRITICAL เสมอ, วันสุดท้ายที่ยังเหลือของขยับขึ้น 1 ระดับ (ถ้า last_day_bump)
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from common import config
from risk_scanner import nb

BKK = ZoneInfo("Asia/Bangkok")

BUMP = {"LOW": "MEDIUM", "MEDIUM": "HIGH", "HIGH": "CRITICAL", "CRITICAL": "CRITICAL"}
HOURS_PER_DAY = config.STORE_CLOSE_HOUR - config.STORE_OPEN_HOUR


def risk_level(score, days_to_expiry, th):
    if days_to_expiry < 0 or score >= th["CRITICAL"]:
        return "CRITICAL"
    level = "HIGH" if score >= th["HIGH"] else "MEDIUM" if score >= th["MEDIUM"] else "LOW"
    if th.get("last_day_bump") and days_to_expiry == 0 and score > 0:
        level = BUMP[level]
    return level


def hours_used_today(reference_date, now=None):
    """ชั่วโมงร้านเปิดที่ผ่านไปแล้วของวันนี้ (สแกนก่อนเปิดร้าน หรือวันอ้างอิงไม่ใช่วันนี้ = 0)"""
    now = now or datetime.now(tz=BKK)
    if now.date() != reference_date:
        return 0.0
    used = now.hour + now.minute / 60 - config.STORE_OPEN_HOUR
    return float(min(max(used, 0.0), HOURS_PER_DAY))


def sellable_hours(days_to_expiry, used_today):
    if days_to_expiry < 0:
        return 0
    return int(round((days_to_expiry + 1) * HOURS_PER_DAY - used_today))


def allocate(plots, demand, ref, newest_share, priority=None, lift=1.0):
    """แบ่งความต้องการรายวันของสินค้าหนึ่งให้ล็อตที่ยังขายได้

    priority = lot_id ที่ลดราคา: ลูกค้าหยิบล็อตนี้ก่อน (ป้ายลดราคาชนะความชอบของใหม่) และยอดเพิ่มขึ้น x lift
    คืน sold (คาดว่าขายได้) และ directed (ความต้องการที่มาถึงล็อตนั้น ก่อนตัดด้วยจำนวนคงเหลือ) ต่อล็อต
    """
    remaining = {l["lot_id"]: float(l["current_quantity"]) for l in plots}
    expiry = {l["lot_id"]: date.fromisoformat(str(l["expiration_date"])[:10]) for l in plots}
    sold = defaultdict(float)
    directed = defaultdict(float)
    if not plots:
        return sold, directed
    last = max(expiry.values())
    day = ref
    while day <= last:
        want = demand.get((plots[0]["product_id"], day), 0.0)
        active = [l["lot_id"] for l in plots if expiry[l["lot_id"]] >= day]   # เรียงหมดอายุก่อนอยู่แล้ว
        if want > 0 and active:
            if priority in active:
                lifted = want * lift
                directed[priority] += lifted
                take = min(lifted, remaining[priority])
                remaining[priority] -= take
                sold[priority] += take
                want = max(0.0, want - take / lift)          # ส่วนที่ล็อตลดราคารับไม่ไหว กลับไปเป็นยอดปกติ
                active = [a for a in active if a != priority]
            if want > 0 and active:
                newest = active[-1]
                to_newest = want * newest_share if len(active) > 1 else 0.0
                # ส่วนที่ล็อตใหม่สุดรับไม่ไหวไหลกลับไปคิวแบบ FIFO
                directed[newest] += to_newest
                take = min(to_newest, remaining[newest])
                remaining[newest] -= take
                sold[newest] += take
                left = want - take
                for lot_id in active:
                    if left <= 0:
                        break
                    directed[lot_id] += left
                    take = min(left, remaining[lot_id])
                    remaining[lot_id] -= take
                    sold[lot_id] += take
                    left -= take
        day += timedelta(days=1)
    return sold, directed


def sellable_lots(plots, ref):
    return [l for l in plots if date.fromisoformat(str(l["expiration_date"])[:10]) >= ref]


def group_by_product(lots):
    by_product = defaultdict(list)
    for lot in lots:
        if lot["current_quantity"] > 0:
            by_product[lot["product_id"]].append(lot)
    for plots in by_product.values():
        plots.sort(key=lambda l: (str(l["expiration_date"]), l["lot_id"]))
    return by_product


def assess(lots, demand, phi_for, reference_date, thresholds=None, used_today=0.0,
           newest_share=config.NEWEST_PICK_SHARE):
    """lots = inventory_lots จาก scan-inputs, demand = {(product_id, date): mu}, phi_for(จำนวนวัน) -> phi

    คืน list ต่อล็อต: 'payload' (ส่ง POST /risk-assessments) + ค่าภายในที่ handoff ใช้ต่อ
    """
    th = thresholds or config.load_thresholds()
    ref = date.fromisoformat(str(reference_date)[:10])
    results = []
    for pid, plots in group_by_product(lots).items():
        sold, directed = allocate(sellable_lots(plots, ref), demand, ref, newest_share)
        for lot in plots:
            qty = int(lot["current_quantity"])
            exp = date.fromisoformat(str(lot["expiration_date"])[:10])
            dte = (exp - ref).days
            if dte < 0:
                total = avail = got = prob = 0.0
                phi_lot = phi_for(1)
            else:
                total = sum(demand.get((pid, ref + timedelta(days=i)), 0.0) for i in range(dte + 1))
                avail = directed.get(lot["lot_id"], 0.0)
                got = min(qty, sold.get(lot["lot_id"], 0.0))
                # ความไม่แน่นอนของยอดรวม (dte + 1) วัน: variance = phi_k x ความต้องการรวม
                phi_k = phi_for(dte + 1)
                phi_lot = phi_k * total / avail if avail > 0 else phi_k
                prob = nb.prob_at_least(qty, avail, phi_lot)
            leftover = qty - got
            score = 100.0 if dte < 0 else leftover / qty * 100
            payload = {
                "lot_id": lot["lot_id"],
                "days_to_expiry": dte,
                "sellable_hours": sellable_hours(dte, used_today),
                "quantity_at_assessment": qty,
                "forecast_daily_demand": round(total / (dte + 1), 2) if dte >= 0 else 0.0,
                "predicted_units_sold_before_expiry": round(got, 2),
                "predicted_leftover_units": round(leftover, 2),
                "sell_through_probability": round(prob, 4),
                "risk_score": round(score, 2),
                "risk_level": risk_level(score, dte, th),
            }
            results.append({"payload": payload, "lot": lot, "plots": plots, "available_demand": avail,
                            "phi_lot": phi_lot, "expired": dte < 0})
    results.sort(key=lambda r: (-r["payload"]["risk_score"], str(r["lot"]["expiration_date"]), r["lot"]["lot_id"]))
    return results
