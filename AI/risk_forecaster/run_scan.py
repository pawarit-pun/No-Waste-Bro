"""รอบสแกน 1 รอบ: ดึงข้อมูล -> Forecaster -> Risk Scanner -> shelf curve + recipe_demand -> บันทึก

ใช้งาน (จากโฟลเดอร์ AI, ต้องเทรนก่อนด้วย train_forecaster.py และ calibrate_risk.py):
    python run_scan.py                                  # โหมด local: อ่าน data/mock_v3 ไม่เขียน Supabase
    python run_scan.py --date 2026-10-16
    python run_scan.py --source api --dry-run           # เรียก scan-inputs จริง แต่ไม่ล็อก / ไม่ POST
    python run_scan.py --source api                     # รอบจริง (ต้องตั้ง API_BASE_URL)
    python run_scan.py --source api --optimize preview  # รอบจริง แล้วให้ Optimizer คำนวณผลของ run นี้ (ยังไม่บันทึก)
    python run_scan.py --source api --optimize save     # รอบจริง แล้วให้ Optimizer บันทึก decision ทันที (พร้อมให้ RAG)

ลำดับในโหมด api:
  1. GET   /ai/scan-inputs?history_days=56
  2. PATCH /inventory-lots/ai-status  PROCESSING  (ทุกล็อตที่ได้มา)
  3. Forecaster + Risk Scanner + shelf curve (HIGH / CRITICAL) + recipe_demand
  4. POST  /risk-assessments  (บันทึก forecast_runs, lot_risk_assessments, lot_shelf_forecasts,
                               recipe_demand_forecasts ใน transaction เดียว) -> run_id + assessment_id
  5. PATCH /inventory-lots/ai-status  IDLE  (ล็อต LOW / MEDIUM ให้สแกนใหม่พรุ่งนี้)
  Optimizer อ่านผลจาก GET /ai/optimize-inputs?run_id=...
  6. (ถ้าใส่ --optimize) POST /ai/optimize?run_id=...  server รัน Optimizer กับผลรอบนี้
ถ้าพังระหว่างขั้น 3-4 ล็อตทั้งหมดจะถูกตั้งกลับเป็น IDLE
"""
import argparse
import json
from datetime import date, datetime, timedelta

import pandas as pd

from common import config
from risk_scanner import handoff, risk
from forecaster.model import Forecaster
from common.sources import ApiSource, LocalSource, load_reference


