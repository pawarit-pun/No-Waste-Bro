"""Tool ของ Manager Agent (อ่านอย่างเดียว ไม่มี tool ไหนเขียนข้อมูล)

tool แต่ละตัว: name, คำอธิบายภาษาไทยให้โมเดล, พารามิเตอร์, ฟังก์ชัน (ds, args) -> (result, artifact | None)
  result   = JSON ที่ส่งกลับให้โมเดล (เล็กพอดี ตัวเลขคำนวณเสร็จแล้ว)
  artifact = การ์ดที่หน้าเว็บแสดงคู่กับคำตอบ (ไม่ส่งให้โมเดล)
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from .whatif import WhatIfError, run_what_if

from .labels import ACTION_TH, METHOD_TH
from .proposals import KINDS as PROPOSAL_KINDS
from .proposals import propose_action

# รหัสเหตุผลที่ Optimizer ตัดทางเลือกออก (ai_engine/optimizer/rules.py) -> ภาษาไทย ดูจาก prefix ยาวสุดที่ตรง
REASON_TH = {
    "K0_EXPIRED": "หมดอายุแล้ว ลดราคาขายไม่ได้",
    "K1_MARKDOWN_NOT_ALLOWED": "สินค้านี้ห้ามลดราคา",
    "K2_BELOW_MIN_PRICE": "ราคาหลังลดต่ำกว่าราคาต่ำสุดที่อนุญาต",
    "K3_LEVEL_NOT_IN_POLICY": "ส่วนลดระดับนี้ไม่อยู่ในนโยบายร้าน",
    "K3_NOT_FORECAST": "ไม่มีผลพยากรณ์ยอดขายที่ส่วนลดระดับนี้",
    "K4_PRICE_CHANGED": "ราคาขายเปลี่ยนหลังสแกน",
    "K5_NO_SALES_EXPECTED": "คาดว่าขายไม่ได้เลย",
    "K6_NO_EXTRA_SALES": "ลดลึกขึ้นแล้วคาดว่าขายได้ไม่เพิ่ม",
    "P1_FLAG_": "สินค้านี้ไม่อนุญาตวิธีนี้",
    "P2_CATEGORY_": "partner ไม่รับสินค้าหมวดนี้",
    "P3_NO_PICKUP_SLOT": "ไม่มีรอบรับของที่ทันเวลา",
    "P3_PARTNER_INACTIVE": "partner ไม่ active",
    "P4_MIN_DAYS": "อายุที่เหลือตอนรับของน้อยกว่าที่ partner กำหนด",
    "P5_EXPIRED_FOR_HUMAN_USE": "หมดอายุแล้ว ห้ามให้คนบริโภค",
    "P6_NO_CAPACITY": "partner รับน้ำหนักเพิ่มไม่ได้",
    "P7_BELOW_MIN_KG": "น้ำหนักไม่ถึงขั้นต่ำต่อรอบของ partner",
    "P8_NO_WEIGHT": "ไม่มีข้อมูลน้ำหนักสินค้า",
    "U0_RECIPE_INACTIVE": "สูตรไม่ได้เปิดใช้",
    "U1_": "ข้อมูลครัวหรือเวลาทำของสูตรไม่ครบ",
    "U2_KITCHEN_NOT_ALLOWED": "สินค้านี้ห้ามส่งเข้าครัว",
    "U2_NOT_AN_INGREDIENT": "ไม่ใช่วัตถุดิบของสูตรใด",
    "U2_NO_AT_RISK_PRIMARY_INGREDIENT": "ไม่มีวัตถุดิบหลักที่เสี่ยง",
    "U3_KITCHEN_HOURS": "ชั่วโมงครัวไม่พอ",
    "U4_EXPIRES_BEFORE_DUE": "หมดอายุก่อนครัวทำเสร็จ",
    "U4_NO_FEASIBLE_JOB": "ไม่มีช่วงเวลาครัวที่ทำได้",
    "U5_NO_MENU_DEMAND": "คาดว่าไม่มีคนซื้อเมนูนี้",
    "U6_UNIT_MISMATCH_": "หน่วยของสูตรกับสินค้าไม่ตรงกัน",
    "U7_OUTPUT_PRODUCT_UNKNOWN": "ไม่พบสินค้าที่สูตรผลิต",
    "U8_INGREDIENT_SHORT": "วัตถุดิบอื่นของสูตรไม่พอ",
    "U8_LOT_TOO_SMALL_FOR_": "lot เล็กเกินกว่า 1 batch",
}
OPEN, DONE = ("PENDING", "IN_PROGRESS"), ("COMPLETED", "REJECTED")


def reason_th(code: str) -> str:
    head = code.split(" ")[0]
    best = max((k for k in REASON_TH if head.startswith(k)), key=len, default=None)
    return REASON_TH[best] if best else head


def _parse_dt(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------- registry
@dataclass
class Param:
    type: str                      # string / integer / number / boolean / array / object
    description: str
    required: bool = False
    enum: Optional[list] = None
    items: Optional[dict] = None
    properties: Optional[dict] = None


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[[Any, dict], tuple[dict, Optional[dict]]]
    params: dict[str, Param] = field(default_factory=dict)

    def spec(self) -> dict:
        props = {}
        for k, p in self.params.items():
            s: dict = {"type": p.type, "description": p.description}
            if p.enum:
                s["enum"] = p.enum
            if p.items:
                s["items"] = p.items
            if p.properties:
                s["properties"] = p.properties
            props[k] = s
        schema = {"type": "object", "properties": props,
                  "required": [k for k, p in self.params.items() if p.required]}
        return {"toolSpec": {"name": self.name, "description": self.description, "inputSchema": {"json": schema}}}

    def coerce(self, args: Any) -> dict:
        """ตรวจ/แปลงอาร์กิวเมนต์จากโมเดล (โมเดลเล็กส่งเลขเป็น string บ่อย) ผิด -> ValueError ส่งกลับให้โมเดลแก้"""
        args = dict(args or {})
        out = {}
        for k, p in self.params.items():
            if k not in args or args[k] in (None, ""):
                if p.required:
                    raise ValueError(f"ต้องระบุ {k}")
                continue
            v = args[k]
            try:
                if p.type == "integer":
                    v = int(float(v))
                elif p.type == "number":
                    v = float(v)
                elif p.type == "boolean":
                    v = v if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes")
                elif p.type == "string":
                    v = str(v).strip()
                elif p.type == "array" and not isinstance(v, list):
                    v = [v]
                elif p.type == "object" and not isinstance(v, dict):
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError(f"{k} ต้องเป็น {p.type}") from None
            if p.enum and v not in p.enum:
                raise ValueError(f"{k} ต้องเป็นหนึ่งใน {p.enum}")
            out[k] = v
        unknown = set(args) - set(self.params)
        if unknown:
            raise ValueError(f"ไม่รู้จักพารามิเตอร์ {sorted(unknown)}")
        return out


# ---------------------------------------------------------------- helpers
def _lot_brief(it: dict) -> dict:
    a = it.get("latest_assessment") or {}
    p = it.get("product") or {}
    return {"lot_id": it["lot_id"], "name": p.get("name"), "category": p.get("category"),
            "quantity": it.get("current_quantity"), "unit": p.get("unit_of_measure"),
            "price": it.get("current_selling_price"), "regular_price": p.get("regular_price"),
            "expiration_date": it.get("expiration_date"), "days_left": it.get("days_left"),
            "location": " / ".join(x for x in (it.get("location_aisle"), it.get("location_shelf")) if x) or None,
            "risk_level": a.get("risk_level"), "risk_score": a.get("risk_score"),
            "ai_status": it.get("ai_status"), "origin": it.get("origin"),
            "waiting_plans": it.get("waiting_plans", 0), "open_tasks": it.get("open_tasks", 0)}


def _task_brief(t: dict, now: datetime) -> dict:
    due = _parse_dt(t.get("due_by"))
    return {"task_id": str(t["task_id"]), "lot_id": t.get("lot_id"), "name": (t.get("product") or {}).get("name"),
            "action": ACTION_TH.get(t["action_type"], t["action_type"]), "action_type": t["action_type"],
            "quantity": t.get("action_quantity"), "status": t["task_status"], "priority": t.get("priority"),
            "staff": (t.get("assigned_staff") or {}).get("full_name") or "ยังไม่มีผู้รับผิดชอบ",
            "due_by": t.get("due_by"), "discount_pct": t.get("discount_pct"),
            "overdue": bool(due and t["task_status"] in OPEN and due < now)}


def _find_lot(ds, lot_id: str) -> Optional[dict]:
    lot_id = lot_id.upper()
    return next((it for it in ds.inventory().get("items") or [] if it["lot_id"] == lot_id), None)


def _portion_text(p: dict, recipes: Optional[dict] = None) -> dict:
    d = p["details"]
    out = {"method": METHOD_TH.get(p["method"], p["method"]), "units": p["units"],
           "net_profit_thb": round(p.get("net_profit_thb", 0.0), 2)}
    if p["method"] == "MARKDOWN":
        out.update(discount_pct=d.get("discount_pct"), unit_price=d.get("unit_price"),
                   expected_sold=round(d.get("expected_sold", 0), 1))
    if d.get("partner_name"):
        out.update(partner=d["partner_name"], pickup_at=d.get("pickup_at"))
    if d.get("timing") == "END_OF_LIFE":
        out["when"] = "ส่วนที่คาดว่าขายไม่หมด กำจัดหลังหมดเวลาขาย"
    if d.get("provisional"):
        out["provisional"] = "แผนชั่วคราว: ยังไม่สร้าง task จนถึงวันที่ลงมือ ระบบจะคิดใหม่ในวันนั้น"
    if p["method"] in ("KITCHEN", "KITCHEN_INGREDIENT") and d.get("recipe_id"):
        out.update(recipe=(recipes or {}).get(d["recipe_id"], d["recipe_id"]), batches=d.get("batches"),
                   kitchen_due_by=d.get("due_by"))
    return out


# ---------------------------------------------------------------- tools
PIPELINE_RUN_FIELDS = ("status", "current_step", "stop_after", "at_risk_lots", "decisions_created", "tasks_created",
                       "message", "error", "requested_at", "started_at", "finished_at")   # server/schemas/pipeline.py


def get_store_snapshot(ds, args):
    now = ds.now()
    items = [it for it in ds.inventory().get("items") or [] if (it.get("current_quantity") or 0) > 0]
    risk = Counter((it.get("latest_assessment") or {}).get("risk_level") or "ยังไม่สแกน" for it in items)
    tasks = ds.tasks(OPEN)
    briefs = [_task_brief(t, now) for t in tasks]
    reviews = ds.reviews() or {}
    runs = ds.pipeline_runs(1) or []
    last = runs[0] if isinstance(runs, list) and runs else None
    result = {
        "today": ds.reference_date().isoformat(), "now": now.strftime("%H:%M"),
        "lots_in_stock": len(items), "units_in_stock": sum(it["current_quantity"] for it in items),
        "lots_by_risk_level": dict(risk),
        "expired_lots": sum(1 for it in items if (it.get("days_left") or 0) < 0),
        "expiring_today_lots": sum(1 for it in items if it.get("days_left") == 0),
        "expiring_tomorrow_lots": sum(1 for it in items if it.get("days_left") == 1),
        "plans_waiting_approval": (reviews.get("counts") or {}).get("waiting", len(reviews.get("items") or [])),
        "open_tasks": len(tasks),
        "open_tasks_by_status": dict(Counter(b["status"] for b in briefs)),
        "open_tasks_by_action": dict(Counter(b["action"] for b in briefs)),
        "overdue_tasks": sum(1 for b in briefs if b["overdue"]),
        "last_pipeline_run": {k: last.get(k) for k in PIPELINE_RUN_FIELDS if last.get(k) is not None} if last else None,
    }
    return result, {"type": "snapshot", **{k: result[k] for k in ("lots_in_stock", "lots_by_risk_level",
                                                                  "plans_waiting_approval", "open_tasks",
                                                                  "overdue_tasks")}}


RISK_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def list_at_risk_lots(ds, args):
    levels = args.get("risk_levels") or ["CRITICAL", "HIGH"]
    levels = [str(x).upper() for x in levels]
    rows = []
    for it in ds.inventory().get("items") or []:
        a = it.get("latest_assessment") or {}
        if (it.get("current_quantity") or 0) <= 0 or a.get("risk_level") not in levels:
            continue
        if args.get("max_days_left") is not None and (it.get("days_left") or 0) > args["max_days_left"]:
            continue
        if args.get("category") and (it.get("product") or {}).get("category") != args["category"].upper():
            continue
        rows.append(_lot_brief(it))
    rows.sort(key=lambda r: (RISK_ORDER.get(r["risk_level"], 9), -(r["risk_score"] or 0), r["days_left"] or 0))
    limit = args.get("limit") or 10
    result = {"total": len(rows), "shown": min(limit, len(rows)), "risk_levels": levels, "lots": rows[:limit]}
    return result, {"type": "lot_list", "lots": rows[:limit]}


def get_lot(ds, args):
    it = _find_lot(ds, args["lot_id"])
    if not it:
        raise ValueError(f"ไม่พบ {args['lot_id']} (หรือ lot นี้ไม่มีของเหลือแล้ว)")
    now = ds.now()
    tasks = [_task_brief(t, now) for t in ds.tasks(OPEN + DONE) if t.get("lot_id") == it["lot_id"]]
    reviews = [{"review_id": str(r["review_id"]), "action": ACTION_TH.get((r.get("decision") or {}).get("action_type"), ""),
                "quantity": (r.get("decision") or {}).get("action_quantity"), "priority": r.get("priority")}
               for r in (ds.reviews() or {}).get("items") or [] if r.get("lot_id") == it["lot_id"]]
    result = {**_lot_brief(it), "received_date": it.get("received_date"), "unit_cost": it.get("unit_cost"),
              "tasks": tasks[:10], "plans_waiting_approval": reviews[:10]}
    return result, {"type": "lot", "lot_id": it["lot_id"]}


def list_tasks(ds, args):
    status = args.get("status", "open")
    statuses = {"open": OPEN, "completed": ("COMPLETED",), "rejected": ("REJECTED",), "all": OPEN + DONE}[status]
    now = ds.now()
    rows = [_task_brief(t, now) for t in ds.tasks(statuses)]
    if args.get("action_type"):
        rows = [r for r in rows if r["action_type"] == args["action_type"].upper()]
    if args.get("lot_id"):
        rows = [r for r in rows if r["lot_id"] == args["lot_id"].upper()]
    if args.get("overdue_only"):
        rows = [r for r in rows if r["overdue"]]
    limit = args.get("limit") or 15
    result = {"now": now.isoformat(timespec="minutes"), "total": len(rows), "shown": min(limit, len(rows)),
              "overdue": sum(1 for r in rows if r["overdue"]), "tasks": rows[:limit]}
    return result, {"type": "task_list", "tasks": rows[:limit]}


def get_plan(ds, args):
    r = ds.plan("base")
    plan, s = r["plan"], r["plan"]["summary"]
    today = Counter()
    for d in r["payload"]["decisions"]:
        today[ACTION_TH.get(d["action_type"], d["action_type"])] += d["action_quantity"]
    provisional = Counter()
    for lot in plan["lots"]:
        for p in lot["portions"]:
            if p["details"].get("provisional"):
                provisional[METHOD_TH.get(p["method"], p["method"])] += p["units"]
    base = plan.get("baselines") or {}
    result = {
        "scan_run_id": plan.get("run_id"), "scan_date": plan.get("reference_date"),
        "computed_at": plan.get("simulated_now"), "lots": s.get("lots", 0), "units": s.get("units", 0),
        "units_by_method": {METHOD_TH.get(k.split(" ")[0], k) + (" " + k.split(" ")[1] if " " in k else ""): v
                            for k, v in (s.get("units_by_method") or {}).items()},
        "task_units_today_by_action": dict(today),
        "provisional_units_by_method": dict(provisional),
        "net_profit_thb": s.get("net_profit_thb"),
        "net_profit_if_regular_price_then_landfill_thb": (base.get("regular_price_then_landfill") or {}).get("net_profit_thb"),
        "improvement_vs_regular_then_landfill_thb": base.get("improvement_vs_regular_then_landfill_thb"),
        "unresolved_units": s.get("unresolved_units", 0),
        "warnings": plan.get("warnings", [])[:5],
        "note": "คำนวณใหม่ตอนนี้แบบ dry-run (ไม่บันทึก) รวม lot ที่สร้าง task ไปแล้ว ตัวเลขอาจต่างจาก decision ที่บันทึกตอนรัน pipeline",
    }
    return result, None


def explain_decision(ds, args):
    lot_id = args["lot_id"].upper()
    r = ds.plan("base")
    lot = next((l for l in r["plan"]["lots"] if l["lot_id"] == lot_id), None)
    if not lot:
        reason = (r["plan"].get("skipped_lots") or {}).get(lot_id)
        raise ValueError(f"{lot_id} ไม่อยู่ในแผนรอบนี้ (ไม่ใช่ lot HIGH / CRITICAL ของรอบสแกนล่าสุด)"
                         + (f" เหตุผล: {reason}" if reason else ""))
    excluded = [{"option": opt, "reasons": sorted({reason_th(c) for c in codes}), "detail": codes}
                for opt, codes in (lot.get("explain") or {}).get("excluded", {}).items()]
    # ทางเลือกที่ทำได้แต่ไม่ได้เลือก (จาก payload ของ decision แรกของ lot นี้ = ที่ Optimizer เทียบให้แล้ว)
    alts = []
    for d in r["payload"]["decisions"]:
        if d["assessment_id"] == lot["assessment_id"]:
            for a in d.get("alternatives") or []:
                if "expected_profit_impact" in a and a.get("feasible", True):
                    alts.append({"action": ACTION_TH.get(a.get("action_type"), a.get("action_type")),
                                 "discount_pct": a.get("discount_pct"),
                                 "expected_profit_impact_thb": a["expected_profit_impact"], "note": a.get("note")})
            break
    price_options = [{"discount_pct": o["discount_pct"], "price": o["price"], "expected_sold": o["expected_sold"],
                      "lot_net_profit_thb": o["lot_net_profit_thb"], "chosen": o["chosen"]}
                     for o in (lot.get("explain") or {}).get("price_options") or []]
    saved = []
    try:
        for d in (ds.decisions(lot.get("run_id") or r["plan"].get("run_id")) or {}).get("decisions") or []:
            if d.get("lot_id") == lot_id:
                saved.append({"action": ACTION_TH.get(d["action_type"], d["action_type"]),
                              "quantity": d["action_quantity"], "discount_pct": d.get("discount_pct"),
                              "status": d.get("status"), "expected_profit_impact_thb": d.get("expected_profit_impact")})
    except Exception:  # noqa: BLE001  decision ที่บันทึกไว้เป็นข้อมูลเสริม อ่านไม่ได้ก็อธิบายต่อได้
        pass
    result = {
        "lot_id": lot_id, "name": lot["name"], "quantity": lot["quantity"], "risk_level": lot["risk_level"],
        "days_to_expiry": lot["days_to_expiry"], "current_price": lot["current_price"], "unit_cost": lot["unit_cost"],
        "plan": [_portion_text(p, {x["recipe_id"]: x["name"] for x in ds.optimize_inputs().get("recipes") or []})
                 for p in lot["portions"]],
        "lot_net_profit_thb": round(lot.get("net_profit_thb", 0.0), 2),
        "price_options": price_options, "other_feasible_options": alts[:6], "excluded_options": excluded[:10],
        "saved_decisions": saved,
        "note": "แผนคำนวณใหม่ตอนนี้ (dry-run) ถ้าต่างจาก saved_decisions ให้บอกผู้จัดการว่าเวลาหรือข้อมูลเปลี่ยนไปหลังรัน pipeline",
    }
    return result, {"type": "lot_explain", **{k: result[k] for k in ("lot_id", "name", "quantity", "risk_level", "plan",
                                                                     "lot_net_profit_thb", "price_options",
                                                                     "other_feasible_options", "excluded_options",
                                                                     "saved_decisions")}}


def what_if(ds, args):
    ov = {k: args[k] for k in ("force_discount", "no_markdown", "partner_unavailable", "kitchen_hours",
                               "demand_scale") if k in args}
    try:
        result = run_what_if(ds, ov)
    except WhatIfError as e:
        raise ValueError(str(e)) from None
    result["note"] = "จำลองอย่างเดียว ไม่ได้เปลี่ยนแผนหรือ task จริง"
    return result, {"type": "what_if", **result}


def search_sop(ds, args, retriever=None):
    retriever = retriever or getattr(ds, "sop_retriever", None)
    if retriever is None:
        raise ValueError("ค้นเอกสาร SOP ไม่ได้ตอนนี้ (Knowledge Base ไม่พร้อม)")
    chunks = retriever(args["query"], args.get("action_type"))
    result = {"results": [{"doc_id": c["doc_id"], "text": c["text"][:700]} for c in chunks]}
    return result, {"type": "sources", "docs": sorted({c["doc_id"] for c in chunks})}


def get_daily_report(ds, args):
    kind = (args.get("kind") or "").upper() or None
    date = args.get("date") or ds.reference_date().isoformat()
    rows = [r for r in ds.daily_reports(8) if str(r.get("report_date")) == date and (kind is None or r.get("kind") == kind)]
    if not rows:
        have = sorted({f"{r.get('report_date')} {r.get('kind')}" for r in ds.daily_reports(8)})
        raise ValueError(f"ไม่มีรายงาน{' ' + kind if kind else ''}ของวันที่ {date}"
                         + (f" (มี: {', '.join(have)})" if have else " (ยังไม่เคยทำรายงาน)"))
    result = {"reports": [{"report_date": r["report_date"], "kind": r["kind"], "message": r.get("message"),
                           "metrics": r.get("metrics"), "anomalies": r.get("anomalies"),
                           "updated_at": r.get("updated_at")} for r in rows],
              "note": "กำไรเป็นค่าที่ Optimizer คาด ยังไม่ใช่ยอดขายจริง"}
    return result, None


ACTION_ENUM = ["MARKDOWN", "KITCHEN_REPURPOSE", "DONATE", "DISCARD", "ANIMAL_FEED", "COMPOST",
               "ANAEROBIC_DIGESTION", "LANDFILL"]

TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("get_store_snapshot", "ภาพรวมร้านตอนนี้: จำนวน lot แยกตามระดับความเสี่ยง lot ที่หมดอายุวันนี้/พรุ่งนี้ "
         "plan ที่รออนุมัติ task ที่ค้าง/เลยกำหนด และสถานะ pipeline รอบล่าสุด", get_store_snapshot),
    Tool("list_at_risk_lots", "รายการ lot ที่เสี่ยง (ผลสแกนล่าสุด) เรียงจากเสี่ยงมากไปน้อย พร้อมจำนวนทั้งหมด", list_at_risk_lots, {
        "risk_levels": Param("array", "ระดับความเสี่ยง ค่าเริ่มต้น CRITICAL กับ HIGH",
                             items={"type": "string", "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]}),
        "max_days_left": Param("integer", "เฉพาะ lot ที่เหลืออายุไม่เกินกี่วัน (0 = หมดอายุวันนี้)"),
        "category": Param("string", "หมวดสินค้า", enum=["DAIRY", "BAKERY", "MEAT", "SEAFOOD", "PRODUCE", "READY_TO_EAT"]),
        "limit": Param("integer", "จำนวนสูงสุดที่แสดง ค่าเริ่มต้น 10"),
    }),
    Tool("get_lot", "ข้อมูล lot เดียว: สินค้า จำนวน ราคา วันหมดอายุ ตำแหน่ง ความเสี่ยง task และ plan ที่รออนุมัติของ lot นี้", get_lot, {
        "lot_id": Param("string", "รหัส lot เช่น LOT-000020", required=True),
    }),
    Tool("list_tasks", "รายการ task ของพนักงาน พร้อมผู้รับผิดชอบ กำหนดเสร็จ และว่าเลยกำหนดหรือยัง", list_tasks, {
        "status": Param("string", "open = ยังไม่เสร็จ (ค่าเริ่มต้น), completed, rejected, all",
                        enum=["open", "completed", "rejected", "all"]),
        "action_type": Param("string", "ประเภทงาน", enum=ACTION_ENUM),
        "lot_id": Param("string", "เฉพาะ lot นี้"),
        "overdue_only": Param("boolean", "true = เฉพาะงานที่เลยกำหนดแล้ว"),
        "limit": Param("integer", "จำนวนสูงสุดที่แสดง ค่าเริ่มต้น 15"),
    }),
    Tool("get_plan", "สรุปแผนของ Optimizer ทั้งรอบ: หน่วยต่อวิธีจัดการ กำไรสุทธิ เทียบกับขายปกติแล้วฝังกลบ "
         "งานที่ต้องทำวันนี้ และแผนชั่วคราวของวันถัดไป", get_plan),
    Tool("explain_decision", "อธิบายว่าทำไม Optimizer เลือกวิธีนี้กับ lot หนึ่ง: แผนแบ่งส่วน ราคาแต่ละระดับส่วนลด "
         "ทางเลือกอื่นที่ทำได้ และทางเลือกที่ถูกตัดออกพร้อมเหตุผล", explain_decision, {
        "lot_id": Param("string", "รหัส lot เช่น LOT-000020", required=True),
    }),
    Tool("what_if", "จำลองสถานการณ์แล้วเทียบกับแผนจริง (ไม่เปลี่ยนข้อมูลจริง) ระบุอย่างน้อย 1 อย่าง "
         "ใช้ตัวเลขที่ tool คืนมาเท่านั้น", what_if, {
        "force_discount": Param("object", "บังคับ lot หนึ่งขายราคาลดระดับนี้",
                                properties={"lot_id": {"type": "string"}, "discount_pct": {"type": "number"}}),
        "no_markdown": Param("array", "lot ที่ห้ามลดราคา หรือ [\"ALL\"] = ทุก lot", items={"type": "string"}),
        "partner_unavailable": Param("array", "partner_id ที่ไม่มารับของ เช่น P-ANI-01", items={"type": "string"}),
        "kitchen_hours": Param("object", "ชั่วโมงครัวที่ว่างวันนี้",
                               properties={"department_id": {"type": "string"}, "hours": {"type": "number"}}),
        "demand_scale": Param("number", "ยอดขายทั้งร้านเปลี่ยนกี่เท่า 0.5 ถึง 1.5"),
    }),
    Tool("propose_action", "เสนองานให้ผู้จัดการกดยืนยันบนการ์ด (คุณทำเองไม่ได้): RUN_PIPELINE = รัน pipeline วางแผนให้ lot IDLE, "
         "RELEASE_LOTS = คืน lot ที่ค้างเป็น IDLE, BLOCK_KITCHEN = ปิดครัวที่ใช้ไม่ได้วันนี้ (then_run_pipeline = วางแผนใหม่ต่อ) "
         "ใช้เมื่อผู้จัดการขอให้ทำสิ่งเหล่านี้ หรือข้อมูลชี้ว่าควรทำ", propose_action, {
        "kind": Param("string", "ประเภทข้อเสนอ", required=True, enum=list(PROPOSAL_KINDS)),
        "params": Param("object", "RUN_PIPELINE: {stop_after: SCAN|OPTIMIZE|TASKS}, RELEASE_LOTS: {lot_ids: [...]}, "
                                  "BLOCK_KITCHEN: {department_id, hours?, then_run_pipeline?}",
                        properties={"stop_after": {"type": "string"}, "lot_ids": {"type": "array", "items": {"type": "string"}},
                                    "department_id": {"type": "string"}, "hours": {"type": "number"},
                                    "then_run_pipeline": {"type": "boolean"}}),
        "reason": Param("string", "เหตุผลสั้นๆ ภาษาไทยว่าทำไมเสนอ (แสดงบนการ์ด)"),
    }),
    Tool("get_daily_report", "รายงานประจำวัน: MORNING = สรุปแผนของวัน (lot เสี่ยง, แผนต่อวิธี, kg, ความผิดปกติ), "
         "EVENING = สรุปปิดวัน (งานที่ทำจริง, kg ที่ขายต่อ/ฝังกลบ, งานค้าง) ใช้ตอบคำถามแบบ 'เมื่อเช้า' 'วันนี้ทำไปเท่าไร'",
         get_daily_report, {
        "date": Param("string", "วันที่ YYYY-MM-DD ไม่ระบุ = วันนี้ของระบบ"),
        "kind": Param("string", "ประเภทรายงาน ไม่ระบุ = ทั้งสอง", enum=["MORNING", "EVENING"]),
    }),
    Tool("search_sop", "ค้นเอกสาร SOP / นโยบายร้าน (ขั้นตอนลดราคา ครัว บริจาค ทิ้ง ความปลอดภัยอาหาร)", search_sop, {
        "query": Param("string", "สิ่งที่ต้องการค้น เป็นภาษาไทย", required=True),
        "action_type": Param("string", "จำกัดเฉพาะเอกสารของงานประเภทนี้",
                             enum=["MARKDOWN", "KITCHEN_REPURPOSE", "DONATE", "DISCARD"]),
    }),
]}


def tool_config() -> dict:
    return {"tools": [t.spec() for t in TOOLS.values()]}
