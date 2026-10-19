"""คัดลอก output ของ simulate.py มาไว้ใน AI/risk_forecaster/data/<ชื่อชุด> และสร้าง training_dataset.csv

ใช้งาน (จากโฟลเดอร์ AI/risk_forecaster):
    python tools/build_dataset.py ../../server/scripts/forecast_data/data data/mock_v3

training_dataset.csv = product_daily + daily_context + products (คอลัมน์เดียวกับ scripts.export_training_data ของ server)
lot_daily.csv / lot_outcomes.csv = ผลจริงรายล็อตจาก simulation ใช้ปรับเกณฑ์ risk เท่านั้น (ไม่เข้า Supabase)
"""
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

FILES = ["product_daily.csv", "daily_context.csv", "inventory_lots_demo.csv", "lot_daily.csv", "lot_outcomes.csv"]
PRODUCT_COLS = ["product_id", "name", "category", "unit_of_measure", "min_allowed_price", "shelf_life_days"]


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    dst.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        shutil.copyfile(src / f, dst / f)
    ref = Path(__file__).resolve().parent.parent / "data" / "reference" / "products.json"
    products = pd.DataFrame(json.loads(ref.read_text(encoding="utf-8")))[PRODUCT_COLS]
    pdy = pd.read_csv(dst / "product_daily.csv")
    ctx = pd.read_csv(dst / "daily_context.csv")
    df = (pdy.merge(ctx, left_on="sale_date", right_on="context_date").drop(columns="context_date")
             .merge(products, on="product_id"))
    df.to_csv(dst / "training_dataset.csv", index=False)
    print(f"{dst}: training_dataset {df.shape}, {pdy.sale_date.min()} -> {pdy.sale_date.max()}")


if __name__ == "__main__":
    main()
