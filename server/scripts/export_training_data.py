"""Export ข้อมูลสำหรับเทรน Risk Scanner + Forecast เป็น CSV ส่งให้ทีม AI

ใช้งาน (รันในโฟลเดอร์ server):
    python -m scripts.export_training_data                                  # ข้อมูลถึงเมื่อวาน (ตาม DEMO_DATE) -> ../AI/risk_forecaster/data
    python -m scripts.export_training_data --until 2026-10-15 --out ../AI/risk_forecaster/data

ไฟล์ที่ได้:
    product_daily.csv     สินค้า × วัน (ถึง --until)
    daily_context.csv     ปัจจัยรายวันทั้งหมดในตาราง (วันหลัง --until = ค่าพยากรณ์อากาศ)
    products.csv          ข้อมูลสินค้า
    training_dataset.csv  product_daily + daily_context + products join เป็นตารางเดียว
    data_dictionary.csv   คำอธิบายทุกคอลัมน์และที่มา
    README.md             วันที่ export ช่วงข้อมูล จำนวนแถว ข้อควรระวัง

คอลัมน์ชุดเดียวกับที่ GET /ai/scan-inputs ส่งตอนทำนาย ให้คำนวณ feature ด้วยวิธีเดียวกันทั้งสองทาง
"""
import argparse
import csv
from datetime import date, datetime, timedelta
from pathlib import Path

from core.dates import BKK, today_bkk
from db.helpers import fetch_all

PRODUCT_COLUMNS = ["product_id", "name", "category", "unit_of_measure", "regular_price",
                   "min_allowed_price", "shelf_life_days"]

DICTIONARY = [
    # table, column, description, source
    ("product_daily", "product_id + sale_date", "1 แถว = 1 สินค้า × 1 วัน (primary key)", "-"),
    ("product_daily", "opening_qty", "ของบนชั้นตอนเปิดร้าน 08:00", "simulation"),
    ("product_daily", "received_qty", "ของรับเข้าวันนั้น (supplier หรือครัวผลิต)", "simulation"),
    ("product_daily", "sold_qty", "ยอดขายจริงทั้งวัน = sold_full_price_qty + markdown_sold_qty", "simulation"),
    ("product_daily", "sold_full_price_qty", "ขายได้ในราคาปกติ", "simulation"),
    ("product_daily", "markdown_sold_qty", "ขายได้ในราคาลด", "simulation"),
    ("product_daily", "waste_qty", "ทิ้งเพราะหมดอายุ/เสีย", "simulation"),
    ("product_daily", "closing_qty", "คงเหลือตอนปิดร้าน 22:00 = opening + received - sold - waste", "คำนวณ (CHECK ใน DB)"),
    ("product_daily", "is_stockout", "ของหมดชั้นก่อนปิดร้าน: ยอดขายวันนั้นต่ำกว่า demand จริง (censored)", "simulation"),
    ("product_daily", "stockout_hour", "ชั่วโมงที่ของหมด (8-22) ว่าง = ไม่หมด", "simulation"),
    ("product_daily", "markdown_pct", "ส่วนลดสูงสุดของวัน (0 = ไม่ลด)", "simulation"),
    ("product_daily", "regular_price", "ราคาปกติ (บาท/หน่วย)", "products"),
    ("product_daily", "avg_selling_price", "ราคาขายเฉลี่ยถ่วงน้ำหนักของวัน (ว่าง = ขายไม่ได้เลย)", "คำนวณ"),
    ("product_daily", "latent_demand", "demand จริงก่อนถูกจำกัดด้วยสต็อก ใช้วัดผลโมเดลเท่านั้น ห้ามใช้เป็น feature", "simulation"),
    ("daily_context", "context_date", "วันที่ (primary key)", "-"),
    ("daily_context", "dow", "ISO day of week 1 = จันทร์ … 7 = อาทิตย์", "คำนวณ"),
    ("daily_context", "is_weekend", "เสาร์/อาทิตย์", "คำนวณ"),
    ("daily_context", "is_public_holiday / holiday_name", "วันหยุดราชการ/วันหยุดพิเศษที่มีผลกับ กทม.", "ประกาศ ครม. (รวมวันหยุดอุทกภัย 28-29 ก.ย. 2569)"),
    ("daily_context", "is_long_weekend_day", "อยู่ในช่วงหยุดต่อเนื่อง >= 3 วัน", "คำนวณ"),
    ("daily_context", "is_pension_day", "วันจ่ายบำนาญ", "ปฏิทินกรมบัญชีกลาง 2569"),
    ("daily_context", "is_private_payday", "วันเงินเดือนเอกชน", "ASSUMPTION: วันทำการสุดท้ายของเดือน"),
    ("daily_context", "days_since_any_payday", "จำนวนวันนับจากวันเงินเดือนออกล่าสุด (ข้าราชการรอบ 1/2, บำนาญ, เอกชน)", "ปฏิทินกรมบัญชีกลาง 2569 + ASSUMPTION"),
    ("daily_context", "rain_mm", "ฝนรวมทั้งวัน (มม.)", "Open-Meteo 13.75, 100.50: ค่าจริงถึงวันที่ export / ค่าพยากรณ์หลังจากนั้น"),
    ("daily_context", "rain_mm_16_20", "ฝนช่วง 16:00-20:00 ช่วงพีคคนซื้อของ (มม.)", "Open-Meteo hourly"),
    ("daily_context", "temp_max_c / temp_min_c", "อุณหภูมิสูงสุด/ต่ำสุด (°C)", "Open-Meteo"),
    ("products", "category", "DAIRY / BAKERY / MEAT / SEAFOOD / PRODUCE / READY_TO_EAT", "products"),
    ("products", "unit_of_measure", "หน่วยนับของ lot (PIECE / PACK)", "products"),
    ("products", "min_allowed_price", "ราคาต่ำสุดที่ลดได้", "products"),
    ("products", "shelf_life_days", "อายุสินค้านับจากวันรับเข้า/ผลิต (0 = ต้องขายให้หมดในวันนั้น)", "lot จริงใน inventory_lots / recipes"),
]


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in columns})


