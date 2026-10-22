"""กดรันครั้งเดียว (one-shot): lot ทั้งหมดในร้าน ณ เช้าวันเดียว -> แต่ละนโยบายทำงาน 1 วัน -> สรุปผลของวันนั้นวันเดียว

ไม่คิดถึงวันข้างหน้า: ไม่มีของเข้าร้านเพิ่ม ไม่มีรอบสแกนพรุ่งนี้ ครัวใช้ชั่วโมงของวันนี้เท่านั้น
ของที่ยังไม่หมดอายุตอนปิดร้าน = สต็อกคงเหลือ คิดที่ต้นทุน (ไม่กำไรไม่ขาดทุน) แสดงมูลค่าราคาขายแยกไว้ให้เห็น
รถของ partner: แบบ dedicated (มาวันนี้ถ้ามีรอบรับและมีของ) ของที่รอรถวันอื่นแสดงเป็น "รอรถ" ยังไม่คิดค่าเที่ยว

ใช้งาน (จากโฟลเดอร์ AI/backtest, Python ที่มี lightgbm + scipy เช่น server/.venv):
    python run_oneshot.py                                  # 27 lot ของ demo วันที่ 2026-10-16 (= DEMO_DATE)
    python run_oneshot.py --source history --date 2026-09-18   # lot ทุก lot บนชั้นเช้าวันนั้น + ลูกค้าจริง

แหล่ง lot (--source):
  demo     mock_v3/inventory_lots_demo.csv 27 lot (ชุดเดียวกับ demo บน Supabase) วันที่ 2026-10-16
           ลูกค้าวันนั้นไม่มีใน mock (ข้อมูลจบ 15 ต.ค.) -> latent_demand เฉลี่ยของวันเดียวกันในสัปดาห์ 4 สัปดาห์ก่อน
           Forecaster ใช้โมเดลตัวจริงในเครื่อง (เทรนถึง 15 ต.ค. เหมือน run_scan.py)
  history  lot ทุก lot บนชั้นเช้าวัน --date จาก lot_daily.csv ลูกค้า = latent_demand จริงของวันนั้น
           Forecaster เทรนใหม่ด้วยข้อมูลก่อนวันนั้นเท่านั้น
"""
from __future__ import annotations

import argparse
import copy
import html
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from world import FIXED_RULES, HERE, METHOD_TH, MOCK, Bin, Ledger, Lot, World, apply_fixed_rule, end_of_day_pickups, sell
from policy_lifecycle import LifecyclePolicy, ScanModel
from run_backtest import CSS, baht, pct, signed, summarize

DEMO_DATE = date(2026, 10, 16)
ACTION_TH = {"MARKDOWN": "ลดราคา", "KITCHEN_REPURPOSE": "เข้าครัว", "DONATE": "บริจาค", "ANIMAL_FEED": "อาหารสัตว์",
             "COMPOST": "ปุ๋ยหมัก", "ANAEROBIC_DIGESTION": "ก๊าซชีวภาพ", "LANDFILL": "ฝังกลบ", "DISCARD": "ทิ้งเอง"}


# ---------------------------------------------------------------- lot + ลูกค้าของวันนั้น
def demo_lots(world: World) -> list:
    df = pd.read_csv(MOCK / "inventory_lots_demo.csv")
    return [Lot(r.lot_id, r.product_id, date.fromisoformat(r.received_date), date.fromisoformat(r.expiration_date),
                int(r.current_quantity), float(r.unit_cost), float(r.current_selling_price),
                float(world.products[r.product_id]["regular_price"]))
            for r in df.itertuples() if r.current_quantity > 0]


def proxy_demand(world: World, d: date, weeks: int = 4) -> dict:
    """ยอดลูกค้าแทนของจริง: latent_demand เฉลี่ยของวันเดียวกันในสัปดาห์ย้อนหลัง (ไม่ใช่ค่าที่ Forecaster ทาย)"""
    same = [d - timedelta(days=7 * i) for i in range(1, weeks + 1)]
    out = {}
    for pid in world.products:
        vals = [world.demand[(pid, x)] for x in same if (pid, x) in world.demand]
        if vals:
            out[(pid, d)] = int(round(sum(vals) / len(vals)))
    return out


def fresh(base: list) -> list:
    return [copy.copy(l) for l in base]


