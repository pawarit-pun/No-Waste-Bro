"""รัน Optimizer แบบ offline ด้วยข้อมูลจากภาพ Supabase (ไม่แตะเน็ต/ไม่เขียน DB)

    python -m ai_engine.demo.run_offline --date 2026-10-16 --time 08:00 [--mode extended] [--out out/]
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time
from pathlib import Path

from ai_engine.clock import BKK
from ai_engine.demo.offline_snapshot import build_offline_inputs
from ai_engine.optimizer import OptimizerConfig, run_optimizer


def format_report(plan: dict) -> str:
    s = plan["summary"]
    lines = [f"วันที่อ้างอิง {plan['reference_date']}  เวลาจำลอง {plan['simulated_now']}",
            f"solver: {plan['solver']['status']} gap={plan['solver']['gap']} {plan['solver']['time_ms']} ms", ""]
    for lo in plan["lots"]:
        lines.append(f"{lo['lot_id']} {lo['product_id']} {lo['name']}  {lo['quantity']} หน่วย  "
                    f"เหลือ {lo['days_to_expiry']} วัน  risk {lo['risk_level']} {lo['risk_score']}")
        for p in lo["portions"]:
            tag = p["method"] + (f" {p['details']['discount_pct']}%" if "discount_pct" in p["details"] and p["method"] == "MARKDOWN" else "")
            extra = p["details"].get("partner_name") or ""
            lines.append(f"    {p['share_pct']:6.2f}%  {p['units']:4d} หน่วย  {p['weight_kg']:8.2f} kg  {tag:22s} "
                        f"รับ {p['revenue_thb']:9.2f}  จ่าย {p['cost_thb']:8.2f}  กำไรสุทธิ {p['net_profit_thb']:9.2f}  {extra}")
        lines.append(f"    -> กำไร/ขาดทุน lot นี้ {lo['net_profit_thb']:.2f} บาท (ต้นทุนสินค้า {lo['cogs_thb']:.2f})")
    lines += ["", "เที่ยวรับของ partner:"]
    for t in plan["trips"]:
        lines.append(f"  {t['partner_id']} {t['partner_type']:20s} {t['kg']:8.2f} kg รับ {t['pickup_at']}  "
                    f"ค่าเที่ยว {t['trip_cost_thb']:.2f} + handling {t['handling_thb']:.2f}  buyback {t['buyback_revenue_thb']:.2f}")
    lines.append("งานครัว:")
    for j in plan["kitchen_jobs"]:
        lines.append(f"  {j['job_id']} {j['name']} {j['batches']} batch ({j['output_units']:g} ชิ้น, {j['hours']} ชม.) "
                    f"กำไร {j['net_profit_thb']:.2f}")
    lines += ["", "สัดส่วนรวม (ตามจำนวนหน่วย): " + ", ".join(f"{k} {v}%" for k, v in s["split_pct_by_method"].items()),
            f"รายรับรวม {s['gross_revenue_thb']:.2f} | ค่าใช้จ่ายรวม {s['route_costs_thb']:.2f} | ต้นทุนสินค้า {s['cogs_thb']:.2f}",
            f"เงินที่ได้กลับคืนสุทธิ {s['net_recovery_thb']:.2f} บาท | กำไร(ขาดทุน)สุทธิรวมต้นทุนสินค้า {s['net_profit_thb']:.2f} บาท",
            f"ตรวจยอดตรงกับ solver: {s['reconciliation_ok']} (gap {s['reconciliation_gap_thb']})", "",
            "เทียบกับวิธีไม่ใช้ Optimizer (กำไรสุทธิรวมต้นทุนสินค้า):"]
    for k, v in plan["baselines"].items():
        lines.append(f"  {k}: {v if not isinstance(v, dict) else v.get('net_profit_thb')}")
    lines += ["", "คำเตือน:"] + [f"  - {w}" for w in plan["warnings"]]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-10-16")
    ap.add_argument("--time", default="08:00")
    ap.add_argument("--mode", default="current", choices=["current", "extended"])
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    now = datetime.combine(date.fromisoformat(a.date), time.fromisoformat(a.time), tzinfo=BKK)
    inputs, demand = build_offline_inputs(now)
    result = run_optimizer(inputs, demand, now, OptimizerConfig(action_mode=a.mode))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.json").write_text(json.dumps(result["plan"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "decisions_payload.json").write_text(json.dumps(result["payload"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(format_report(result["plan"]))
    print(f"\nบันทึก {out}/plan.json และ {out}/decisions_payload.json ({len(result['payload']['decisions'])} decisions)")


if __name__ == "__main__":
    main()