def main() -> None:
    parser = argparse.ArgumentParser(description="Export ข้อมูลเทรน Forecast เป็น CSV")
    parser.add_argument("--until", type=date.fromisoformat, default=None,
                        help="วันสุดท้ายของ product_daily (YYYY-MM-DD) ค่าเริ่มต้น = เมื่อวาน (ตาม DEMO_DATE)")
    parser.add_argument("--out", type=Path, default=Path("../AI/risk_forecaster/data"), help="โฟลเดอร์ปลายทาง (ค่าเริ่มต้น ../AI/risk_forecaster/data)")
    args = parser.parse_args()
    until = args.until or (today_bkk() - timedelta(days=1))
    args.out.mkdir(parents=True, exist_ok=True)

    product_daily = fetch_all("product_daily", order_by=("product_id", "sale_date"),
                              filters=[("lte", "sale_date", until.isoformat())])
    daily_context = fetch_all("daily_context", order_by=("context_date",))
    products = fetch_all("products", columns=", ".join(PRODUCT_COLUMNS), order_by=("product_id",))
    if not product_daily:
        raise SystemExit(f"ไม่มีข้อมูลใน product_daily ถึงวันที่ {until}")

    pd_columns = list(product_daily[0].keys())
    ctx_columns = list(daily_context[0].keys())
    write_csv(args.out / "product_daily.csv", product_daily, pd_columns)
    write_csv(args.out / "daily_context.csv", daily_context, ctx_columns)
    write_csv(args.out / "products.csv", products, PRODUCT_COLUMNS)

    ctx_by_date = {row["context_date"]: row for row in daily_context}
    product_by_id = {row["product_id"]: row for row in products}
    joined = []
    for row in product_daily:
        ctx = ctx_by_date.get(row["sale_date"], {})
        prod = product_by_id.get(row["product_id"], {})
        joined.append({**row,
                       **{k: v for k, v in ctx.items() if k != "context_date"},
                       **{k: v for k, v in prod.items() if k not in ("product_id", "regular_price")}})
    joined_columns = (pd_columns + [c for c in ctx_columns if c != "context_date"]
                      + [c for c in PRODUCT_COLUMNS if c not in ("product_id", "regular_price")])
    write_csv(args.out / "training_dataset.csv", joined, joined_columns)

    with (args.out / "data_dictionary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["table", "column", "description", "source"])
        writer.writerows(DICTIONARY)

    first, last = product_daily[0]["sale_date"], max(r["sale_date"] for r in product_daily)
    (args.out / "README.md").write_text(f"""# ข้อมูลเทรน Risk Scanner + Forecast

Export เมื่อ {datetime.now(BKK):%Y-%m-%d %H:%M} (เวลาไทย) ด้วย `python -m scripts.export_training_data`

| ไฟล์ | จำนวนแถว | ช่วงข้อมูล |
| --- | --- | --- |
| `product_daily.csv` | {len(product_daily)} | {first} ถึง {last} ({len(products)} สินค้า) |
| `daily_context.csv` | {len(daily_context)} | {daily_context[0]['context_date']} ถึง {daily_context[-1]['context_date']} |
| `products.csv` | {len(products)} | – |
| `training_dataset.csv` | {len(joined)} | product_daily + daily_context + products |

คำอธิบายคอลัมน์: `data_dictionary.csv`

## ข้อควรระวัง
- `latent_demand` ใช้วัดผลโมเดลเท่านั้น **ห้ามใช้เป็น feature** (ตอนใช้งานจริงไม่มีค่านี้)
- วันที่ `is_stockout = true` ยอดขายต่ำกว่า demand จริง (censored)
- `daily_context` หลัง {last} เป็นค่าพยากรณ์อากาศ ไม่ใช่ค่าจริง
- ตอนทำนาย `GET /api/v1/ai/scan-inputs` ส่งคอลัมน์ชุดเดียวกัน (`product_daily` ย้อนหลัง `history_days` วันถึงเมื่อวาน +
  `daily_context` ถึงวันหมดอายุล่าสุดของ lot) ให้คำนวณ feature ด้วยวิธีเดียวกับตอนเทรน
- อากาศ วันหยุด และวันเงินเดือนเป็นข้อมูลจริง ส่วนยอดขายเป็น simulation (ดู `server/README.md` หัวข้อ Forecast Data)
""", encoding="utf-8")
    print(f"✓ export {len(product_daily)} แถว ({first} ถึง {last}) -> {args.out.resolve()}")


if __name__ == "__main__":
    main()