# ---------------------------------------------------------------- 1 วันต่อนโยบาย
def day_summary(led: Ledger, lots: list, bins: dict, d: date, base: list) -> dict:
    left = [l for l in lots if l.qty > 0]
    units_in = sum(l.qty for l in base)
    if units_in != led.units_out() + sum(l.qty for l in left):            # ของไม่หาย / ไม่งอกระหว่างวัน
        raise AssertionError(f"{led.name}: ของเช้า {units_in} != ออก {led.units_out()} + คงเหลือ {sum(l.qty for l in left)}")
    expired = [l for l in left if l.expiry <= d]
    s = summarize(led)
    # ของหมดอายุที่ยังค้างในร้านขายไม่ได้แล้ว: ตัดต้นทุนเป็นขาดทุนวันนี้ (ค่ารถ / handling ยังไม่เกิด จึงไม่รวม)
    write_off = round(sum(l.qty * l.cost for l in expired), 2)
    s["net_profit_cash"], s["net_profit"] = s["net_profit"], round(s["net_profit"] - write_off, 2)
    s["expired_left_cost"] = write_off
    s.update({
        "ending_units": sum(l.qty for l in left), "ending_cost": round(sum(l.qty * l.cost for l in left), 2),
        "ending_retail": round(sum(l.qty * l.regular for l in left), 2),
        "ending_markdown_units": sum(l.qty for l in left if l.disc > 0.5),
        "expired_left_units": sum(l.qty for l in expired), "expired_left_lots": len(expired),
        "waiting_kg": round(sum(b.kg for b in bins.values()), 3),
    })
    return s


def run_rule_day(world: World, base: list, d: date, name: str, discounts: tuple | None = None) -> dict:
    led, bins, lots = Ledger(name), defaultdict(Bin), fresh(base)
    if discounts:
        apply_fixed_rule(world, lots, d, discounts)
    sell(world, lots, d, led)
    end_of_day_pickups(bins, world.rules(d), d, led, world, lots)       # ของหมดอายุคืนนี้ทิ้ง landfill เอง
    return day_summary(led, lots, bins, d, base)


def run_main_day(world: World, base: list, d: date, scanner: ScanModel, approve_rate: float) -> tuple:
    led, bins, lots = Ledger("main"), defaultdict(Bin), fresh(base)
    pol = LifecyclePolicy(world, scanner, approve_rate, kitchen_days=(0,), with_baselines=True)
    pol.day(lots, bins, d, led)                                          # SCAN -> OPTIMIZE -> TASKS -> ลงมือ
    status = Counter(l.status for l in lots if l.scans)                  # ก่อน task จบ (CHECKED = มี task)
    sell(world, lots, d, led)
    end_of_day_pickups(bins, world.rules(d), d, led, world, lots, auto_landfill=False)
    pol.end_of_day(lots, d)
    s = day_summary(led, lots, bins, d, base)
    s["notes"].update(pol.stats)
    s["status_after_optimize"] = dict(status)
    return s, pol


def optimizer_view(world: World, pol: LifecyclePolicy) -> dict:
    """สิ่งที่ Optimizer สั่ง (task) / แผนชั่วคราว / ระดับความเสี่ยง ของรอบนี้ สำหรับรายงาน"""
    res = pol.last_result
    scan = pol.last_scan
    levels = Counter(p["risk_level"] for p in scan.values())
    if res is None:
        return {"levels": dict(levels), "decisions": [], "provisional": [], "baselines": {}, "expected_net": None,
                "released": [], "lots_forwarded": 0}
    plan = res["plan"]
    by_assessment = {lo["assessment_id"]: lo for lo in plan["lots"]}
    decisions = []
    for x in res["payload"]["decisions"]:
        lo = by_assessment[x["assessment_id"]]
        decisions.append({"lot_id": lo["lot_id"], "name": lo["name"], "risk": lo["risk_level"],
                          "days_to_expiry": lo["days_to_expiry"], "action": x["action_type"],
                          "quantity": x["action_quantity"], "lot_quantity": lo["quantity"],
                          "price": x.get("new_recommended_price"), "partner": x.get("target_partner_id"),
                          "due_by": x.get("due_by"), "expected_thb": x["expected_profit_impact"]})
    provisional = [{"lot_id": lo["lot_id"], "name": lo["name"], "method": p["method"], "units": p["units"],
                    "timing": p["details"].get("timing"), "pickup_at": p["details"].get("pickup_at")}
                   for lo in plan["lots"] for p in lo["portions"] if p["details"].get("provisional") and p["units"] > 0]
    return {"levels": dict(levels), "decisions": decisions, "provisional": provisional,
            "baselines": plan.get("baselines") or {}, "expected_net": plan["summary"]["net_profit_thb"],
            "released": res["lots_to_release"], "lots_forwarded": len(plan["lots"]),
            "warnings": [w for w in plan.get("warnings", []) if not w.startswith("A3_")][:12]}


