"""Backtest 3 นโยบายจัดการ lot บนร้านจำลองจาก mock_v3 (ช่วง test ของ Forecaster) ด้วยโค้ด AI บน main แล้วสรุปเป็น HTML

ใช้งาน (จากโฟลเดอร์ AI/backtest, Python ที่มี lightgbm + scipy เช่น server/.venv):
    python run_backtest.py                                  # 60 วัน 2026-08-17 -> 2026-10-15 ทั้ง 2 กติการถ
    python run_backtest.py --disposal dedicated --days 7    # รันเร็ว 7 วัน กติการถแบบเดียว
    python run_backtest.py --disposal bins --compare data/reference_optimizer-update.json
    python run_backtest.py --approve-rate 0.8               # ผู้จัดการปฏิเสธ task 20%
    python run_backtest.py --render-only                    # สร้าง HTML ใหม่จาก JSON เดิม

นโยบาย (ร้านเดียวกัน ของเข้าร้านชุดเดียวกัน ลูกค้าชุดเดียวกัน กติการถเดียวกัน):
  1 ร้านแบบเดิม       ขายราคาปกติ ของหมดอายุทิ้ง landfill
  2 ลดราคาตามกฎตายตัว  ตามจำนวนวันที่เหลือขาย (ดู world.FIXED_RULES) ของหมดอายุทิ้ง landfill
  3 product (main)    ทุกเช้า Risk Scanner + Forecaster สแกน lot IDLE -> Optimizer -> task เฉพาะวันนี้ (policy_lifecycle.py)

กติการถ (--disposal) ดู world.py: dedicated = แบบที่ Optimizer บน main คิดต้นทุน, bins = เหมือน backtest 22 ต.ค.
Forecaster ของนโยบาย 3 เทรนใหม่ด้วยข้อมูลก่อนช่วง test (2026-08-04) เท่านั้น ไม่เห็นยอดขายในช่วง backtest

กำไรสุทธิ = รายได้ขาย + มูลค่าเมนูครัว + buyback - ค่าเที่ยว - ค่า handling - ต้นทุนสินค้าทุกหน่วยที่ออกจากร้าน
ความเสียหายจากของทิ้ง = ต้นทุนสินค้าที่ทิ้ง / ส่ง partner + ค่าเที่ยว + handling - buyback
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import date, timedelta
from pathlib import Path

from world import DISPOSAL_MODES, FIXED_RULES, HERE, MAX_HOLD_DAYS, METHOD_TH, MOCK, NEWEST_SHARE, TRUE_LIFT, \
    Ledger, World, run_rule_policy
from policy_lifecycle import TEST_START, LifecyclePolicy, ScanModel, rf_config

MODE_TH = {"dedicated": "รถมาเฉพาะ (dedicated)", "bins": "ถังสะสม (bins)"}


def summarize(led: Ledger) -> dict:
    m = led.money
    sold_units = led.units["SELL_REGULAR"] + led.units["MARKDOWN"]
    waste_units = sum(v for k, v in led.units.items() if k not in ("SELL_REGULAR", "MARKDOWN", "KITCHEN"))
    return {
        "name": led.name, "net_profit": round(led.net, 2), "waste_loss": round(led.waste_loss, 2),
        "revenue": round(m["revenue_full"] + m["revenue_md"], 2), "revenue_markdown": round(m["revenue_md"], 2),
        "kitchen_value": round(m["kitchen_value"], 2), "buyback": round(m["buyback"], 2),
        "trip_fee": round(m["trip_fee"], 2), "handling": round(m["handling"], 2),
        "cogs_total": round(led.cogs, 2), "cogs_waste": round(m["cogs_waste"], 2),
        "units": dict(led.units), "sold_units": sold_units, "waste_units": waste_units,
        "kg": {k: round(v, 2) for k, v in led.kg.items()}, "waste_kg": round(sum(led.kg.values()), 2),
        "landfill_kg": round(led.kg["LANDFILL"], 2), "calls": dict(led.calls), "calls_below_min": led.calls_below_min,
        "daily": led.daily, "notes": dict(led.notes),
    }


def pct(a: float, b: float) -> float:
    return (a - b) / abs(b) * 100 if b else 0.0


def baht(x: float) -> str:
    return f"{x:,.0f}"


def signed(x: float) -> str:
    return f"{x:+,.0f}" if round(x) else "0"


def environment(world: World, scanner: ScanModel) -> dict:
    """สภาพแวดล้อมของ backtest สำหรับรายงาน: ร้านจำลอง / partner / ผลวัดของ Forecaster + Risk Scanner บนช่วง test"""
    fm = json.loads((rf_config.MODEL_DIR / f"{rf_config.MODEL_VERSION}_metrics.json").read_text(encoding="utf-8"))
    th = json.loads((rf_config.MODEL_DIR / "risk_thresholds.json").read_text(encoding="utf-8"))
    fc = scanner.fc
    return {
        "data": MOCK.name, "history": fm["history"], "split": fm["split"],
        "categories": sorted({p["category"] for p in world.products.values()}),
        "store_hours": f"{rf_config.STORE_OPEN_HOUR:02d}:00-{rf_config.STORE_CLOSE_HOUR:02d}:00",
        "true_lift": TRUE_LIFT, "newest_share": NEWEST_SHARE, "max_hold_days": MAX_HOLD_DAYS,
        "partners": [{"partner_id": pid, "type": r.partner_type, "mode": r.mode, "trip_cost": round(r.trip_cost, 2),
                      "pickup_days": sorted(r.pickup_days)} for pid, r in sorted(world.rules(world.start).items())],
        "forecaster": {"version": rf_config.MODEL_VERSION, "model": "LightGBM" if fm["chosen"] == "lgbm" else fm["chosen"],
                       "trees": fm["params"]["n_estimators"], "features": int(scanner.model.n_features_in_),
                       "trained_until": (TEST_START - timedelta(days=1)).isoformat(),
                       "test_wape": fm["test_wape"], "fva_pct": fm["test_fva_pct"], "bias_pct": fm["test_bias_pct"],
                       "coverage_80": {k: v["coverage_pct"] for k, v in fm["test_coverage_80"].items()},
                       "lifts_used": {str(k): round(v, 3) for k, v in fc.lifts.items()}},
        "risk": {"cutoffs": {k: th[k] for k in ("MEDIUM", "HIGH", "CRITICAL")}, "forward": list(rf_config.FORWARD_LEVELS),
                 "test": th["test"]},
    }


CSS = """
:root{--bg:#fff6ec;--card:#fff;--ink:#3b2a1d;--muted:#7d6552;--accent:#e8853d;--accent-dark:#b35a1b;
--soft:#ffe8d1;--soft2:#fff2e4;--line:#f4e3d2;--bad:#c0392b}
body{margin:0;background:var(--bg);font-family:"Sarabun","Noto Sans Thai","Leelawadee UI",Tahoma,sans-serif;color:var(--ink)}
.page{max-width:1280px;margin:0 auto;padding:32px 40px}
h1{font-size:30px;margin:0 0 4px} h2{font-size:20px;margin:30px 0 12px;color:var(--accent-dark)}
.meta{color:var(--muted);font-size:15px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:22px}
.kpi,table,.note,.card{background:var(--card);border-radius:14px;box-shadow:0 1px 3px rgba(120,70,20,.14)}
.kpi{padding:18px 20px;border-top:5px solid var(--accent)}
.kpi.bad{border-top-color:var(--bad)} .kpi.bad .kpi-sub{color:var(--bad)}
.kpi-label{font-size:14px;color:var(--muted)} .kpi-value{font-size:30px;font-weight:700;margin:6px 0 2px}
.kpi-sub{font-size:14px;color:var(--accent-dark);font-weight:600}
table{width:100%;border-collapse:collapse;overflow:hidden;font-size:15px}
th{background:var(--accent-dark);color:#fff;font-weight:600;padding:10px 12px;text-align:right}
td{padding:9px 12px;text-align:right;border-bottom:1px solid var(--line)}
th.l,td.l{text-align:left} tr:last-child td{border-bottom:none} tr.ours td{background:var(--soft2);font-weight:700}
tr.ref td{color:var(--muted);font-style:italic}
.two{display:grid;grid-template-columns:1fr 1fr;gap:20px} .three{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.note,.card{padding:16px 20px;font-size:14px;line-height:1.65;color:#4a3828}
.card h3{margin:0 0 10px;font-size:16px;color:var(--accent-dark)}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:5px 14px} .kv .k{color:var(--muted)}
table.mini{box-shadow:none;font-size:13px;margin-bottom:12px} table.mini th{padding:6px 8px}
table.mini td{padding:5px 8px}
ul.why{margin:0;padding-left:20px} ul.why li{margin:6px 0}
@media (max-width:900px){.page{padding:20px 16px}.kpis,.two,.three{grid-template-columns:1fr}
table{display:block;overflow-x:auto}}
"""


def render_html(res: dict) -> str:
    p1, p2, p3, env = res["policy1"], res["policy2"], res["policy3"], res["environment"]
    fc, rk, n3 = env["forecaster"], env["risk"], res["policy3"]["notes"]
    ref = res.get("reference")
    mode = res["disposal"]
    e = html.escape
    rows_policy = [("1 · ร้านแบบเดิม", p1), (f"2 · ลดราคาตามกฎตายตัว (ช่วง{res['policy2_variant']})", p2),
                   ("3 · Risk Scanner + Forecaster + Optimizer (main)", p3)]

    def kpi(label, value, sub="", tone=""):
        return (f'<div class="kpi {tone}"><div class="kpi-label">{e(label)}</div>'
                f'<div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>')

    def kv(rows):
        return '<div class="kv">' + "".join(f'<div class="k">{e(k)}</div><div>{v}</div>' for k, v in rows) + "</div>"

    save1, save2 = p3["net_profit"] - p1["net_profit"], p3["net_profit"] - p2["net_profit"]
    tone = lambda x: "" if x >= 0 else "bad"
    loss_cut1 = (p1["waste_loss"] - p3["waste_loss"]) / p1["waste_loss"] * 100 if p1["waste_loss"] else 0
    landfill_cut1 = (p1["landfill_kg"] - p3["landfill_kg"]) / p1["landfill_kg"] * 100 if p1["landfill_kg"] else 0
    calls1, calls3 = sum(p1["calls"].values()), sum(p3["calls"].values())
    half = len(p1["daily"]) // 2
    h1 = p3["daily"][half - 1] - p1["daily"][half - 1]
    h2 = (p3["daily"][-1] - p3["daily"][half - 1]) - (p1["daily"][-1] - p1["daily"][half - 1])

    def row(name, p, cls=""):
        return (f"<tr{f' class={cls}' if cls else ''}><td class='l'>{e(name)}</td><td>{baht(p['net_profit'])}</td>"
                f"<td>{baht(p['revenue'])}</td><td>{baht(p['cogs_waste'])}</td>"
                f"<td>{baht(p['trip_fee'] + p['handling'] - p['buyback'])}</td><td>{baht(p['waste_loss'])}</td>"
                f"<td>{p['waste_kg']:,.0f}</td><td>{sum(p['calls'].values())}</td></tr>")

    table = "".join(row(n, p, "ours" if p is p3 else "") for n, p in rows_policy)
    if ref:
        table += row("อ้างอิง · optimizer-update (กติกาของเรา, 22 ต.ค.)", ref["policy3"], "ref")
    methods = ["SELL_REGULAR", "MARKDOWN", "KITCHEN", "DONATION", "ANIMAL_FEED", "COMPOSTING", "ANAEROBIC_DIGESTION",
               "LANDFILL"]
    mix = "".join(f"<tr><td class='l'>{e(METHOD_TH[m])}</td>" + "".join(
        f"<td>{p['units'].get(m, 0):,}</td>" for _, p in rows_policy) + "</tr>" for m in methods)
    variants = "".join(
        f"<tr><td class='l'>ช่วง{e(k)} ({' / '.join(f'{x}%' for x in FIXED_RULES[k])})</td>"
        f"<td>{baht(v['net_profit'])}</td><td>{baht(v['waste_loss'])}</td>"
        f"<td>{signed(p3['net_profit'] - v['net_profit'])}</td><td>{pct(p3['net_profit'], v['net_profit']):+.1f}%</td></tr>"
        for k, v in res["policy2_variants"].items())
    lift = lambda d: " / ".join(f"{int(k)}% → ×{v:.2f}" for k, v in sorted(d.items(), key=lambda kv: int(kv[0])) if int(k))
    days = "จ อ พ พฤ ศ ส อา".split()
    partners = "".join(
        f"<tr><td class='l'>{e(METHOD_TH.get(p['type'], p['type']))}</td><td>{baht(p['trip_cost'])}</td>"
        f"<td class='l'>{'ถังสะสม' if p['mode'] == 'BIN' else 'เรียกเฉพาะ'}</td>"
        f"<td class='l'>{'ทุกวัน' if len(p['pickup_days']) == 7 else ' '.join(days[d - 1] for d in p['pickup_days'])}</td></tr>"
        for p in env["partners"])
    sp = {k: v.replace("->", "→") for k, v in env["split"].items()}
    store = kv([
        ("ข้อมูล", f"{e(env['data'])} ร้านจำลอง (ยอดขายรายชั่วโมงจาก simulate.py)"),
        ("ข้อมูลทั้งหมด", e(env["history"].replace("->", "→"))),
        ("ช่วงที่ทดสอบ", f"<b>{res['start']} → {res['end']} ({res['days']} วัน)</b> อยู่ในช่วง test ของ Forecaster"),
        ("สินค้า", f"{res['products']} SKU · {len(env['categories'])} หมวด ({e(', '.join(env['categories']))})"),
        ("lot", f"สต็อกวันแรก + ของเข้าร้าน รวม {res['lots_total']:,} lot (ชุดเดียวกันทุกนโยบาย)"),
        ("ลูกค้า", "latent_demand = ความต้องการจริงที่ราคาเต็ม (ไม่ใช่ค่าพยากรณ์)"),
        ("ร้านเปิด", f"{env['store_hours']} · นโยบาย 3 สแกนและตัดสินใจทุกเช้า 08:00"),
        ("ลดราคาแล้วขายเพิ่ม", f"{lift(env['true_lift'])} (ค่าจริงของตัวสร้างข้อมูล)"),
        ("ลูกค้าหยิบ lot", f"ลดราคาก่อน · {env['newest_share']:.0%} หยิบ lot ใหม่สุด · ที่เหลือหมดอายุก่อนได้ก่อน"),
    ])
    cov = " · ".join(f"{k} วัน {v:.1f}%" for k, v in fc["coverage_80"].items())
    model = kv([
        ("โมเดลในเครื่อง", f"{e(fc['version'])}.pkl · {e(fc['model'])} {fc['trees']} ต้นไม้ · {fc['features']} feature"),
        ("แบ่งข้อมูล", f"train {e(sp['train'])}<br>validation {e(sp['validation'])}<br>test {e(sp['test'])}"),
        ("ใน backtest", f"<b>เทรนใหม่ด้วยข้อมูลถึง {fc['trained_until']} เท่านั้น</b> ไม่เห็นยอดขายช่วงทดสอบ"),
        ("ความคลาดเคลื่อน (WAPE)", f"{fc['test_wape']['lgbm']:.2f}% · ค่าเฉลี่ยวันเดียวกันของสัปดาห์ "
                                   f"{fc['test_wape']['same_dow']:.2f}% (ดีกว่า {fc['fva_pct']:.1f}%)"),
        ("ทายเกิน/ขาดรวม", f"{fc['bias_pct']:+.2f}%"),
        ("ยอดจริงตกในช่วงพยากรณ์ 80%", cov),
        ("lift ที่โมเดลประมาณ", f"{lift(fc['lifts_used'])} (จากข้อมูลก่อน test)"),
        ("Risk Scanner", f"เกณฑ์ MEDIUM / HIGH / CRITICAL = {' / '.join(str(v) for v in rk['cutoffs'].values())} · "
                         f"ส่งต่อ {e(' + '.join(rk['forward']))}"),
        ("Risk Scanner ช่วง test", f"แม่น (precision) {rk['test']['forward_precision']:.1%} · "
                                   f"จับได้ (recall) {rk['test']['forward_recall']:.1%}"),
    ])
    rule_text = (f"เรียกรถเมื่อถังถึงปริมาณที่คุ้ม หรือของรอเกิน {env['max_hold_days']:g} วัน (เหมือน backtest 22 ต.ค.)"
                 if mode == "bins" else
                 "รถมาทุกวันที่มีรอบรับและมีของรอ คิดค่าเที่ยวเต็มทุกครั้ง (วิธีที่ Optimizer บน main คิดต้นทุน)")
    disposal = (f"<table class='mini'><tr><th class='l'>partner (Supabase 22 ต.ค.)</th><th>บาท/ครั้ง</th>"
                f"<th class='l'>โหมด</th><th class='l'>วันรับ</th></tr>{partners}</table>") + kv([
        ("กติการถ", f"<b>{e(MODE_TH[mode])}</b>: {rule_text} · เหมือนกันทุกนโยบาย"),
        ("นโยบาย 1-2", "ของหมดอายุไปฝังกลบอย่างเดียว"),
        ("นโยบาย 3", "เลือกได้ทุก partner + เข้าครัว + ลดราคา · ของหมดอายุที่ไม่มี decision ค้างในร้านรอรอบสแกนถัดไป"),
        ("ปิดรอบ", "วันสุดท้ายเก็บถังที่เหลือ + ของหมดอายุที่ค้างในร้านไปฝังกลบ (ทุกนโยบาย)"),
    ])
    tasks = n3.get("tasks_approved", 0) + n3.get("tasks_rejected", 0)
    due_today = n3.get("partner_tasks_due_today", 0) / n3["partner_tasks"] * 100 if n3.get("partner_tasks") else 100.0
    scans_per_lot = n3.get("lots_scanned", 0) / res["lots_total"] if res["lots_total"] else 0
    lifecycle = (
        "<table><tr><th class='l'>ตัวชี้วัด</th><th>ค่า</th><th class='l'>ความหมาย</th></tr>" + "".join(
            f"<tr><td class='l'>{e(k)}</td><td>{v}</td><td class='l'>{e(m)}</td></tr>" for k, v, m in [
                ("task ทั้งหมด", f"{tasks:,} ({tasks / res['days']:.1f}/วัน)",
                 f"อนุมัติ {n3.get('tasks_approved', 0):,} · ปฏิเสธ {n3.get('tasks_rejected', 0):,} (approve_rate {res['approve_rate']:g})"),
                ("task เอาของออกที่ due วันนี้", f"{due_today:.1f}%", "กติกาของ main ต้องได้ 100%"),
                ("วันที่ lot ได้แผนชั่วคราว", f"{n3.get('deferral_days', 0):,}",
                 f"ไม่มี decision แล้วสแกนใหม่ ({n3.get('lots_deferred', 0):,} lot ไม่ซ้ำ)"),
                ("หน่วย x วัน ของหมดอายุค้างในร้าน", f"{n3.get('expired_unit_days', 0):,}",
                 f"{n3.get('lots_expired_in_store', 0):,} lot ข้ามคืนหลังหมดอายุ ไม่มี decision คืนนั้นเพราะ: "
                 f"Risk Scanner ให้ LOW / MEDIUM ในวันหมดอายุ {n3.get('expired_overnight_not_forwarded', 0):,} · "
                 f"แผนส่งเที่ยวพรุ่งนี้ (แผนชั่วคราว) {n3.get('expired_overnight_provisional', 0):,} · "
                 f"แผนคาดว่าขายหมด {n3.get('expired_overnight_expected_sell_out', 0):,} · "
                 f"มี decision แต่ของเหลือเกินแผน {n3.get('expired_overnight_decision_short', 0):,}"),
                ("… ค้างเกิน 1 คืน", f"{n3.get('expired_unit_days_over_1_night', 0):,}",
                 f"{n3.get('lots_expired_over_1_night', 0):,} lot สแกนเช้าแล้วยังไม่มีใครเอาออก เช่น วันที่ไม่มีรถรับ "
                 "(ประกาศ สธ. 367 ห้ามวางขายหลังหมดอายุ)"),
                ("ของหมดอายุที่ไม่เคยได้ decision", f"{n3.get('expired_flushed_units', 0):,} หน่วย",
                 f"ทิ้ง landfill ตอนปิดรอบ ต้นทุน {baht(n3.get('expired_flushed_cost', 0))} บาท"),
                ("lot ค้าง PROCESSING", f"{n3.get('stuck_processing', 0):,}",
                 f"ส่งต่อ Optimizer แล้วไม่ได้ decision และไม่ถูกคืน IDLE (ไม่ถูกสแกนอีก) · เพราะ portion 0 หน่วยที่ไม่ใช่"
                 f"แผนชั่วคราวขวาง lots_to_release {n3.get('stuck_zero_unit_portion', 0):,}"),
                ("การสแกน", f"{n3.get('lots_scanned', 0):,} ครั้ง ({scans_per_lot:.1f}/lot)",
                 f"ส่งต่อ Optimizer {n3.get('lots_forwarded', 0):,} ครั้ง · Optimizer error {n3.get('optimizer_errors', 0)} วัน"),
            ]) + "</table>")
    why = "".join(f"<li>{x}</li>" for x in [
        f"<b>ค่าเรียกรถ:</b> ร้านแบบเดิม {baht(p1['trip_fee'])} บาท ({calls1} ครั้ง) · ของเรา {baht(p3['trip_fee'])} บาท "
        f"({calls3} ครั้ง) ภายใต้กติการถแบบ{e(MODE_TH[mode])}",
        f"<b>Risk Scanner จับ lot ที่จะเหลือได้ราว {rk['test']['forward_recall']:.0%}:</b> "
        f"lot ที่หลุดการตรวจจับถูกทิ้งเหมือนร้านเดิม",
        f"<b>แผนชั่วคราว {n3.get('deferral_days', 0):,} ครั้ง:</b> Optimizer ของ main คิดค่าเที่ยวของวันถัดไป 0 บาท "
        f"(deferred_trip_cost_share = 0) จึงวางแผนส่งเที่ยวพรุ่งนี้ แต่พอถึงวันนั้นเที่ยวคิดเต็ม แผนจึงเปลี่ยน · "
        f"รถที่เรียกจริงมีแค่ {e(', '.join(sorted(p3['calls'])) or '-')}",
        f"<b>ไม่มีขั้นกำจัดตอนปิดร้าน:</b> lot ที่ไม่ได้ decision END_OF_LIFE คืนวันหมดอายุ (ส่วนใหญ่เพราะ Risk Scanner ให้ "
        f"LOW / MEDIUM) ค้างในร้านจนรอบสแกนเช้า ({n3.get('expired_unit_days', 0):,} หน่วย x วัน)",
        f"<b>ร้านเล็ก ข้อมูล mock:</b> {res['products']} SKU ผลจึงควรดูเป็น % มากกว่าจำนวนบาท",
    ])
    ref_note = (f" · แถว 'อ้างอิง' มาจาก {e(ref['source'])} (กติการถ {e(MODE_TH.get(ref.get('disposal', 'bins'), 'bins'))})"
                if ref else "")

    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtest main {e(mode)}</title><style>{CSS}</style></head><body><div class="page">
<h1>Backtest {res['days']} วัน: โค้ด AI บน main · กติการถ{e(MODE_TH[mode])}</h1>
<div class="meta">ร้านจำลองจาก {e(env['data'])} · {res['start']} ถึง {res['end']} (ช่วง test ของ Forecaster) · สินค้า {res['products']} SKU ·
lot เข้าร้าน {res['lots_total']:,} lot · ลูกค้าจริงจาก latent_demand · หน่วยเงิน: บาท</div>

<div class="kpis">
{kpi("กำไรสุทธิ · นโยบาย 3 (main)", baht(p3['net_profit']), f"ร้านแบบเดิม {baht(p1['net_profit'])} · กฎตายตัว {baht(p2['net_profit'])}")}
{kpi("กำไรสุทธิ เทียบร้านแบบเดิม (บาท)", signed(save1), f"{pct(p3['net_profit'], p1['net_profit']):+.2f}%", tone(save1))}
{kpi("กำไรสุทธิ เทียบลดราคาตามกฎ (บาท)", signed(save2), f"{pct(p3['net_profit'], p2['net_profit']):+.2f}%", tone(save2))}
{kpi("ความเสียหายจากของทิ้งลดลง เทียบร้านแบบเดิม", f"{loss_cut1:.1f}%", f"ฝังกลบ {p1['landfill_kg']:,.0f} → {p3['landfill_kg']:,.0f} kg ({-landfill_cut1:+.1f}%)", tone(loss_cut1))}
</div>

<h2>เทียบ 3 นโยบาย</h2>
<table><tr><th class="l">นโยบาย</th><th>กำไรสุทธิ</th><th>รายได้ขาย</th><th>ต้นทุนของที่ทิ้ง</th>
<th>ค่ากำจัดสุทธิ</th><th>ความเสียหายจากของทิ้ง</th><th>ของทิ้ง (kg)</th><th>เรียกรถ (ครั้ง)</th></tr>{table}</table>

<h2>วงจร lot แบบ main (decision เอาของออกเฉพาะวันนี้ · แผนวันอื่นเป็นแผนชั่วคราว)</h2>
<div class="two"><div>{lifecycle}</div><div class="card"><h3>อ่านผลอย่างไร</h3><ul class="why">{why}</ul></div></div>

<h2>สภาพแวดล้อมที่ใช้ทดสอบ</h2>
<div class="three">
<div class="card"><h3>ร้านจำลองและช่วงเวลา</h3>{store}</div>
<div class="card"><h3>Forecaster + Risk Scanner</h3>{model}</div>
<div class="card"><h3>การกำจัดและ partner</h3>{disposal}</div>
</div>

<div class="two">
<div><h2>สินค้าไปทางไหน (หน่วย)</h2>
<table><tr><th class="l">วิธี</th><th>1 · เดิม</th><th>2 · กฎตายตัว</th><th>3 · main</th></tr>{mix}</table></div>
<div><h2>เทียบกฎตายตัวทุกช่วงส่วนลด</h2>
<table><tr><th class="l">ส่วนลด (≥3 / 2 / 1 วัน / วันสุดท้าย)</th><th>กำไรสุทธิ</th><th>ความเสียหาย</th>
<th>main ดีกว่า (บาท)</th><th>%</th></tr>{variants}</table>
<h2>ความสม่ำเสมอ</h2>
<div class="note">กำไรของ main เทียบร้านแบบเดิม: {half} วันแรก <b>{signed(h1)}</b> บาท · {len(p1['daily']) - half} วันหลัง <b>{signed(h2)}</b> บาท ·
decision ลดราคา {n3.get('decision_MARKDOWN', 0)} · เข้าครัว {n3.get('decision_KITCHEN_REPURPOSE', 0)} · ฝังกลบ {n3.get('decision_LANDFILL', 0)} ·
ทิ้งเอง (DISCARD) {n3.get('decision_DISCARD', 0)}</div></div>
</div>

<h2>วิธีคิดเงินและข้อจำกัด</h2>
<div class="note">
<b>กำไรสุทธิ</b> = รายได้ขาย + มูลค่าเมนูครัว + รับซื้อคืน − ค่าเรียกรถ − handling − ต้นทุนสินค้าทุกหน่วยที่ออกจากร้าน ·
<b>ความเสียหายจากของทิ้ง</b> = ต้นทุนของที่ทิ้ง + ค่าเรียกรถ + handling − รับซื้อคืน ·
<b>นโยบาย 2</b> เทียบกับช่วงส่วนลดที่ได้กำไรมากสุด ·
<b>ข้อจำกัด:</b> ข้ามขั้น LLM (decision 1 ตัว = task 1 ตัว), ทุก task เสร็จในวันที่ออก (งานครัวของพรุ่งนี้ทำวันนี้),
มูลค่าเมนูครัวใช้ค่าคาดหมายของแผน, ข้อมูลเป็น mock {res['products']} SKU{ref_note}
</div>
</div></body></html>"""


def run_mode(world: World, scanner: ScanModel, approve_rate: float) -> dict:
    p1 = summarize(run_rule_policy(world, "policy1", None))
    print(f"  1 ร้านแบบเดิม           กำไรสุทธิ {p1['net_profit']:>12,.2f}  ความเสียหาย {p1['waste_loss']:>10,.2f}")
    variants = {}
    for k, rule in FIXED_RULES.items():
        variants[k] = summarize(run_rule_policy(world, f"policy2_{k}", rule))
        print(f"  2 กฎตายตัว ช่วง{k:<5}      กำไรสุทธิ {variants[k]['net_profit']:>12,.2f}  ความเสียหาย {variants[k]['waste_loss']:>10,.2f}")
    best2 = max(variants, key=lambda k: variants[k]["net_profit"])     # เทียบกับกฎที่ดีที่สุด (ไม่ให้ตัวเลขดูดีเกินจริง)
    print("  3 Risk Scanner + Forecaster + Optimizer ของ main (รายวัน) ...")
    p3 = summarize(LifecyclePolicy(world, scanner, approve_rate).run())
    print(f"  3 main                   กำไรสุทธิ {p3['net_profit']:>12,.2f}  ความเสียหาย {p3['waste_loss']:>10,.2f}")
    return {"start": world.start.isoformat(), "end": world.end.isoformat(), "days": (world.end - world.start).days + 1,
            "disposal": world.disposal, "approve_rate": approve_rate, "products": len(world.products),
            "lots_total": len(world.initial) + sum(len(v) for v in world.deliveries.values()),
            "policy1": p1, "policy2": variants[best2], "policy2_variant": best2, "policy2_variants": variants,
            "policy3": p3,
            "saving_vs_policy1_thb": round(p3["net_profit"] - p1["net_profit"], 2),
            "saving_vs_policy1_pct": round(pct(p3["net_profit"], p1["net_profit"]), 2),
            "saving_vs_policy2_thb": round(p3["net_profit"] - variants[best2]["net_profit"], 2),
            "saving_vs_policy2_pct": round(pct(p3["net_profit"], variants[best2]["net_profit"]), 2),
            "environment": environment(world, scanner)}


def load_reference(path: Path | None, res: dict) -> dict | None:
    """ผล backtest ของ optimizer-update (กติกาของเรา) ใช้เทียบได้เมื่อช่วงวันและกติการถตรงกันเท่านั้น"""
    if path is None or not path.exists():
        return None
    ref = json.loads(path.read_text(encoding="utf-8"))
    if (ref["start"], ref["days"], ref.get("disposal", "bins")) != (res["start"], res["days"], res["disposal"]):
        return None
    return {"source": path.name, "disposal": ref.get("disposal", "bins"), "policy3": ref["policy3"],
            "policy1_net_profit": ref["policy1"]["net_profit"]}


def write(out: Path, res: dict) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    mode = res["disposal"]
    (out / f"backtest_result_{mode}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    page = out / f"backtest_report_{mode}.html"
    page.write_text(render_html(res), encoding="utf-8")
    return page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=date(2026, 8, 17))
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--disposal", choices=[*DISPOSAL_MODES, "both"], default="both")
    ap.add_argument("--approve-rate", type=float, default=1.0, help="สัดส่วน task ที่ผู้จัดการอนุมัติ (ที่เหลือถูกปฏิเสธ)")
    ap.add_argument("--compare", type=Path, default=HERE / "data" / "reference_optimizer-update.json",
                    help="ผลของ optimizer-update ไว้เทียบ (ใช้เมื่อช่วงวันและกติการถตรงกัน)")
    ap.add_argument("--out", type=Path, default=HERE / "output")
    ap.add_argument("--render-only", action="store_true", help="สร้าง HTML ใหม่จาก backtest_result_<โหมด>.json เดิม")
    args = ap.parse_args()
    modes = DISPOSAL_MODES if args.disposal == "both" else (args.disposal,)
    if args.render_only:
        for mode in modes:
            path = args.out / f"backtest_result_{mode}.json"
            if path.exists():
                print(f"ไฟล์: {write(args.out, json.loads(path.read_text(encoding='utf-8')))}")
        return
    if args.start < TEST_START:
        raise SystemExit(f"--start ต้องไม่ก่อน {TEST_START} (Forecaster ต้องไม่เห็นข้อมูลช่วงที่ทดสอบ)")
    scanner = ScanModel()                                              # เทรนครั้งเดียว ใช้ทุกกติการถ
    summary = []
    for mode in modes:
        world = World(args.start, args.days, mode)
        print(f"\n[{mode}] backtest {world.start} -> {world.end} | lot เริ่ม {len(world.initial)} | ของเข้าร้าน "
              f"{sum(len(v) for v in world.deliveries.values())} lot")
        res = run_mode(world, scanner, args.approve_rate)
        res["reference"] = load_reference(args.compare, res)
        page = write(args.out, res)
        n3 = res["policy3"]["notes"]
        summary.append(f"[{mode}] main vs ร้านแบบเดิม {res['saving_vs_policy1_thb']:+,.2f} บาท "
                       f"({res['saving_vs_policy1_pct']:+.2f}%) | vs กฎตายตัว ({res['policy2_variant']}) "
                       f"{res['saving_vs_policy2_thb']:+,.2f} บาท ({res['saving_vs_policy2_pct']:+.2f}%) | "
                       f"ของหมดอายุค้างในร้าน {n3.get('expired_unit_days', 0):,} หน่วย x วัน | ไฟล์: {page}")
        if res["reference"]:
            ref = res["reference"]["policy3"]["net_profit"]
            summary.append(f"[{mode}] อ้างอิง optimizer-update กำไรสุทธิ {ref:,.2f} | main {res['policy3']['net_profit']:,.2f} "
                           f"(ต่าง {res['policy3']['net_profit'] - ref:+,.2f} บาท)")
    print("\n" + "\n".join(summary))


if __name__ == "__main__":
    main()
