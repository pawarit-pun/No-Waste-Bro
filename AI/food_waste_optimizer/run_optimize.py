"""รอบ Optimizer 1 รอบ: อ่านข้อมูลจริงจาก server -> คำนวณ -> (--save) บันทึกลง Supabase ผ่าน server
(รวมโค้ดของ ai_engine/demo/run_offline.py เดิมไว้ที่นี่ รูปแบบเดียวกับ run_scan.py ของทีม Risk Scanner)

ใช้งาน (จากโฟลเดอร์ AI/food_waste_optimizer, เปิด server ไว้ก่อน: `fastapi dev main.py` ในโฟลเดอร์ server)
    python run_optimize.py                          อ่านจริง คำนวณ แสดงผล ไม่เขียนอะไร (dry run)
    python run_optimize.py --run-id <uuid>          ระบุรอบสแกน (ไม่ใส่ = รอบล่าสุด)
    python run_optimize.py --save                   บันทึก decision + คืน lot ที่ไม่ต้องทำอะไรเป็น IDLE
    python run_optimize.py --via-server [--save]    ให้ server รัน Optimizer เอง (POST /api/v1/ai/optimize)
    python run_optimize.py --input output/<รอบ>/optimize_inputs.json   รันซ้ำจากข้อมูลจริงที่บันทึกไว้ (ไม่ต่อ server)

URL ของ server: env API_BASE_URL (ค่าเริ่มต้น http://127.0.0.1:8000/api/v1)
ผลแต่ละรอบ: output/<วันที่>_<เวลา>_<โหมด>/ (optimize_inputs.json, plan.json, decisions_request.json,
             decisions_response.json, allocations.json, report.txt)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from ai_engine.optimizer import ApiClient, ApiError, PlanValidationError, optimize_and_post, run_optimizer
from ai_engine.optimizer.config import BKK

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


# ---------------------------------------------------------------- PART 1: รายงาน
def format_report(plan: dict, decisions: list) -> str:
    s = plan["summary"]
    lines = [f"run_id {plan['run_id']} | วันที่อ้างอิง {plan['reference_date']} | เวลาที่ใช้คิด {plan['simulated_now']}",
             f"solver {plan['solver']['status']} ({plan['solver']['time_ms']} ms)", ""]
    for lid, sk in plan.get("skipped_lots", {}).items():
        lines.append(f"ข้าม {lid}: {', '.join(sk['reasons'])}")
    for lo in plan["lots"]:
        lines.append(f"{lo['lot_id']} {lo['product_id']} {lo['name']} | {lo['quantity']} หน่วย | หมดอายุอีก "
                     f"{lo['days_to_expiry']} วัน | {lo['risk_level']} {lo['risk_score']} | ยอดขายที่เหลือ "
                     f"{lo['demand_fraction'] * 100:.0f}% ของที่ forecaster คาด")
        for p in lo["portions"]:
            tag = p["method"] + (f" {p['details']['discount_pct']}%" if p["method"] == "MARKDOWN" else "")
            who = p["details"].get("partner_name") or p["details"].get("recipe_id") or ""
            lines.append(f"    {p['share_pct']:6.2f}% {p['units']:4d} หน่วย {p['weight_kg']:7.2f} kg  {tag:20s} "
                         f"รับ {p['revenue_thb']:9.2f} จ่าย {p['cost_thb']:8.2f} ต้นทุนสินค้า {p['cogs_thb']:8.2f} "
                         f"สุทธิ {p['net_profit_thb']:9.2f}  {who}")
        lines.append(f"    -> lot นี้ {lo['net_profit_thb']:.2f} บาท")
    lines += ["", "เที่ยวรับของ:"] + [
        f"  {t['partner_id']} {t['partner_type']:20s} {t['kg']:8.2f} kg รับ {t['pickup_at']} ค่าเที่ยว {t['trip_cost_thb']:.2f} "
        f"+ handling {t['handling_thb']:.2f} - รับซื้อ {t['buyback_revenue_thb']:.2f}" for t in plan["trips"]]
    lines += ["งานครัว:"] + [
        f"  {j['job_id']} {j['name']} {j['batches']} batch ใช้ {j['anchor_units']} หน่วยจาก {j['anchor_lot_id']} "
        f"ได้ {j['output_units']:g} ชิ้น คาดขาย {j['expected_sold_units']} | กำไร {j['net_profit_thb']:.2f}"
        for j in plan["kitchen_jobs"]]
    lines += ["", "สัดส่วนรวม (ตามจำนวนหน่วย): " + ", ".join(f"{k} {v}%" for k, v in s["split_pct_by_method"].items()),
              f"รายได้ {s['gross_revenue_thb']:.2f} | ค่าใช้จ่าย {s['route_costs_thb']:.2f} | ต้นทุนสินค้า {s['cogs_thb']:.2f}",
              f"เงินที่ได้กลับคืนสุทธิ {s['net_recovery_thb']:.2f} บาท | กำไร(ขาดทุน)สุทธิรวมต้นทุนสินค้า {s['net_profit_thb']:.2f} บาท",
              "", "เทียบกับไม่ใช้ Optimizer:"]
    for k, v in plan.get("baselines", {}).items():
        lines.append(f"  {k}: {v['net_profit_thb'] if isinstance(v, dict) else v}")
    lines += ["", f"decision ที่จะบันทึก ({len(decisions)}):"] + [
        f"  [{i}] {d['action_type']:18s} {d['action_quantity']:4d} หน่วย "
        f"{d.get('discount_pct', '') or d.get('target_recipe_id', '') or d.get('target_partner_id', '')} "
        f"due {d.get('due_by', '-')} | {d['expected_profit_impact']:.2f} บาท" for i, d in enumerate(decisions)]
    lines += ["", "คำเตือน:"] + [f"  - {w}" for w in plan["warnings"]] if plan["warnings"] else []
    return "\n".join(lines)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


# ---------------------------------------------------------------- PART 2: โหมดต่าง ๆ
def run_local_file(path: Path) -> dict:
    """รันซ้ำจาก optimize_inputs.json ที่รอบก่อนบันทึกไว้ (ข้อมูลจริง) ใช้ products.json ในโฟลเดอร์เดียวกันถ้ามี"""
    data = json.loads(path.read_text(encoding="utf-8"))
    inputs = data.get("optimize_inputs", data)
    products = data.get("products")
    if products is None and (path.parent / "products.json").exists():
        products = json.loads((path.parent / "products.json").read_text(encoding="utf-8"))
    result = run_optimizer(inputs, products_catalog=products)
    result.update(inputs=inputs, products=products, saved=None, released=None, dry_run=True)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="No-Waste-Bro Optimizer")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--days-ahead", type=int, default=1)
    ap.add_argument("--save", action="store_true", help="บันทึก decision ลง Supabase ผ่าน server")
    ap.add_argument("--via-server", action="store_true", help="ให้ server รัน Optimizer เอง (POST /ai/optimize)")
    ap.add_argument("--input", type=Path, default=None, help="optimize_inputs.json ที่บันทึกไว้ (ไม่ต่อ server)")
    args = ap.parse_args()

    mode = "file" if args.input else ("server" if args.via_server else "api") + ("_save" if args.save else "_dry")
    try:
        if args.input:
            result = run_local_file(args.input)
        elif args.via_server:
            response = ApiClient().run_optimize(args.run_id, args.days_ahead, dry_run=not args.save)
            out = OUTPUT_DIR / f"{response['reference_date']}_{datetime.now(BKK):%H%M%S}_{mode}"
            out.mkdir(parents=True, exist_ok=True)
            write_json(out / "optimize_response.json", response)
            print(json.dumps(response["summary"], ensure_ascii=False, indent=1))
            print(f"decision {len(response['decisions'])} รายการ | บันทึกแล้ว: {bool(response['saved'])} | "
                  f"คืน IDLE: {response['lots_released']}\nไฟล์ผลลัพธ์: {out}")
            return 0
        else:
            result = optimize_and_post(ApiClient(), run_id=args.run_id, days_ahead=args.days_ahead, dry_run=not args.save)
    except ApiError as e:
        print(f"เรียก server ไม่สำเร็จ: {e}\n(เปิด server ด้วย `fastapi dev main.py` ในโฟลเดอร์ server แล้วหรือยัง?)",
              file=sys.stderr)
        return 1
    except PlanValidationError as e:
        print(f"แผนไม่ผ่านการตรวจกฎ ไม่ได้บันทึกอะไร:\n{json.dumps(e.violations + e.payload_errors, ensure_ascii=False, indent=1)}",
              file=sys.stderr)
        return 2

    plan = result["plan"]
    out = OUTPUT_DIR / f"{plan['reference_date']}_{datetime.now(BKK):%H%M%S}_{mode}"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "optimize_inputs.json", result.get("inputs"))
    write_json(out / "products.json", result.get("products"))
    write_json(out / "plan.json", plan)
    write_json(out / "decisions_request.json", result["payload"])
    write_json(out / "allocations.json", result["allocations"])
    if result.get("saved") is not None:
        write_json(out / "decisions_response.json", result["saved"])
    report = format_report(plan, result["payload"]["decisions"])
    (out / "report.txt").write_text(report, encoding="utf-8")
    print(report)
    status = "บันทึกแล้ว" if result.get("saved") else "ยังไม่ได้บันทึก (เพิ่ม --save เพื่อบันทึก)"
    if args.input:
        status = "รันจากไฟล์ ไม่ได้บันทึก"
    print(f"\n{status} | คืน IDLE: {result['lots_to_release'] if result.get('released') else '-'} | ไฟล์ผลลัพธ์: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())