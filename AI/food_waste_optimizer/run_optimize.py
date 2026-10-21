"""รอบ Optimizer 1 รอบ: GET ข้อมูลจริงจาก Supabase (ผ่าน server) -> คำนวณ -> POST ลง optimization_decisions ทันที
(รวมโค้ดของ ai_engine/demo/run_offline.py เดิมไว้ที่นี่ รูปแบบเดียวกับ run_scan.py ของทีม Risk Scanner)

ใช้งาน (จากโฟลเดอร์ AI/food_waste_optimizer, เปิด server ไว้ก่อน: `fastapi dev main.py` ในโฟลเดอร์ server)
    python run_optimize.py                          GET -> คำนวณ -> POST decision ลง Supabase ทันที + คืน lot ที่ไม่ต้องทำอะไรเป็น IDLE
    python run_optimize.py --dry-run                GET -> คำนวณ -> แสดงผลอย่างเดียว ไม่เขียนอะไร
    python run_optimize.py --run-id <uuid>          ระบุรอบสแกนเอง
                                                    (ไม่ใส่ = รอบล่าสุดที่สแกนวันเดียวกับ DEMO_DATE และยังมี lot HIGH / CRITICAL
                                                     รอตัดสินใจ จาก GET /ai/optimize-runs)
    python run_optimize.py --via-server [--dry-run] ให้ server รัน Optimizer เอง (POST /api/v1/ai/optimize)
    python run_optimize.py --input output/<รอบ>/optimize_inputs.json   รันซ้ำจากข้อมูลจริงที่บันทึกไว้ (ไม่ต่อ server ไม่เขียน)

URL ของ server: env API_BASE_URL (ค่าเริ่มต้น https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1)
ผลแต่ละรอบ: output/<วันที่>_<เวลา>_<โหมด>/ (optimize_inputs.json, plan.json, decisions_request.json,
             decisions_response.json, allocations.json, report.txt)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from ai_engine.optimizer import ApiClient, ApiError, PlanValidationError, optimize_and_post, pick_run, run_optimizer
from ai_engine.optimizer.config import BKK

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR") or Path(__file__).resolve().parent / "output")   # env: ใช้บน Lambda (เขียนได้แค่ /tmp)


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
            if p["details"].get("timing") == "END_OF_LIFE":
                tag += " (เหลือ)"
            elif "shelf_units" in p["details"]:
                tag += f" (ชั้น {p['details']['shelf_units']})"
            who = p["details"].get("partner_name") or p["details"].get("recipe_id") or ""
            lines.append(f"    {p['share_pct']:6.2f}% {p['units']:4d} หน่วย {p['weight_kg']:7.2f} kg  {tag:20s} "
                         f"รับ {p['revenue_thb']:9.2f} จ่าย {p['cost_thb']:8.2f} ต้นทุนสินค้า {p['cogs_thb']:8.2f} "
                         f"สุทธิ {p['net_profit_thb']:9.2f}  {who}")
        lines.append(f"    -> lot นี้ {lo['net_profit_thb']:.2f} บาท")
    lines += ["", "เที่ยวรับของ:"] + [
        f"  {t['trip_id']} {t['partner_type']:20s} {t['kg']:8.2f} kg รับ {t['pickup_at']} ค่าเที่ยว {t['trip_cost_thb']:.2f} "
        f"+ handling {t['handling_thb']:.2f} - รับซื้อ {t['buyback_revenue_thb']:.2f}" for t in plan["trips"]]
    lines += ["งานครัว:"] + [
        f"  {j['job_id']} {j['name']} {j['batches']} batch ใช้ {j['anchor_units']} หน่วยจาก {j['anchor_lot_id']} "
        f"ได้ {j['output_units']:g} ชิ้น คาดขาย {j['expected_sold_units']} | กำไร {j['net_profit_thb']:.2f}"
        for j in plan["kitchen_jobs"]]
    lines += ["", "สัดส่วนรวม (ตามจำนวนหน่วย): " + ", ".join(f"{k} {v}%" for k, v in s["split_pct_by_method"].items()),
              f"รายได้ {s['gross_revenue_thb']:.2f} | ค่าใช้จ่าย {s['route_costs_thb']:.2f} | ต้นทุนสินค้า {s['cogs_thb']:.2f}",
              f"เงินที่ได้กลับคืนสุทธิ {s['net_recovery_thb']:.2f} บาท | กำไร(ขาดทุน)สุทธิรวมต้นทุนสินค้า {s['net_profit_thb']:.2f} บาท",
              f"วางขาย {s['shelf_units']} หน่วย คาดขายได้ {s['expected_sold_units']} | คาดว่าเหลือหลังหมดเวลาขาย "
              f"{s['expected_end_of_life_units']} หน่วย (ตัวเงินเป็นค่าคาดหมายจาก P10/P50/P90)",
              "", "เทียบกับไม่ใช้ Optimizer:"]
    for k, v in plan.get("baselines", {}).items():
        lines.append(f"  {k}: {v['net_profit_thb'] if isinstance(v, dict) else v}")
    lines += ["", f"decision ที่จะบันทึก ({len(decisions)}):"] + [
        f"  [{i}] {d['action_type']:18s} {d['action_quantity']:4d} หน่วย "
        f"{d.get('discount_pct', '') or d.get('target_recipe_id', '') or d.get('target_partner_id', '')} "
        f"due {d.get('due_by', '-')} | {d['expected_profit_impact']:.2f} บาท" for i, d in enumerate(decisions)]
    lines += ["", "คำเตือน:"] + [f"  - {w}" for w in plan["warnings"]] if plan["warnings"] else []
    return "\n".join(lines)


def format_runs(runs: dict) -> str:
    lines = [f"รอบสแกนใน lot_risk_assessments (วันที่อ้างอิงของ server = {runs['reference_date']}):",
             f"  {'run_id':36s}  {'สแกนวันที่':10s}  lot  HIGH/CRIT  มี decision  รอตัดสินใจ  พร้อม"]
    for r in runs["runs"][:10]:
        lines.append(f"  {r['run_id']:36s}  {str(r['scan_date']):10s}  {r['lots']:3d}  {r['at_risk']:9d}  "
                     f"{r['decided']:11d}  {r['pending']:10d}  {'ใช่' if r['ready'] else '-'}")
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
    ap.add_argument("--dry-run", action="store_true", help="คำนวณและแสดงผลอย่างเดียว ไม่เขียน Supabase")
    ap.add_argument("--save", action="store_true", help=argparse.SUPPRESS)   # รุ่นเก่า: ตอนนี้บันทึกเป็นค่าเริ่มต้นแล้ว
    ap.add_argument("--via-server", action="store_true", help="ให้ server รัน Optimizer เอง (POST /ai/optimize)")
    ap.add_argument("--input", type=Path, default=None, help="optimize_inputs.json ที่บันทึกไว้ (ไม่ต่อ server)")
    args = ap.parse_args()
    save = not args.dry_run

    mode = "file" if args.input else ("server" if args.via_server else "api") + ("_save" if save else "_dry")
    try:
        if args.input:
            result = run_local_file(args.input)
        else:
            # ---- 1) GET: เลือกรอบสแกนที่พร้อมตัดสินใจ
            client = ApiClient()
            run_id, runs = pick_run(client, args.run_id)
            if runs is not None:
                print(format_runs(runs) + "\n")
                if run_id is None:
                    print(f"ไม่มีรอบสแกนที่พร้อมตัดสินใจ: ต้องเป็นรอบที่สแกนวันที่ {runs['reference_date']} (= DEMO_DATE) "
                          f"และยังมี lot HIGH / CRITICAL สถานะ PROCESSING ที่ไม่มี decision\n"
                          f"  - สแกนใหม่: cd ..\\risk_forecaster แล้ว python run_scan.py --source api\n"
                          f"  - หรือแก้ DEMO_DATE ใน server/.env ให้ตรงกับ 'สแกนวันที่' ของรอบที่ต้องการ แล้วเปิด server ใหม่\n"
                          f"  - หรือระบุรอบเอง: python run_optimize.py --run-id <run_id>\n"
                          f"ไม่ได้บันทึกอะไร", file=sys.stderr)
                    return 3
                print(f"ใช้รอบ {run_id}\n")
            if args.via_server:
                response = client.run_optimize(run_id, args.days_ahead, dry_run=not save)
                out = OUTPUT_DIR / f"{response['reference_date']}_{datetime.now(BKK):%H%M%S}_{mode}"
                out.mkdir(parents=True, exist_ok=True)
                write_json(out / "optimize_response.json", response)
                print(json.dumps(response["summary"], ensure_ascii=False, indent=1))
                print(f"decision {len(response['decisions'])} รายการ | บันทึกแล้ว: {bool(response['saved'])} | "
                      f"คืน IDLE: {response['lots_released']}\nไฟล์ผลลัพธ์: {out}")
                return 0
            # ---- 2) GET ข้อมูล -> คำนวณ -> 3) POST /optimization-decisions (ถ้าไม่ใช่ --dry-run)
            result = optimize_and_post(client, run_id=run_id, days_ahead=args.days_ahead, dry_run=not save)
    except ApiError as e:
        print(f"server ตอบ error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"ต่อ server ไม่ได้: {e}\n(เปิด server ด้วย `fastapi dev main.py` ในโฟลเดอร์ server แล้วหรือยัง?)",
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
    if result.get("saved"):
        status = (f"บันทึกลง optimization_decisions แล้ว {result['saved'].get('created', len(result['payload']['decisions']))} "
                  f"รายการ (ดู: GET /api/v1/optimization-decisions?run_id={plan['run_id']})")
    elif save:
        status = "ไม่มี decision ให้บันทึก (ไม่มี lot HIGH / CRITICAL ที่ยังไม่ตัดสินใจในรอบสแกนนี้)"
    else:
        status = "--dry-run: ยังไม่ได้บันทึก (รันโดยไม่ใส่ --dry-run เพื่อบันทึก)"
    if args.input:
        status = "รันจากไฟล์ ไม่ได้บันทึก"
    print(f"\n{status} | คืน IDLE: {result['lots_to_release'] if result.get('released') else '-'} | ไฟล์ผลลัพธ์: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())