# ---------------------------------------------------------------- รายงาน
def render_html(res: dict) -> str:
    e = html.escape
    p1, p2, p3, ov = res["policy1"], res["policy2"], res["policy3"], res["optimizer"]
    rows = [("1 · ร้านแบบเดิม", p1), (f"2 · ลดราคาตามกฎตายตัว (ช่วง{res['policy2_variant']})", p2),
            ("3 · Risk Scanner + Forecaster + Optimizer (main)", p3)]

    def kpi(label, value, sub="", tone=""):
        return (f'<div class="kpi {tone}"><div class="kpi-label">{e(label)}</div>'
                f'<div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>')

    tone = lambda x: "" if x >= 0 else "bad"
    save1, save2 = p3["net_profit"] - p1["net_profit"], p3["net_profit"] - p2["net_profit"]
    table = "".join(
        f"<tr{' class=ours' if p is p3 else ''}><td class='l'>{e(n)}</td><td>{baht(p['net_profit'])}</td>"
        f"<td>{baht(p['revenue'])}</td><td>{p['sold_units']:,}</td><td>{p['waste_units']:,}</td>"
        f"<td>{baht(p['trip_fee'] + p['handling'] - p['buyback'])}</td><td>{p['ending_units']:,}</td>"
        f"<td>{baht(p['ending_retail'])}</td><td>{p['expired_left_units']:,}</td></tr>" for n, p in rows)
    methods = ["SELL_REGULAR", "MARKDOWN", "KITCHEN", "DONATION", "ANIMAL_FEED", "COMPOSTING", "ANAEROBIC_DIGESTION",
               "LANDFILL"]
    mix = "".join(f"<tr><td class='l'>{e(METHOD_TH[m])}</td>" + "".join(
        f"<td>{p['units'].get(m, 0):,}</td>" for _, p in rows) + "</tr>" for m in methods)
    target = lambda x: f"{x['price']:,.2f} บาท" if x["price"] else (x["partner"] or "-")
    dec = "".join(
        f"<tr><td class='l'>{e(x['lot_id'])}</td><td class='l'>{e(x['name'])}</td><td class='l'>{e(x['risk'])}</td>"
        f"<td>{x['days_to_expiry']}</td><td class='l'>{e(ACTION_TH.get(x['action'], x['action']))}</td>"
        f"<td>{x['quantity']:,} / {x['lot_quantity']:,}</td><td class='l'>{e(target(x))}</td>"
        f"<td class='l'>{e(str(x['due_by'] or '-')[:16].replace('T', ' '))}</td><td>{signed(x['expected_thb'])}</td></tr>"
        for x in ov["decisions"]) or "<tr><td class='l' colspan=9>ไม่มี task</td></tr>"
    prov = "".join(
        f"<tr><td class='l'>{e(x['lot_id'])}</td><td class='l'>{e(x['name'])}</td>"
        f"<td class='l'>{e(METHOD_TH.get(x['method'], x['method']))}</td><td>{x['units']:,}</td>"
        f"<td class='l'>{e(x['timing'] or '-')}</td><td class='l'>{e(str(x['pickup_at'] or '-')[:16].replace('T', ' '))}</td></tr>"
        for x in ov["provisional"]) or "<tr><td class='l' colspan=6>ไม่มี</td></tr>"
    base_th = {"do_nothing_no_disposal_cost": "ไม่ทำอะไร (ไม่คิดค่ากำจัด)", "regular_price_then_landfill": "ขายราคาปกติแล้วฝังกลบ",
               "markdown_then_landfill": "ลดราคาแล้วฝังกลบ", "optimized": "ตามแผน Optimizer"}
    base_rows = "".join(f"<tr{' class=ours' if k == 'optimized' else ''}><td class='l'>{e(base_th[k])}</td>"
                        f"<td>{baht(v['net_profit_thb'])}</td></tr>"
                        for k, v in ov["baselines"].items() if k in base_th and isinstance(v, dict))
    n3 = p3["notes"]
    st = p3.get("status_after_optimize", {})
    levels = " · ".join(f"{k} {v}" for k, v in sorted(ov["levels"].items(), key=lambda kv: kv[0]))
    status = (f"สแกน {n3.get('lots_scanned', 0)} lot ({e(levels)}) · ส่งต่อ Optimizer {ov['lots_forwarded']} lot · "
              f"มี task (CHECKED) {st.get('CHECKED', 0)} · คืน IDLE ทันที {len(ov['released'])} · "
              f"ค้าง PROCESSING {n3.get('stuck_processing', 0)} · task เอาของออก due วันนี้ "
              f"{n3.get('partner_tasks_due_today', 0)}/{n3.get('partner_tasks', 0)}")
    warn = "".join(f"<li>{e(w)}</li>" for w in ov.get("warnings", []))
    src = res["source_text"]

    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>One-shot {res['date']}</title><style>{CSS}</style></head><body><div class="page">
