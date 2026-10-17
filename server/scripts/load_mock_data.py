"""โหลด mock data จาก simulate.py ขึ้น Supabase (แทนที่ข้อมูลชุดเดิมทั้งหมด)

ใช้งาน (รันในโฟลเดอร์ server):
    python -m scripts.load_mock_data                     # ถามยืนยันก่อนลบ
    python -m scripts.load_mock_data --yes               # ไม่ถาม
    python -m scripts.load_mock_data --src scripts/forecast_data/data --demo-date 2026-10-16

ลำดับที่ทำ:
  1. demo_reset()  ล้างผลสแกน / decision / task / forecast ของรอบก่อน
  2. ลบ demo_lot_baseline, inventory_lots, product_daily, daily_context ทั้งหมด
  3. ใส่ daily_context.csv, product_daily.csv, inventory_lots_demo.csv (ทีละ 500 แถว)
  4. demo_snapshot(demo-date)  เก็บ lot ชุดใหม่เป็นค่าตั้งต้นของ demo
  5. demo_reset(demo-date)     ตั้ง sequence ของ lot_id ต่อจาก lot ล่าสุด (วันที่ของ lot ยังตรงกับ CSV)

ไม่แตะตาราง products / recipes / partners / kitchen (ต้องมี product_id ครบอยู่แล้ว)
รันซ้ำได้ ถ้าหยุดกลางทางให้รันใหม่ตั้งแต่ต้น
"""
import argparse
import csv
import sys
from pathlib import Path

from db.supabase import supabase

BATCH = 500
TABLES = [  # (ตาราง, ไฟล์, คอลัมน์ที่ใช้กรองตอนลบทั้งตาราง)
    ("daily_context", "daily_context.csv", "context_date"),
    ("product_daily", "product_daily.csv", "sale_date"),
    ("inventory_lots", "inventory_lots_demo.csv", "lot_id"),
]
TEXT_COLS = {"lot_id", "product_id", "location_aisle", "location_shelf", "ai_status",
             "context_date", "sale_date", "received_date", "expiration_date"}


def convert(col, v):
    if v == "":
        return None
    if col in TEXT_COLS:
        return v
    if v in ("True", "False"):
        return v == "True"
    try:
        return int(v)
    except ValueError:
        return float(v)


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [{k: convert(k, v) for k, v in row.items()} for row in csv.DictReader(f)]


def count(table):
    return supabase.table(table).select("*", count="exact", head=True).execute().count


def delete_all(table, col):
    if col.endswith("_date"):
        supabase.table(table).delete().gte(col, "1900-01-01").execute()
    else:
        supabase.table(table).delete().neq(col, "").execute()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=Path("scripts/forecast_data/data"))
    ap.add_argument("--demo-date", default="2026-10-16", help="วัน demo ที่ simulate.py ออกแบบ lot ไว้")
    ap.add_argument("--yes", action="store_true", help="ไม่ถามยืนยัน")
    args = ap.parse_args()

    data = {t: read(args.src / f) for t, f, _ in TABLES}
    print("Supabase ตอนนี้ -> ไฟล์ใหม่")
    for t, _, _ in TABLES:
        print(f"  {t}: {count(t)} -> {len(data[t])} แถว")
    pd_dates = sorted(r["sale_date"] for r in data["product_daily"])
    print(f"  product_daily ช่วง {pd_dates[0]} -> {pd_dates[-1]}")
    if not args.yes and input("ลบข้อมูลเดิมแล้วใส่ชุดใหม่? พิมพ์ y เพื่อยืนยัน: ").strip().lower() != "y":
        sys.exit("ยกเลิก ไม่ได้เปลี่ยนอะไร")

    print("1) demo_reset (ล้างผลรอบก่อน):", supabase.rpc("demo_reset", {"p_today": args.demo_date}).execute().data)

    print("2) ลบข้อมูลเดิม")
    supabase.table("demo_lot_baseline").delete().neq("lot_id", "").execute()
    for t, _, col in reversed(TABLES):
        delete_all(t, col)

    print("3) ใส่ข้อมูลใหม่")
    for t, _, _ in TABLES:
        rows = data[t]
        for i in range(0, len(rows), BATCH):
            supabase.table(t).insert(rows[i:i + BATCH]).execute()
        print(f"  {t}: {len(rows)} แถว")

    print("4) demo_snapshot:", supabase.rpc("demo_snapshot", {"p_ref": args.demo_date}).execute().data)
    print("5) demo_reset:", supabase.rpc("demo_reset", {"p_today": args.demo_date}).execute().data)

    print("ตรวจ:")
    ok = True
    for t, _, _ in TABLES:
        n = count(t)
        ok &= n == len(data[t])
        print(f"  {t}: {n} แถว {'OK' if n == len(data[t]) else 'ไม่ตรงกับไฟล์!'}")
    print("เสร็จ" if ok else "จำนวนแถวไม่ตรง ลองรันใหม่อีกครั้ง")


if __name__ == "__main__":
    main()
