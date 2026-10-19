"""ปรับเกณฑ์ระดับความเสี่ยงด้วยผลจริงรายล็อต (A5)

ใช้งาน (จากโฟลเดอร์ AI/risk_forecaster, หลัง train_forecaster.py):
    python calibrate_risk.py                      # ใช้ data/mock_v3 -> models/risk_thresholds.json

วิธี:
  1. ย้อนสแกนทุกวันในช่วง validation และ test: ทุกล็อตที่อยู่บนชั้นตอนเปิดร้าน (lot_daily.csv)
     -> Forecaster ที่เทรนด้วยข้อมูลก่อนช่วงนั้นเท่านั้น -> Risk Scanner -> score ที่ทำนาย
  2. score จริง = ของที่ทิ้งเพราะหมดอายุ (lot_outcomes.csv) / ของคงเหลือวันนั้น x 100
  3. ลองทุกชุด cutoff (MEDIUM < HIGH < CRITICAL) จาก CUTOFF_CANDIDATES และลองมี/ไม่มี "วันสุดท้ายขยับขึ้น 1 ระดับ"
     เลือกชุดที่ macro-F1 ระหว่างระดับที่ทำนายกับระดับจริงสูงสุดในช่วง validation
  4. รายงานผลของชุดที่เลือกบนช่วง test (ไม่ได้ใช้เลือก) + ตาราง calibration + precision / recall ของการส่งต่อ (HIGH ขึ้นไป)
"""
import argparse
import itertools
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

from common import config
from risk_scanner import risk
from forecaster.model import Forecaster, split_training_csv

LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def backtest_window(fc, model, product_daily, ctx, prod_df, lot_daily, outcomes, start, end, last_day, price):
    rows = []
    day = start
    while day <= end:
        today = lot_daily[lot_daily.date == day]
        today = today[today.expiration_date <= last_day]              # ต้องรู้ผลจริงตอนหมดอายุ
        if not today.empty:
            lots = [{"lot_id": r.lot_uid, "product_id": r.product_id, "expiration_date": r.expiration_date.date(),
                     "current_quantity": int(r.opening_qty), "current_selling_price": price[r.product_id]}
                    for r in today.itertuples()]
            targets = sorted({(l["product_id"], day + timedelta(days=i)) for l in lots
                              for i in range((pd.Timestamp(l["expiration_date"]) - day).days + 1)})
            mu = fc.predict_daily(product_daily, ctx, prod_df, day, targets, model=model)
            demand = {(r.product_id, r.date.date()): float(r.mu) for r in mu.itertuples()}
            for res in risk.assess(lots, demand, fc.phi_for, day.date(), config.DEFAULT_THRESHOLDS):
                p = res["payload"]
                expired = outcomes.at[p["lot_id"], "expired_qty"]
                rows.append({"date": day, "lot_uid": p["lot_id"], "product_id": res["lot"]["product_id"],
                             "days_to_expiry": p["days_to_expiry"], "qty": p["quantity_at_assessment"],
                             "pred_score": p["risk_score"], "actual_score": min(100.0, expired / p["quantity_at_assessment"] * 100)})
        day += timedelta(days=1)
    return pd.DataFrame(rows)


def levels(scores, dte, th, bump):
    out = []
    for s, d in zip(scores, dte):
        out.append(risk.risk_level(s, d, {**th, "last_day_bump": bump}))
    return np.array(out)


def evaluate(df, th, bump):
    pred = levels(df.pred_score, df.days_to_expiry, th, bump)
    actual = levels(df.actual_score, df.days_to_expiry, th, False)     # ระดับจริงไม่มีการขยับ
    fwd_pred = np.isin(pred, config.FORWARD_LEVELS)
    fwd_true = np.isin(actual, config.FORWARD_LEVELS)
    tp = int((fwd_pred & fwd_true).sum())
    return {
        # คิดครบทั้ง 4 ระดับเสมอ: ชุด cutoff ที่ทำให้บางระดับว่าง (เช่น MEDIUM = 0 -> ไม่มี LOW) จะได้คะแนนต่ำ
        "macro_f1": round(float(f1_score(actual, pred, labels=LEVELS, average="macro", zero_division=0)), 4),
        "forward_precision": round(float(tp / max(fwd_pred.sum(), 1)), 3),
        "forward_recall": round(float(tp / max(fwd_true.sum(), 1)), 3),
        "forwarded_share": round(float(fwd_pred.mean()), 3),
        "lots": int(len(df)),
    }