<h1>กดรันครั้งเดียว: {res['date']} · {res['lots']} lot · {res['units']:,} ชิ้น</h1>
<div class="meta">{e(src)} · ผลของวันนี้วันเดียว ไม่มีของเข้าร้าน / ไม่มีรอบสแกนพรุ่งนี้ · หน่วยเงิน: บาท</div>

<div class="kpis">
{kpi("กำไรสุทธิวันนี้ · main", baht(p3['net_profit']), f"ร้านแบบเดิม {baht(p1['net_profit'])} · กฎตายตัว {baht(p2['net_profit'])}")}
{kpi("เทียบร้านแบบเดิม (บาท)", signed(save1), f"{pct(p3['net_profit'], p1['net_profit']):+.1f}%", tone(save1))}
{kpi("เทียบลดราคาตามกฎ (บาท)", signed(save2), f"{pct(p3['net_profit'], p2['net_profit']):+.1f}%", tone(save2))}
{kpi("ของหมดอายุค้างในร้านคืนนี้ · main", f"{p3['expired_left_units']:,} ชิ้น",
     f"{p3['expired_left_lots']} lot ไม่มี task เอาออก (ร้านเดิมทิ้งเองตอนปิดร้าน)", "bad" if p3['expired_left_units'] else "")}
</div>

<h2>ผลของวันนี้</h2>
<table><tr><th class="l">นโยบาย</th><th>กำไรสุทธิวันนี้</th><th>รายได้ขาย</th><th>ขายได้ (ชิ้น)</th><th>ทิ้ง / partner (ชิ้น)</th>
<th>ค่ากำจัดสุทธิ</th><th>สต็อกเหลือ (ชิ้น)</th><th>มูลค่าราคาปกติของสต็อกเหลือ</th><th>หมดอายุค้างร้าน (ชิ้น)</th></tr>{table}</table>

<h2>สิ่งที่ Optimizer สั่ง (task วันนี้)</h2>
<div class="note">{status}</div>
<table><tr><th class="l">lot</th><th class="l">สินค้า</th><th class="l">ความเสี่ยง</th><th>เหลือ (วัน)</th><th class="l">ทำอะไร</th>
<th>จำนวน / lot</th><th class="l">ราคาใหม่ / partner</th><th class="l">ทำภายใน</th><th>กำไรที่คาด</th></tr>{dec}</table>

<div class="two">
<div><h2>แผนชั่วคราว (ไม่มี task วันนี้ · lot คืน IDLE)</h2>
<table><tr><th class="l">lot</th><th class="l">สินค้า</th><th class="l">วิธี</th><th>ชิ้น</th><th class="l">ช่วง</th><th class="l">รถมารับ</th></tr>{prov}</table></div>
<div><h2>สินค้าไปทางไหนวันนี้ (ชิ้น)</h2>
<table><tr><th class="l">วิธี</th><th>1 · เดิม</th><th>2 · กฎตายตัว</th><th>3 · main</th></tr>{mix}</table></div>
</div>

<div class="two">
<div><h2>Optimizer ประเมินเอง (ทั้งอายุที่เหลือของ lot เสี่ยง)</h2>
<table><tr><th class="l">ทางเลือก</th><th>กำไรสุทธิที่คาด</th></tr>{base_rows}</table>
<div class="note">ตัวเลขนี้คิดยอดขายจนหมดอายุของ lot ที่ส่งต่อ ({ov['lots_forwarded']} lot) ไม่ใช่ผลวันเดียวด้านบน</div></div>
<div><h2>คำเตือนจาก Optimizer</h2><div class="note"><ul class="why">{warn or '<li>ไม่มี</li>'}</ul></div></div>
</div>

