"""ข้อมูลจำลองแบบ offline = คัดลอกจากภาพ Supabase ที่ให้มา (products, recipes, partners, kitchen, inventory_lots)
ใช้ทดสอบ Optimizer โดยไม่ต้องต่อเน็ต — ในการใช้งานจริงข้อมูลชุดนี้มาจาก GET /ai/optimize-inputs

หมายเหตุ: accepted_categories ของ P-ADG-01 และ P-LDF-01 ถูกตัดท้ายในภาพ ("...,PRODUC") จึงสมมติเป็นครบ 6 หมวด
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from ai_engine.forecaster.mock_forecaster import mock_forecast, to_at_risk_rows

ALL_CATS = ["DAIRY", "BAKERY", "MEAT", "SEAFOOD", "PRODUCE", "READY_TO_EAT"]

# (id, name, category, uom, base_cost, regular, min_allowed, markdown, kitchen, donation, net_value, net_unit)
_P = [
    ("BAK-001", "ขนมปังแซนวิช 480g", "BAKERY", "PIECE", 32.00, 40.00, 20.00, 1, 1, 1, 480, "G"),
    ("BAK-002", "เค้กกล้วยหอม 700g", "BAKERY", "PIECE", 65.19, 179.00, 89.50, 1, 0, 1, 700, "G"),
    ("BAK-003", "ขนมปังพุดดิ้ง 150g", "BAKERY", "PIECE", 11.99, 35.00, 17.50, 1, 0, 1, 150, "G"),
    ("DAI-001", "นมสดพาสเจอร์ไรส์ 830ml", "DAIRY", "PIECE", 38.95, 47.50, 23.75, 1, 1, 1, 830, "ML"),
    ("DAI-002", "โยเกิร์ต รสธรรมชาติ 125g", "DAIRY", "PIECE", 11.89, 14.50, 7.25, 1, 1, 1, 125, "G"),
    ("MEA-001", "อกไก่สด 500g", "MEAT", "PACK", 33.38, 44.50, 22.25, 1, 1, 0, 500, "G"),
    ("MEA-002", "เนื้อวัวสันนอก สเต็ก 500g", "MEAT", "PACK", 97.50, 130.00, 65.00, 1, 1, 0, 500, "G"),
    ("PRO-001", "กล้วยหอม 1kg", "PRODUCE", "PACK", 24.50, 35.00, 17.50, 1, 1, 1, 1, "KG"),
    ("PRO-002", "ผักกาดหอม 250g", "PRODUCE", "PACK", 16.63, 23.75, 11.88, 1, 1, 1, 250, "G"),
    ("RTE-001", "สเต็กเนื้อสันนอก พร้อมสลัด 300g", "READY_TO_EAT", "PIECE", 59.04, 169.00, 84.50, 1, 0, 1, 300, "G"),
    ("RTE-002", "สลัดอกไก่ย่าง 200g", "READY_TO_EAT", "PIECE", 20.80, 59.00, 29.50, 1, 0, 1, 200, "G"),
    ("RTE-003", "ข้าวหน้าแซลมอนย่าง 300g", "READY_TO_EAT", "PIECE", 36.46, 109.00, 54.50, 1, 0, 1, 300, "G"),
    ("RTE-004", "สมูทตี้กล้วยโยเกิร์ต 400ml", "READY_TO_EAT", "PIECE", 22.80, 65.00, 32.50, 1, 0, 0, 400, "ML"),
    ("SEA-001", "ปลาแซลมอนนอร์เวย์ ตัดชิ้น 300g", "SEAFOOD", "PACK", 83.16, 115.50, 57.75, 1, 1, 0, 300, "G"),
]

# (id, name, type, categories, days, start, end, min_days, min_kg, max_kg, fixed, travel, handling, buyback)
_PARTNERS = [
    ("P-ADG-01", "ไบโอเอเนอร์จี ก๊าซชีวภาพ", "ANAEROBIC_DIGESTION", ALL_CATS, [1, 2, 3, 4, 5, 6, 7], "07:00:00", "10:00:00", None, 100, 950, 1750, 100.64, 0.90, 0.0),
    ("P-ANI-01", "ฟาร์มอาหารสัตว์ทุ่งรวงทอง", "ANIMAL_FEED", ["BAKERY", "PRODUCE", "READY_TO_EAT"], [2, 3, 4, 6], "16:00:00", "18:00:00", None, 0, 1000, 1000, 37.74, 0.30, 0.92),
    ("P-CMP-01", "โรงงานปุ๋ยหมักเกษตรสุขดิน", "COMPOSTING", ["BAKERY", "PRODUCE", "READY_TO_EAT"], [1, 2, 4, 6], "13:00:00", "16:00:00", None, 100, 1000, 1600, 53.465, 0.60, 0.0),
    ("P-DON-01", "ธนาคารอาหารสยามสุข", "DONATION", ["BAKERY", "DAIRY", "PRODUCE"], [1, 3, 5, 6, 7], "09:00:00", "11:00:00", 2, 100, 800, 550, 0.0, 0.0, 0.0),
    ("P-LDF-01", "กรีนเมย์ ดังกอน", "LANDFILL", ALL_CATS, [1, 2, 3, 4, 5, 6], "20:00:00", "22:00:00", None, 0, 1000, 650, 78.625, 1.15, 0.0),
]

# (recipe_id, name, output, yield, prep_min, shelf_days, dept, utility)
_R = [
    ("RCP-001", "สเต็กเนื้อสันนอก พร้อมสลัด", "RTE-001", 10, 60, 0, "KITCHEN_DELI", 77.09),
    ("RCP-002", "สลัดอกไก่ย่าง", "RTE-002", 10, 45, 1, "KITCHEN_DELI", 51.33),
    ("RCP-003", "ข้าวหน้าแซลมอนย่าง", "RTE-003", 10, 45, 0, "KITCHEN_DELI", 45.14),
    ("RCP-004", "สมูทตี้กล้วยโยเกิร์ต", "RTE-004", 8, 20, 0, "KITCHEN_DELI", 17.23),
    ("RCP-005", "เค้กกล้วยหอม", "BAK-002", 4, 75, 3, "BAKERY_DEPT", 41.76),
    ("RCP-006", "ขนมปังพุดดิ้ง", "BAK-003", 12, 50, 3, "BAKERY_DEPT", 26.90),
]
# (recipe, product, qty, unit, primary)
_I = [
    ("RCP-001", "MEA-002", 2000, "G", 1), ("RCP-001", "PRO-002", 500, "G", 0),
    ("RCP-002", "MEA-001", 1000, "G", 1), ("RCP-002", "PRO-002", 750, "G", 0),
    ("RCP-003", "SEA-001", 900, "G", 1),
    ("RCP-004", "DAI-001", 800, "ML", 0), ("RCP-004", "DAI-002", 1000, "G", 1), ("RCP-004", "PRO-001", 1000, "G", 0),
    ("RCP-005", "PRO-001", 2000, "G", 1),
    ("RCP-006", "BAK-001", 480, "G", 1), ("RCP-006", "DAI-001", 1300, "ML", 1),
]
# (lot, product, received, expires, initial, current, unit_cost, aisle, shelf, price)
_L = [
    ("LOT-000001", "DAI-001", "2026-10-09", "2026-10-18", 180, 85, 38.95, "CHILL-A", "A-01", 47.50),
    ("LOT-000002", "DAI-001", "2026-10-15", "2026-10-24", 180, 172, 38.95, "CHILL-A", "A-01", 47.50),
    ("LOT-000003", "DAI-002", "2026-09-19", "2026-10-17", 200, 45, 11.89, "CHILL-A", "A-03", 14.50),
    ("LOT-000004", "MEA-001", "2026-10-13", "2026-10-17", 60, 18, 33.38, "MEAT-B", "B-01", 44.50),
    ("LOT-000005", "MEA-002", "2026-10-11", "2026-10-17", 30, 14, 97.50, "MEAT-B", "B-02", 130.00),
    ("LOT-000006", "SEA-001", "2026-10-14", "2026-10-16", 30, 12, 83.16, "SEAFOOD-C", "C-01", 115.50),
    ("LOT-000007", "PRO-001", "2026-10-12", "2026-10-17", 100, 32, 24.50, "PRODUCE-D", "D-04", 35.00),
    ("LOT-000008", "PRO-002", "2026-10-14", "2026-10-18", 60, 36, 16.63, "PRODUCE-D", "D-02", 23.75),
    ("LOT-000009", "BAK-001", "2026-10-13", "2026-10-17", 100, 42, 32.00, "BAKERY-E", "E-01", 40.00),
    ("LOT-000010", "BAK-002", "2026-10-14", "2026-10-17", 16, 11, 65.19, "BAKERY-E", "E-05", 179.00),
]


def snapshot_lots() -> list:
    """inventory_lots ที่ ai_status = IDLE (หน้าตาเดียวกับ scan-inputs)"""
    return [{"lot_id": l, "product_id": p, "received_date": rd, "expiration_date": ed, "initial_quantity": iq,
             "current_quantity": cq, "unit_cost": uc, "location_aisle": a, "location_shelf": s,
             "current_selling_price": pr, "ai_status": "IDLE"} for l, p, rd, ed, iq, cq, uc, a, s, pr in _L]


def build_offline_inputs(now: datetime, days_ahead: int = 1) -> tuple[dict, dict]:
    """คืน (inputs JSON ตาม Swagger ของ optimize-inputs, demand จาก mock forecaster)"""
    lots = snapshot_lots()
    forecast = mock_forecast(lots, now)
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"offline|{now.isoformat()}"))
    products = [{"product_id": p, "name": n, "category": c, "unit_of_measure": u, "net_content_value": nv,
                 "net_content_unit": nu, "base_cost": bc, "regular_price": rp, "min_allowed_price": mp,
                 "allow_markdown": bool(md), "allow_kitchen_repurposing": bool(k), "allow_donation": bool(d),
                 "allow_animal_feed": True, "allow_composting": True, "allow_anaerobic_digestion": True,
                 "allow_landfill": True}
                for p, n, c, u, bc, rp, mp, md, k, d, nv, nu in _P]
    partners = [{"partner_id": i, "name": n, "partner_type": t, "accepted_categories": cats, "pickup_days": days,
                 "pickup_time_start": s, "pickup_time_end": e, "min_days_before_expiry": md, "min_kg_per_pickup": mk,
                 "max_capacity_kg_per_pickup": xk, "fixed_cost_per_trip": f, "travel_cost_per_trip": tr,
                 "handling_fee_per_kg": h, "buyback_price_per_kg": b, "is_active": True}
                for i, n, t, cats, days, s, e, md, mk, xk, f, tr, h, b in _PARTNERS]
    recipes = [{"recipe_id": r, "name": n, "target_category": "", "output_product_id": o, "output_quantity": y,
                "estimated_prep_time_mins": m, "shelf_life_days": sh, "department_id": d, "utility_cost": u,
                "is_active": True,
                "ingredients": [{"recipe_id": r, "ingredient_product_id": p, "required_quantity": q,
                                 "unit_of_measure": un, "is_primary_ingredient": bool(pr)}
                                for rr, p, q, un, pr in _I if rr == r]}
               for r, n, o, y, m, sh, d, u in _R]
    kitchen = [{"department_id": d, "capacity_date": (now.date() + timedelta(days=i)).isoformat(),
                "available_hrs": 8.0, "booked_hrs": 0.0, "remaining_hrs": 8.0, "workload_status": "AVAILABLE"}
               for d in ("BAKERY_DEPT", "KITCHEN_DELI") for i in range(days_ahead + 1)]
    ref = now.date()
    meta = {p[0]: p for p in _P}
    stock = []
    for pid in sorted({i[1] for i in _I}):
        rows = [l for l in lots if l["product_id"] == pid and l["current_quantity"] > 0
                and date.fromisoformat(l["expiration_date"]) >= ref]
        rows.sort(key=lambda l: (l["expiration_date"], l["lot_id"]))
        nv, nu = meta[pid][10], meta[pid][11]
        per_unit = nv * (1000 if nu in ("KG", "L") else 1)
        units = sum(l["current_quantity"] for l in rows)
        stock.append({"product_id": pid, "name": meta[pid][1], "net_content_value": nv, "net_content_unit": nu,
                      "total_units": units, "total_content": units * per_unit,
                      "content_unit": "ML" if nu in ("ML", "L") else "G",
                      "lots": [{k: l[k] for k in ("lot_id", "current_quantity", "expiration_date",
                                                  "location_aisle", "location_shelf")} for l in rows]})
    return {"reference_date": ref.isoformat(), "run_id": run_id,
            "at_risk_lots": to_at_risk_rows(lots, forecast, run_id, None, now),
            "products": products, "recipes": recipes, "kitchen_capacity": kitchen,
            "donation_partners": partners, "ingredient_stock": stock}, forecast["demand"]
