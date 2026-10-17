"""เทรน Forecaster แล้วบันทึกโมเดล + ค่าความแม่น + feature importance ลง AI/risk_forecaster/models/

ใช้งาน (จากโฟลเดอร์ AI/risk_forecaster):
    python train_forecaster.py                                   # ใช้ data/mock_v3/training_dataset.csv
    python train_forecaster.py --data data/xxx/training_dataset.csv
"""
import argparse
import json
from pathlib import Path

import pandas as pd

from common import config
from forecaster.model import Forecaster


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=config.MOCK_DIR / "training_dataset.csv")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    print(f"เทรนจาก {args.data} ({len(df)} แถว)")
    fc = Forecaster().fit(df)
    fc.save()
    m = fc.metrics
    print("ประวัติ:", m["history"])
    print("แบ่งข้อมูล:", json.dumps(m["split"], ensure_ascii=False), "| แถว:", m["rows"])
    print("validation WAPE:", m["validation_wape"], "-> parameter", m["params"], "| ใช้", m["chosen"])
    print("test WAPE:", m["test_wape"])
    print("test WAPE แยกหมวด:", json.dumps(m["test_wape_by_category"], ensure_ascii=False))
    print("test WAPE แยกสินค้า:", json.dumps(m["test_wape_by_product"], ensure_ascii=False))
    print(f"FVA (ดีกว่า same-dow): {m['test_fva_pct']}%")
    print(f"bias: {m['test_bias_pct']}% (บวก = ทายเกิน, ลบ = ทายขาด) แยกหมวด:",
          json.dumps(m["test_bias_by_category"], ensure_ascii=False))
    print("coverage ช่วง 10-90% (ควรใกล้ 80%):",
          ", ".join(f"{k} วัน {v['coverage_pct']}%" for k, v in m["test_coverage_80"].items()))
    print("phi ตามจำนวนวัน:", m["phi_by_days"])
    print("lift ของการลดราคา (ลดทั้งวัน):", m["markdown_lift"])
    top = list(fc.feature_importance.items())[:8]
    print("feature สำคัญ (gain %):", ", ".join(f"{k} {v}" for k, v in top))
    print(f"บันทึกที่ {config.MODEL_DIR}")


if __name__ == "__main__":
    main()