<h2>วิธีคิดและข้อจำกัด</h2>
<div class="note">
<b>กำไรสุทธิวันนี้</b> = รายได้ขาย + มูลค่าเมนูครัว + รับซื้อคืน − ค่ารถ − handling − ต้นทุนของทุกชิ้นที่ออกจากร้านวันนี้
− ต้นทุนของหมดอายุที่ยังค้างในร้าน (ขายไม่ได้แล้ว แต่ค่ารถ / handling ของส่วนนี้ยังไม่เกิดจึงไม่รวม: main ได้เปรียบเล็กน้อย) ·
สต็อกที่เหลือคิดที่ต้นทุน (ไม่กำไรไม่ขาดทุน) <b>ผลวันเดียวจึงเข้าข้างการลดราคา</b>: ของที่ลดราคาขายวันนี้อาจขายราคาเต็มได้พรุ่งนี้
ให้ดู "มูลค่าราคาปกติของสต็อกเหลือ" ประกอบ ·
รถ partner มาวันนี้ถ้ามีรอบรับ ของที่ต้องรอรถวันอื่น {p3['waiting_kg']:.1f} kg (main) ยังไม่คิดค่าเที่ยว ·
นโยบาย 1-2 ทิ้งของหมดอายุคืนนี้เองตอนปิดร้าน นโยบาย 3 ทิ้งเฉพาะที่มี task ·
ข้ามขั้น LLM (decision 1 ตัว = task 1 ตัว อนุมัติ {res['approve_rate']:g})
</div>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["demo", "history"], default="demo")
    ap.add_argument("--date", type=date.fromisoformat, default=None, help="demo: 2026-10-16 · history: ต้องระบุ")
    ap.add_argument("--approve-rate", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=HERE / "output")
    args = ap.parse_args()
    if args.source == "demo":
        d = args.date or DEMO_DATE
        world = World(d, 1, "dedicated")
        base = demo_lots(world)
        world.demand.update(proxy_demand(world, d))
        scanner = ScanModel(until=None)                                    # โมเดลตัวจริง (เทรนถึงวันก่อน demo)
        src = (f"demo: inventory_lots_demo.csv (ชุดเดียวกับ Supabase) · ลูกค้า = latent_demand เฉลี่ยวัน"
               f"{'จ อ พ พฤ ศ ส อา'.split()[d.weekday()]} 4 สัปดาห์ก่อน (ไม่มีข้อมูลจริงของวันนั้น) · Forecaster ตัวจริง")
    else:
        if args.date is None:
            raise SystemExit("--source history ต้องระบุ --date")
        d = args.date
        world = World(d, 1, "dedicated")
        base = [world.new_lot(r) for r in world.initial]
        if not base or not any(k[1] == d for k in world.demand):
            raise SystemExit(f"ไม่มี lot / ยอดลูกค้าของวันที่ {d} ใน mock_v3")
        scanner = ScanModel(until=d)                                       # ไม่เห็นยอดขายตั้งแต่วันนั้น
        src = f"history: lot บนชั้นเช้าวันนั้นจาก lot_daily.csv · ลูกค้า = latent_demand จริง · Forecaster เทรนถึง {d - timedelta(days=1)}"
    print(f"one-shot {d} ({args.source}) | {len(base)} lot | {sum(l.qty for l in base):,} ชิ้น")

    p1 = run_rule_day(world, base, d, "policy1")
    variants = {k: run_rule_day(world, base, d, f"policy2_{k}", rule) for k, rule in FIXED_RULES.items()}
    best2 = max(variants, key=lambda k: variants[k]["net_profit"])
    p3, pol = run_main_day(world, base, d, scanner, args.approve_rate)
    res = {"date": d.isoformat(), "source": args.source, "source_text": src, "lots": len(base),
           "units": sum(l.qty for l in base), "approve_rate": args.approve_rate,
           "policy1": p1, "policy2": variants[best2], "policy2_variant": best2, "policy2_variants": variants,
           "policy3": p3, "optimizer": optimizer_view(world, pol)}
    for name, p in [("1 ร้านแบบเดิม", p1), (f"2 กฎตายตัว ({best2})", variants[best2]), ("3 main", p3)]:
        print(f"  {name:<18} กำไรวันนี้ {p['net_profit']:>10,.2f} | ขาย {p['sold_units']:>4} | ทิ้ง {p['waste_units']:>3} | "
              f"สต็อกเหลือ {p['ending_units']:>4} | หมดอายุค้างร้าน {p['expired_left_units']}")
    ov = res["optimizer"]
    print(f"  task {len(ov['decisions'])} ({', '.join(f'{k} {v}' for k, v in Counter(x['action'] for x in ov['decisions']).items())})"
          f" | แผนชั่วคราว {len(ov['provisional'])} | ระดับความเสี่ยง {ov['levels']}")
    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"oneshot_{args.source}_{d.isoformat()}"
    (args.out / f"{stem}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (args.out / f"{stem}.html").write_text(render_html(res), encoding="utf-8")
    print(f"ไฟล์: {args.out / (stem + '.html')}")


if __name__ == "__main__":
    main()
