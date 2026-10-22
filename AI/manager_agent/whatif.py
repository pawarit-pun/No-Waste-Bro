"""What-if: แก้ข้อมูลเข้า Optimizer ตามสถานการณ์ที่ผู้จัดการถาม แล้วรันใหม่เทียบกับแผนจริง (ไม่บันทึกอะไร)

ทุกตัวเลขที่ตอบ (ส่วนต่างกำไร หน่วยต่อวิธี) คำนวณที่นี่ LLM แค่เล่าผล ห้ามคิดเลขเอง
สถานการณ์ที่รองรับ (รวมกันได้):
  force_discount       {"lot_id", "discount_pct"}  บังคับ lot นี้ขายได้แค่ส่วนลดนี้ (ต้องเป็นระดับที่ Forecaster พยากรณ์ไว้)
  no_markdown          ["LOT-..."] หรือ ["ALL"]       ห้ามลดราคา (เหลือแค่ราคาปัจจุบัน)
  partner_unavailable  ["P-..."]                      partner ไม่มารับ
  kitchen_hours        {"department_id", "hours"}     ชั่วโมงครัวที่ยังว่างวันนี้
  demand_scale         0.5 - 1.5                      ยอดขายทั้งร้านเปลี่ยน x เท่า (ทั้ง shelf และเมนูครัว)
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Any

from .labels import METHOD_TH

DEMAND_SCALE_RANGE = (0.5, 1.5)


class WhatIfError(ValueError):
    pass


def apply_overrides(inputs: dict, ov: dict) -> tuple[dict, list[str]]:
    """-> (inputs ใหม่, คำอธิบายสิ่งที่เปลี่ยนเป็นภาษาไทย)"""
    data = copy.deepcopy(inputs)
    lots = {a["lot_id"]: a for a in data.get("at_risk_lots") or []}
    applied: list[str] = []

    fd = ov.get("force_discount")
    if fd:
        lot_id, pct = str(fd.get("lot_id", "")).upper(), fd.get("discount_pct")
        if lot_id not in lots:
            raise WhatIfError(f"{lot_id} ไม่อยู่ในรอบสแกนนี้ (ไม่ใช่ lot HIGH / CRITICAL) จึงจำลองไม่ได้")
        levels = sorted({float(s["discount_pct"]) for s in lots[lot_id].get("shelf") or []})
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            raise WhatIfError("discount_pct ต้องเป็นตัวเลข") from None
        if pct not in levels or pct == 0:
            raise WhatIfError(f"{lot_id} ไม่มีผลพยากรณ์ยอดขายที่ส่วนลด {pct:g}% "
                              f"(ระดับที่มี: {', '.join(f'{x:g}%' for x in levels if x) or 'ไม่มี (ลดราคาไม่ได้)'})")
        lots[lot_id]["shelf"] = [s for s in lots[lot_id]["shelf"] if float(s["discount_pct"]) == pct]
        applied.append(f"{lot_id} ขายได้เฉพาะราคาลด {pct:g}%")

    nm = ov.get("no_markdown") or []
    if nm:
        targets = list(lots) if any(str(x).upper() == "ALL" for x in nm) else [str(x).upper() for x in nm]
        missing = [t for t in targets if t not in lots]
        if missing:
            raise WhatIfError(f"{', '.join(missing)} ไม่อยู่ในรอบสแกนนี้")
        for t in targets:
            lots[t]["shelf"] = [s for s in lots[t].get("shelf") or [] if float(s["discount_pct"]) == 0]
        applied.append("ไม่ลดราคา: " + ("ทุก lot" if len(targets) == len(lots) and len(lots) > 1 else ", ".join(targets)))

    pu = [str(x).upper() for x in ov.get("partner_unavailable") or []]
    if pu:
        known = {p["partner_id"] for p in data.get("donation_partners") or []}
        missing = [p for p in pu if p not in known]
        if missing:
            raise WhatIfError(f"ไม่พบ partner {', '.join(missing)} (มี: {', '.join(sorted(known))})")
        data["donation_partners"] = [p for p in data["donation_partners"] if p["partner_id"] not in pu]
        applied.append("partner ไม่มารับ: " + ", ".join(pu))

    kh = ov.get("kitchen_hours")
    if kh:
        dep, hrs = str(kh.get("department_id", "")).upper(), kh.get("hours")
        try:
            hrs = float(hrs)
        except (TypeError, ValueError):
            raise WhatIfError("hours ต้องเป็นตัวเลข") from None
        if not 0 <= hrs <= 24:
            raise WhatIfError("hours ต้องอยู่ระหว่าง 0 ถึง 24")
        today = str(data.get("reference_date"))[:10]
        rows = [k for k in data.get("kitchen_capacity") or []
                if k["department_id"] == dep and str(k["capacity_date"])[:10] == today]
        if not rows:
            deps = sorted({k["department_id"] for k in data.get("kitchen_capacity") or []})
            raise WhatIfError(f"ไม่พบครัว {dep} ของวันนี้ (มี: {', '.join(deps)})")
        for k in rows:
            k["booked_hrs"] = max(0.0, float(k["available_hrs"]) - hrs)
            k["remaining_hrs"] = hrs
        applied.append(f"ครัว {dep} ว่าง {hrs:g} ชั่วโมงวันนี้")

    ds = ov.get("demand_scale")
    if ds not in (None, 1, 1.0):
        try:
            ds = float(ds)
        except (TypeError, ValueError):
            raise WhatIfError("demand_scale ต้องเป็นตัวเลข") from None
        lo, hi = DEMAND_SCALE_RANGE
        if not lo <= ds <= hi:
            raise WhatIfError(f"demand_scale ต้องอยู่ระหว่าง {lo} ถึง {hi}")
        for a in lots.values():
            for s in a.get("shelf") or []:
                for k in ("expected_qty", "low_qty", "high_qty", "lost_sales_other_lots"):
                    if s.get(k) is not None:
                        s[k] = round(float(s[k]) * ds, 3)
        for r in data.get("recipe_demand") or []:
            for k in ("gross_demand", "menu_qty", "low_qty", "high_qty", "expected_revenue"):
                if r.get(k) is not None:
                    r[k] = round(float(r[k]) * ds, 3)
        applied.append(f"ยอดขายทั้งร้าน x{ds:g} (สมมติฐาน ไม่ได้มาจาก Forecaster)")

    if not applied:
        raise WhatIfError("ไม่ได้ระบุสถานการณ์ที่จะจำลอง")
    return data, applied


def _portions(lot: dict) -> dict[str, int]:
    out: Counter = Counter()
    for p in lot["portions"]:
        name = METHOD_TH.get(p["method"], p["method"])
        if p["method"] == "MARKDOWN":
            name += f" {p['details'].get('discount_pct', 0):g}%"
        if p["details"].get("provisional"):
            name += " (แผนชั่วคราว)"
        out[name] += p["units"]
    return dict(out)


def _fmt(d: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items())) or "-"


def _method_th(key: str) -> str:
    """"MARKDOWN 20%" -> "ลดราคา 20%" """
    head, _, tail = key.partition(" ")
    return (METHOD_TH.get(head, head) + (" " + tail if tail else "")).strip()


MAX_CHANGED_LOTS = 8


def compare(base: dict, alt: dict) -> dict:
    """ผล run_optimizer 2 ชุด -> ส่วนต่างที่ LLM เล่าได้ตรงๆ"""
    bs, as_ = base["plan"]["summary"], alt["plan"]["summary"]
    blots = {l["lot_id"]: l for l in base["plan"]["lots"]}
    alots = {l["lot_id"]: l for l in alt["plan"]["lots"]}
    changed = []
    for lot_id in sorted(set(blots) | set(alots)):
        b, a = blots.get(lot_id), alots.get(lot_id)
        bp, ap = (_portions(b) if b else {}), (_portions(a) if a else {})
        if bp == ap:
            continue
        bn, an = (b or {}).get("net_profit_thb", 0.0), (a or {}).get("net_profit_thb", 0.0)
        changed.append({"lot_id": lot_id, "name": (a or b)["name"], "before": _fmt(bp), "after": _fmt(ap),
                        "net_profit_before_thb": round(bn, 2), "net_profit_after_thb": round(an, 2),
                        "net_profit_change_thb": round(an - bn, 2)})
    methods = sorted(set(bs.get("units_by_method") or {}) | set(as_.get("units_by_method") or {}))
    units = [{"method": _method_th(m), "before": (bs.get("units_by_method") or {}).get(m, 0),
              "after": (as_.get("units_by_method") or {}).get(m, 0)} for m in methods]
    for u in units:
        u["change"] = u["after"] - u["before"]
    bnet, anet = bs.get("net_profit_thb", 0.0), as_.get("net_profit_thb", 0.0)
    return {
        "net_profit_before_thb": round(bnet, 2), "net_profit_after_thb": round(anet, 2),
        "net_profit_change_thb": round(anet - bnet, 2),
        "unresolved_units_before": bs.get("unresolved_units", 0), "unresolved_units_after": as_.get("unresolved_units", 0),
        "units_by_method": [u for u in units if u["change"]],
        "changed_lots_total": len(changed),
        "changed_lots": sorted(changed, key=lambda c: c["net_profit_change_thb"])[:MAX_CHANGED_LOTS],
        "new_warnings": [w for w in alt["plan"]["warnings"] if w not in base["plan"]["warnings"]][:5],
        "violations_after": len(alt["violations"]) + len(alt["payload_errors"]),
    }


def overrides_key(ov: dict) -> str:
    return "whatif:" + json.dumps(ov, sort_keys=True, ensure_ascii=False, default=str)


def run_what_if(ds: Any, overrides: dict) -> dict:
    base = ds.plan("base")
    inputs, applied = apply_overrides(ds.optimize_inputs(), overrides)
    alt = ds.plan(overrides_key(overrides), inputs)
    return {"scenario": applied, **compare(base, alt)}
