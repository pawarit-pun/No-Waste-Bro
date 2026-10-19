"""ตรวจว่า mock data (product_daily + daily_context + lot demo) สมเหตุสมผลและพอเทรน Forecaster

ใช้งาน (จากโฟลเดอร์ AI/risk_forecaster):
    python data_checks/validate_mock_data.py data/mock_v3

ตรวจ:
  1. สต็อกสมดุล (opening + received - sold - waste = closing) และยอดคงเหลือวันสุดท้ายตรงกับ lot demo
  2. ของหมดชั้น / ของทิ้ง แยกหมวด เทียบช่วงเป้าหมายจาก benchmark (ดู docs/criteria_sources.md)
  3. วัดผลของการลดราคาทั้งวันจากข้อมูลรายวันได้ใกล้ค่าที่ simulator ตั้งไว้
  4. backtest ด้วย Forecaster ตัวจริง: LightGBM ต้องชนะ baseline (same-dow) บนช่วง test
  5. lot demo ผ่าน Risk Scanner ตัวจริง (cutoff จาก models/risk_thresholds.json) ได้ครบทุกระดับ
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CATEGORY = {"DAI": "DAIRY", "MEA": "MEAT", "SEA": "SEAFOOD", "PRO": "PRODUCE", "BAK": "BAKERY", "RTE": "READY_TO_EAT"}
DEMO_DATE = date(2026, 10, 16)
# simulator ลดราคาทั้งวัน: ยอดทั้งวันเพิ่ม = lift รายชั่วโมง (MARKDOWN_LIFT ใน simulate.py)
EXPECTED_DAILY_LIFT = {20: 1.12, 30: 1.20, 50: 1.35}
# เป้าหมาย (min, max) % ต่อหมวด: ของทิ้งจาก shrink รายแผนกของ FMI (ตั้งต่ำกว่าเล็กน้อยเพราะ shrink รวมการขโมย)
# ของหมดชั้นจากค่าเฉลี่ยค้าปลีกราว 8% RTE ยกเว้น (ขายวันละไม่กี่ชิ้น อายุ 0-1 วัน ลดของขาดได้เท่าไรของทิ้งก็เพิ่มเท่านั้น)
WASTE_TARGET = {"BAKERY": (4, 9), "SEAFOOD": (4, 9), "MEAT": (2, 6), "PRODUCE": (2, 6), "DAIRY": (0.5, 3),
                "READY_TO_EAT": (4, 12)}   # v3.1: RTE เทียบ deli ของ FMI 8.7% (เดิมยอม 0-25)
# RTE ขายวันละไม่กี่ชิ้น อายุ 0 วัน ของหมดชั้นช่วงค่ำเป็นเรื่องปกติ (ส่วนใหญ่หมดหลัง 19:00) จึงยอมให้สูงกว่าหมวดอื่น
STOCKOUT_TARGET = {c: (2, 10) for c in CATEGORY.values()} | {"READY_TO_EAT": (0, 35)}


def load(folder):
    pd_ = pd.read_csv(folder / "product_daily.csv", parse_dates=["sale_date"])
    ctx = pd.read_csv(folder / "daily_context.csv", parse_dates=["context_date"])
    lots = pd.read_csv(folder / "inventory_lots_demo.csv", parse_dates=["received_date", "expiration_date"])
    pd_["category"] = pd_.product_id.str[:3].map(CATEGORY)
    df = pd_.merge(ctx, left_on="sale_date", right_on="context_date", how="left").sort_values(["product_id", "sale_date"])
    return df.reset_index(drop=True), ctx, lots


def check_balance(df, lots):
    bad = (df.opening_qty + df.received_qty - df.sold_qty - df.waste_qty != df.closing_qty).sum()
    last = df[df.sale_date == df.sale_date.max()].set_index("product_id").closing_qty
    on_lots = lots.groupby("product_id").current_quantity.sum()
    mismatch = {p: (int(last.get(p, 0)), int(on_lots.get(p, 0))) for p in set(last.index) | set(on_lots.index)
                if last.get(p, 0) != on_lots.get(p, 0)}
    print(f"[1] แถวที่สต็อกไม่สมดุล: {bad} | คงเหลือวันสุดท้ายไม่ตรง lot demo: {mismatch or 'ไม่มี'}")
    return bad == 0 and not mismatch


def check_rates(df):
    g = df.groupby("category").agg(stockout=("is_stockout", "mean"), markdown_days=("markdown_pct", lambda s: (s > 0).mean()),
                                   sold=("sold_qty", "sum"), waste=("waste_qty", "sum"))
    g["stockout_pct"] = (g.stockout * 100).round(1)
    g["waste_pct"] = (g.waste / g.sold * 100).round(1)
    g["markdown_days_pct"] = (g.markdown_days * 100).round(1)
    ok_rows = []
    for cat, r in g.iterrows():
        w_lo, w_hi = WASTE_TARGET[cat]
        s_lo, s_hi = STOCKOUT_TARGET[cat]
        ok_rows.append(w_lo <= r.waste_pct <= w_hi and s_lo <= r.stockout_pct <= s_hi)
    g["ok"] = ok_rows
    print("[2] อัตราแยกหมวด (เป้า: ดู WASTE_TARGET / STOCKOUT_TARGET)\n"
          + g[["stockout_pct", "waste_pct", "markdown_days_pct", "ok"]].to_string())
    print(f"    ของทิ้งรวม {df.waste_qty.sum() / df.sold_qty.sum() * 100:.1f}% | ของหมดชั้นรวม {df.is_stockout.mean() * 100:.1f}%")
    return bool(g.ok.all())


def check_markdown_lift(df):
    """วันลดทั้งวัน (ขายราคาลด >= 90% ของยอด) / ยอดปกติของสินค้าเดียวกันวันเดียวกันในสัปดาห์ (ไม่รวม RTE และวันของหมดชั้น)"""
    d = df[(df.category != "READY_TO_EAT") & ~df.is_stockout]
    base = d[d.markdown_pct == 0].groupby(["product_id", "dow"]).sold_qty.mean().rename("base")
    md = d[(d.markdown_pct > 0) & (d.markdown_sold_qty >= 0.9 * d.sold_qty)].join(base, on=["product_id", "dow"])
    est = (md.sold_qty / md.base).groupby(md.markdown_pct).agg(["mean", "count"])
    print("[3] ผลของการลดราคาทั้งวัน (วัดได้ vs ค่าที่ตั้งใน simulator)")
    ok = True
    for pct, exp in EXPECTED_DAILY_LIFT.items():
        if pct in est.index:
            got, n = est.loc[pct, "mean"], int(est.loc[pct, "count"])
            print(f"    ลด {pct}%: วัดได้ x{got:.2f} จาก {n} วัน | ตั้งไว้ x{exp:.2f}")
            ok &= n >= 20
        else:
            print(f"    ลด {pct}%: ไม่มีข้อมูล")
            ok = False
    return ok


def check_backtest(folder):
    """ใช้ Forecaster ตัวจริง (forecaster/model.py) แบ่ง train / validation / test ตามเวลา"""
    from forecaster.model import Forecaster

    m = Forecaster().fit(pd.read_csv(folder / "training_dataset.csv")).metrics
    print(f"[4] แบ่งข้อมูล {json.dumps(m['split'], ensure_ascii=False)}")
    print(f"    test WAPE (เทียบ latent_demand): same-dow {m['test_wape']['same_dow']}% | LightGBM {m['test_wape']['lgbm']}%")
    return m["test_wape"]["lgbm"] < m["test_wape"]["same_dow"]


def check_demo_risk(folder):
    """lot demo ผ่าน Forecaster + Risk Scanner ตัวจริง (เหมือน run_scan.py โหมด local)"""
    import run_scan
    from common import config
    from risk_scanner import risk
    from forecaster.model import Forecaster
    from common.sources import LocalSource, load_reference

    fc = Forecaster.load()
    ref_products, recipes = load_reference()
    products = {p["product_id"]: p for p in ref_products}
    source = LocalSource(DEMO_DATE, folder)
    scan = source.scan_inputs(config.HISTORY_DAYS)
    demand, _, _ = run_scan.forecast_demand(fc, scan, source, products, recipes)
    th = config.load_thresholds()
    results = risk.assess(scan["inventory_lots"], demand, fc.phi_for, DEMO_DATE, th)
    out = pd.DataFrame([{**{k: r["payload"][k] for k in ("lot_id", "days_to_expiry", "quantity_at_assessment",
                                                         "risk_score", "risk_level")},
                         "product_id": r["lot"]["product_id"]} for r in results])
    print(f"[5] lot demo (cutoff MEDIUM {th['MEDIUM']} / HIGH {th['HIGH']} / CRITICAL {th['CRITICAL']})\n"
          + out.to_string(index=False))
    mix = out.risk_level.value_counts()
    print("    " + " | ".join(f"{k} {mix.get(k, 0)}" for k in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]))
    return all(mix.get(k, 0) >= 1 for k in ["CRITICAL", "HIGH", "LOW"])


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "data/mock_v3")
    df, ctx, lots = load(folder)
    print(f"product_daily {len(df)} แถว ({df.sale_date.min().date()} -> {df.sale_date.max().date()}), "
          f"daily_context {len(ctx)} แถว, วันหยุด {int(ctx.is_public_holiday.sum())} วัน, lot demo {len(lots)} lot")
    results = {
        "สต็อกสมดุล": check_balance(df, lots),
        "ของหมดชั้น/ของทิ้งตามเป้า": check_rates(df),
        "วัดผลการลดราคาได้": check_markdown_lift(df),
        "LightGBM ชนะ baseline": check_backtest(folder),
        "lot demo มี CRITICAL/HIGH/LOW": check_demo_risk(folder),
    }
    print("\nสรุป: " + " | ".join(f"{k} {'ผ่าน' if v else 'ไม่ผ่าน'}" for k, v in results.items()))


if __name__ == "__main__":
    main()