def calibration_table(df):
    bins = list(range(0, 101, 10))
    cut = pd.cut(df.pred_score, bins=bins, right=False, include_lowest=True, labels=[f"{b}-{b + 9}" for b in bins[:-1]])
    cut = cut.cat.add_categories(["100"]).fillna("100")
    g = df.groupby(cut, observed=True).agg(lots=("actual_score", "size"), actual_mean=("actual_score", "mean"),
                                           any_waste=("actual_score", lambda s: (s > 0).mean()))
    return {str(k): {"lots": int(r.lots), "actual_waste_pct_mean": round(r.actual_mean, 1),
                     "share_with_waste": round(r.any_waste, 3)} for k, r in g.iterrows()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=config.MOCK_DIR)
    args = ap.parse_args()

    fc = Forecaster.load()
    training = pd.read_csv(args.data / "training_dataset.csv")
    _, products, rows = fc.build_training(training)
    product_daily, ctx, _ = split_training_csv(training)
    prod_df = products[["product_id", "category", "shelf_life_days"]]
    lot_daily = pd.read_csv(args.data / "lot_daily.csv", parse_dates=["date", "expiration_date"])
    outcomes = pd.read_csv(args.data / "lot_outcomes.csv").set_index("lot_uid")
    price = training.groupby("product_id").regular_price.first().to_dict()
    last = pd.to_datetime(training.sale_date).max()

    print(f"ย้อนสแกน validation {fc.val_start.date()} -> {(fc.test_start - timedelta(days=1)).date()} "
          f"และ test {fc.test_start.date()} -> {last.date()}")
    val = backtest_window(fc, fc.model_until(rows, fc.val_start), product_daily, ctx, prod_df, lot_daily, outcomes,
                          fc.val_start, fc.test_start - timedelta(days=1), last, price)
    test = backtest_window(fc, fc.model_until(rows, fc.test_start), product_daily, ctx, prod_df, lot_daily, outcomes,
                           fc.test_start, last, last, price)

    grid = []
    for c in itertools.combinations(config.CUTOFF_CANDIDATES, 3):
        for bump in (True, False):
            th = {"MEDIUM": c[0], "HIGH": c[1], "CRITICAL": c[2]}
            grid.append((evaluate(val, th, bump)["macro_f1"], th, bump))
    grid.sort(key=lambda g: -g[0])
    best_f1, th, bump = grid[0]
    result = {
        **th, "last_day_bump": bump,
        "selected_by": "macro-F1 บนช่วง validation จาก CUTOFF_CANDIDATES",
        "candidates": list(config.CUTOFF_CANDIDATES),
        "validation": evaluate(val, th, bump),
        "test": evaluate(test, th, bump),
        "default_30_50_80_test": evaluate(test, {"MEDIUM": 30, "HIGH": 50, "CRITICAL": 80}, True),
        "top5_validation": [{"cutoffs": g[1], "last_day_bump": g[2], "macro_f1": g[0]} for g in grid[:5]],
        "calibration_table": calibration_table(pd.concat([val, test])),
        "forward_by_high_cutoff_test": {
            c: evaluate(test, {"MEDIUM": min(th["MEDIUM"], c), "HIGH": c, "CRITICAL": max(th["CRITICAL"], c + 1)}, bump)
            for c in config.CUTOFF_CANDIDATES[1:]},
    }
    config.MODEL_DIR.mkdir(exist_ok=True)
    (config.MODEL_DIR / "risk_thresholds.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                                           encoding="utf-8")
    pd.concat([val.assign(window="validation"), test.assign(window="test")]).to_csv(
        config.MODEL_DIR / "risk_backtest.csv", index=False)

    print(f"ล็อต-วันที่ใช้: validation {len(val)}, test {len(test)}")
    print(f"เลือก: MEDIUM >= {th['MEDIUM']} | HIGH >= {th['HIGH']} | CRITICAL >= {th['CRITICAL']} "
          f"| วันสุดท้ายขยับขึ้น 1 ระดับ: {bump}")
    print("validation:", result["validation"])
    print("test      :", result["test"])
    print("เทียบเกณฑ์เดิม 30/50/80 บน test:", result["default_30_50_80_test"])
    print("ตาราง calibration (score ที่ทำนาย -> % ทิ้งจริงเฉลี่ย):")
    for k, v in result["calibration_table"].items():
        print(f"   {k:>6}: {v['lots']:4d} ล็อต-วัน | ทิ้งจริงเฉลี่ย {v['actual_waste_pct_mean']:5.1f}% "
              f"| มีของทิ้ง {v['share_with_waste'] * 100:5.1f}%")
    print(f"บันทึกที่ {config.MODEL_DIR / 'risk_thresholds.json'}")


if __name__ == "__main__":
    main()