def forecast_demand(fc, scan, source, products, recipes):
    """mu ของทุก (สินค้า, วัน) ที่ต้องใช้: สินค้าของล็อตถึงวันหมดอายุ และสินค้าเมนูครัวในช่วงอายุเมนู"""
    ref = date.fromisoformat(scan["reference_date"])
    targets = set()
    for lot in scan["inventory_lots"]:
        exp = date.fromisoformat(str(lot["expiration_date"])[:10])
        targets |= {(lot["product_id"], ref + timedelta(days=i)) for i in range((exp - ref).days + 1)}
    for r in recipes:
        if r["is_active"]:
            targets |= {(r["output_product_id"], ref + timedelta(days=i)) for i in range(int(r["shelf_life_days"]) + 1)}
    targets = sorted(targets)

    history = list(scan["product_daily"])
    missing = sorted({pid for pid, _ in targets} - {row["product_id"] for row in history})
    stale = False
    if missing:
        extra, stale = source.extra_history(missing, ref)
        history += extra
    prod_df = pd.DataFrame([{"product_id": p["product_id"], "category": p["category"],
                             "shelf_life_days": p["shelf_life_days"]} for p in products.values()])
    mu = fc.predict_daily(history, scan["daily_context"], prod_df, ref, targets)
    demand = {(r.product_id, r.date.date()): float(r.mu) for r in mu.itertuples()}
    return demand, missing, stale


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["local", "api"], default="local")
    ap.add_argument("--date", type=date.fromisoformat, default=date(2026, 10, 16), help="วันอ้างอิง (โหมด local)")
    ap.add_argument("--dry-run", action="store_true", help="โหมด api: อ่านอย่างเดียว ไม่ล็อก ไม่ POST")
    ap.add_argument("--optimize", choices=["preview", "save"], default=None,
                    help="โหมด api รอบจริง: ส่งต่อให้ Optimizer ทันที (preview = คำนวณอย่างเดียว, save = บันทึก decision)")
    args = ap.parse_args()

    source = LocalSource(args.date) if args.source == "local" else ApiSource()
    writes = args.source == "api" and not args.dry_run
    fc = Forecaster.load()
    thresholds = config.load_thresholds()
    ref_products, recipes = load_reference()
    products = {p["product_id"]: p for p in ref_products}

    scan = source.scan_inputs(config.HISTORY_DAYS)
    lots = scan["inventory_lots"]
    out_dir = config.OUTPUT_DIR / f"{scan['reference_date']}_{datetime.now():%H%M%S}_{args.source}"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "scan_inputs.json", scan)
    if not lots:
        print("ไม่มีล็อต IDLE ให้สแกน")
        return
    for p in scan["products"]:                       # ข้อมูลล่าสุดจาก route ทับ snapshot
        products.setdefault(p["product_id"], {}).update(p)
    lot_ids = [l["lot_id"] for l in lots]
    ref = date.fromisoformat(scan["reference_date"])
    used_today = risk.hours_used_today(ref) if args.source == "api" else 0.0

    if writes:
        source.set_ai_status(lot_ids, "PROCESSING")
    try:
        demand, missing, stale = forecast_demand(fc, scan, source, products, recipes)
        results = risk.assess(lots, demand, fc.phi_for, ref, thresholds, used_today)
        recipe_rows = handoff.build(results, products, recipes, demand, fc.lifts, ref, fc.phi_for)
        model_version = f"{config.RISK_MODEL_VERSION}+{fc.version}"
        request = {
            "model_version": model_version,
            "reference_date": ref.isoformat(),
            "run_metrics": {"forecaster": fc.chosen, "test_wape": fc.metrics.get("test_wape"),
                            "thresholds": thresholds, "markdown_lift": fc.lifts},
            "assessments": [r["payload"] for r in results],
            "recipe_demand": recipe_rows,
        }
        write_json(out_dir / "risk_assessments_request.json", request)
        run_id = None
        if writes:
            response = source.post_assessments(request)
            write_json(out_dir / "risk_assessments_response.json", response)
            run_id = response["run_id"]
    except Exception:
        if writes:
            source.set_ai_status(lot_ids, "IDLE")    # คืนล็อตให้สแกนใหม่ได้
        raise

    back = [r["payload"]["lot_id"] for r in results if r["payload"]["risk_level"] in config.RETURN_TO_IDLE_LEVELS]
    if writes:
        source.set_ai_status(back, "IDLE")

    table = pd.DataFrame([r["payload"] for r in results])[
        ["lot_id", "days_to_expiry", "sellable_hours", "quantity_at_assessment", "forecast_daily_demand",
         "predicted_units_sold_before_expiry", "predicted_leftover_units", "sell_through_probability",
         "risk_score", "risk_level"]]
    table.insert(1, "product_id", [r["lot"]["product_id"] for r in results])
    table.to_csv(out_dir / "summary.csv", index=False)
    forward = table[table.risk_level.isin(config.FORWARD_LEVELS)]
    print(f"reference_date {ref} | {len(lots)} ล็อต | forecaster {fc.chosen} | cutoff MEDIUM {thresholds['MEDIUM']} "
          f"HIGH {thresholds['HIGH']} CRITICAL {thresholds['CRITICAL']}")
    if missing:
        print(f"ยอดขายของ {', '.join(missing)} ไม่มีใน scan-inputs ใช้จาก CSV" + (" (อาจไม่อัปเดต)" if stale else ""))
    print(table.to_string(index=False))
    print("ระดับ:", table.risk_level.value_counts().to_dict(), f"| ส่งต่อ Optimizer {len(forward)} ล็อต"
          f" | คืน IDLE {len(back)} ล็อต" + (f" | run_id {run_id}" if run_id else " | (ไม่ได้ POST)"))
    print("recipe_demand:", ", ".join(f"{r['recipe_id']} {r['menu_qty']} (฿{r['expected_revenue']:,.0f})"
                                      for r in recipe_rows))

    # ---- เส้นเชื่อมไป Optimizer (AI/food_waste_optimizer ผ่าน server: POST /ai/optimize)
    if args.optimize and run_id:
        opt = source.optimize(run_id, dry_run=args.optimize == "preview")
        write_json(out_dir / "optimize_response.json", opt)
        s = opt["summary"]
        print(f"Optimizer ({'บันทึกแล้ว' if opt.get('saved') else 'ยังไม่บันทึก'}): {len(opt['decisions'])} decision | "
              + ", ".join(f"{k} {v}%" for k, v in s.get("split_pct_by_method", {}).items())
              + f" | กำไรสุทธิ {s.get('net_profit_thb', 0):,.2f} บาท")
    elif args.optimize:
        print("--optimize ใช้ได้เฉพาะรอบจริง (--source api ไม่ใส่ --dry-run) เพราะต้องมี run_id ที่บันทึกแล้ว")
    print(f"ไฟล์ผลลัพธ์: {out_dir}")


if __name__ == "__main__":
    main()