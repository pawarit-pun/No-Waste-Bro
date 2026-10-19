"""ผลพยากรณ์ที่ส่งต่อให้ Optimizer (บันทึกผ่าน POST /risk-assessments, Optimizer อ่านจาก GET /ai/optimize-inputs)

shelf (ต่อล็อต HIGH / CRITICAL ที่ยังไม่หมดอายุ):
  "ลด x% ตั้งแต่เปิดร้านวันนี้จนหมดอายุ" (ตรงกับ server ที่ย้ายของที่ลดราคาไปเป็นล็อตใหม่ราคาลดค้างไว้)
  คำนวณทีละวัน: ล็อตที่ลดราคาได้ลูกค้าก่อน (ป้ายลดราคาชนะความชอบของใหม่) ยอดเพิ่มขึ้น x lift ของส่วนลด
  expected_qty / low_qty / high_qty  = ยอดที่ล็อตนี้ขายได้ (low-high = ช่วง 10-90% ของ Negative Binomial)
  lost_sales_other_lots              = ล็อตอื่นของสินค้าเดียวกันขายได้น้อยลงเท่าไร (Optimizer ควรหักออก)
  ล็อตหมดอายุ: shelf = [] (เหลือแค่ช่องทางกำจัด)

recipe_demand (ต่อรอบสแกน ต่อสูตรที่ active):
  ความต้องการเมนูในช่วงอายุเมนู - ของเมนูที่มีอยู่บนชั้นแล้ว เรียงตามรายได้ที่คาด (เลือกจากรายได้ ตามที่ทีมตกลง)
"""
from datetime import date, timedelta

from common import config
from risk_scanner import nb
from risk_scanner.risk import allocate, sellable_lots


def shelf_curve(result, product, lifts, demand, ref, phi_for, newest_share=config.NEWEST_PICK_SHARE):
    if result["expired"]:
        return []
    lot = result["lot"]
    lot_id = lot["lot_id"]
    qty = int(lot["current_quantity"])
    exp = date.fromisoformat(str(lot["expiration_date"])[:10])
    days = (exp - ref).days + 1
    plots = sellable_lots(result["plots"], ref)
    base_sold, base_dir = allocate(plots, demand, ref, newest_share)
    others_base = sum(v for k, v in base_sold.items() if k != lot_id)
    total = sum(demand.get((lot["product_id"], ref + timedelta(days=i)), 0.0) for i in range(days))
    phi_k = phi_for(days)
    price_now = float(lot["current_selling_price"])
    curve = []
    for pct in config.DISCOUNT_LEVELS:
        if pct and not product["allow_markdown"]:
            continue
        price = round(price_now * (1 - pct / 100), 2)
        if pct and product["min_allowed_price"] is not None and price < float(product["min_allowed_price"]) - 1e-9:
            continue
        if pct == 0:
            sold, directed, lost = base_sold, base_dir, 0.0
        else:
            sold, directed = allocate(plots, demand, ref, newest_share, priority=lot_id, lift=lifts.get(pct, 1.0))
            lost = max(0.0, others_base - sum(v for k, v in sold.items() if k != lot_id))
        mean = directed.get(lot_id, 0.0)
        phi_lot = phi_k * total * lifts.get(pct, 1.0) / mean if mean > 0 else phi_k
        curve.append({
            "discount_pct": pct,
            "price": price,
            "expected_qty": round(min(qty, sold.get(lot_id, 0.0)), 1),
            "low_qty": nb.quantile(0.10, mean, phi_lot, cap=qty),
            "high_qty": nb.quantile(0.90, mean, phi_lot, cap=qty),
            "applies_from": ref.isoformat(),
            "applies_until": exp.isoformat(),
            "lost_sales_other_lots": round(lost, 1),
        })
    return curve


def recipe_demand(recipes, products, demand, output_stock, ref, phi_for):
    rows = []
    for r in recipes:
        if not r["is_active"]:
            continue
        out_id = r["output_product_id"]
        window = int(r["shelf_life_days"]) + 1                      # เมนูขายได้กี่วัน (รวมวันที่ผลิต)
        gross = sum(demand.get((out_id, ref + timedelta(days=i)), 0.0) for i in range(window))
        stock = int(output_stock.get(out_id, 0))
        phi = phi_for(window)
        menu = max(0.0, gross - stock)
        rows.append({
            "recipe_id": r["recipe_id"],
            "output_product_id": out_id,
            "window_from": ref.isoformat(),
            "window_to": (ref + timedelta(days=window - 1)).isoformat(),
            "gross_demand": round(gross, 1),
            "current_stock": stock,
            "menu_qty": round(menu, 1),
            "low_qty": max(0, nb.quantile(0.10, gross, phi) - stock),
            "high_qty": max(0, nb.quantile(0.90, gross, phi) - stock),
            "expected_revenue": round(menu * float(products[out_id]["regular_price"]), 2),
        })
    rows.sort(key=lambda x: -x["expected_revenue"])
    return rows


def build(results, products, recipes, demand, lifts, reference_date, phi_for):
    """เติม shelf ให้ payload ของล็อต HIGH / CRITICAL และสร้าง recipe_demand ของรอบนี้"""
    ref = date.fromisoformat(str(reference_date)[:10])
    output_stock = {}
    for r in results:
        if not r["expired"]:
            pid = r["lot"]["product_id"]
            output_stock[pid] = output_stock.get(pid, 0) + int(r["lot"]["current_quantity"])
    for r in results:
        p = r["payload"]
        forward = p["risk_level"] in config.FORWARD_LEVELS
        p["shelf"] = shelf_curve(r, products[r["lot"]["product_id"]], lifts, demand, ref, phi_for) if forward else []
    return recipe_demand(recipes, products, demand, output_stock, ref, phi_for)
