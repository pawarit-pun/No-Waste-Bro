"""ข้อเสนอที่ผู้จัดการกดยืนยันได้ (Phase 2)

agent สร้างข้อเสนอได้อย่างเดียว ไม่ได้ทำเอง: server ทำตามเมื่อผู้จัดการกด "ยืนยัน" (POST /agent/proposals/{id}/execute)
และตรวจกับข้อมูลล่าสุดอีกครั้งก่อนทำ ที่นี่ตรวจล่วงหน้าเพื่อไม่เสนอสิ่งที่ทำไม่ได้อยู่แล้ว

  RUN_PIPELINE   {"stop_after": "TASKS"}                                   เริ่ม pipeline รอบใหม่ (สแกน lot IDLE)
  RELEASE_LOTS   {"lot_ids": [...]}                                        คืน lot ที่ค้างเป็น IDLE
  BLOCK_KITCHEN  {"department_id", "date", "hours", "then_run_pipeline"}   จองชั่วโมงที่เหลือของครัวทั้งหมด (ครัวใช้ไม่ได้)
                                                                           แล้วเริ่ม pipeline ต่อ (ถ้า then_run_pipeline)
"""
from __future__ import annotations

from typing import Any, Optional

KINDS = ("RUN_PIPELINE", "RELEASE_LOTS", "BLOCK_KITCHEN")
STEPS = ("SCAN", "OPTIMIZE", "TASKS")
ACTIVE_PIPELINE = ("QUEUED", "RUNNING")
STEP_TH = {"SCAN": "สแกนความเสี่ยง", "OPTIMIZE": "สแกน + วางแผน", "TASKS": "สแกน + วางแผน + เขียนคำสั่งงานเข้าคิวอนุมัติ"}


class ProposalError(ValueError):
    pass


def _active_pipeline(ds) -> Optional[dict]:
    runs = ds.pipeline_runs(1) or []
    last = runs[0] if isinstance(runs, list) and runs else None
    return last if last and last.get("status") in ACTIVE_PIPELINE else None


def kitchen_today(ds, department_id: str) -> Optional[dict]:
    today = ds.reference_date().isoformat()
    return next((k for k in ds.kitchen() or []
                 if k["department_id"] == department_id and str(k["capacity_date"])[:10] == today), None)


def build(ds, kind: str, params: Optional[dict] = None, reason: str = "") -> dict:
    """ตรวจ + เติมค่า -> {"kind", "params", "title", "reason"} (ยังไม่บันทึก) ทำไม่ได้ -> ProposalError"""
    kind = str(kind or "").upper()
    params = dict(params or {})
    if kind not in KINDS:
        raise ProposalError(f"kind ต้องเป็นหนึ่งใน {list(KINDS)}")

    if kind == "RUN_PIPELINE":
        step = str(params.get("stop_after") or "TASKS").upper()
        if step not in STEPS:
            raise ProposalError(f"stop_after ต้องเป็นหนึ่งใน {list(STEPS)}")
        active = _active_pipeline(ds)
        if active:
            raise ProposalError(f"pipeline รอบก่อนยัง {active['status']} อยู่ ต้องรอให้จบก่อน")
        idle = [it for it in ds.inventory().get("items") or []
                if it.get("ai_status") == "IDLE" and (it.get("current_quantity") or 0) > 0]
        if not idle:
            raise ProposalError("ไม่มี lot IDLE ให้สแกน (ทุก lot ถูกวางแผนหรือมีงานอยู่แล้ว)")
        return {"kind": kind, "params": {"stop_after": step},
                "title": f"รัน pipeline ({STEP_TH[step]}) ให้ lot IDLE {len(idle)} lot", "reason": reason}

    if kind == "RELEASE_LOTS":
        ids = sorted({str(x).upper() for x in params.get("lot_ids") or []})
        if not ids:
            raise ProposalError("ต้องระบุ lot_ids")
        items = {it["lot_id"]: it for it in ds.inventory().get("items") or []}
        bad = []
        for lot_id in ids:
            it = items.get(lot_id)
            if not it:
                bad.append(f"{lot_id} ไม่พบหรือไม่มีของเหลือ")
            elif it.get("ai_status") == "IDLE":
                bad.append(f"{lot_id} เป็น IDLE อยู่แล้ว")
            elif it.get("open_tasks") or it.get("waiting_plans"):
                bad.append(f"{lot_id} ยังมีงานค้างหรือ plan รออนุมัติ")
        if bad:
            raise ProposalError("คืน lot ไม่ได้: " + "; ".join(bad))
        return {"kind": kind, "params": {"lot_ids": ids},
                "title": f"คืน {len(ids)} lot เป็น IDLE ({', '.join(ids[:4])}{' …' if len(ids) > 4 else ''})",
                "reason": reason}

    # BLOCK_KITCHEN
    dep = str(params.get("department_id") or "").upper()
    row = kitchen_today(ds, dep) if dep else None
    if not row:
        deps = sorted({k["department_id"] for k in ds.kitchen() or []})
        raise ProposalError(f"ไม่พบครัว {dep or '(ไม่ได้ระบุ)'} ของวันนี้ (มี: {', '.join(deps)})")
    remaining = float(row.get("remaining_hrs") or 0)
    if remaining <= 0:
        raise ProposalError(f"ครัว {dep} ไม่มีชั่วโมงว่างแล้ววันนี้ ไม่ต้องปิดเพิ่ม")
    hours = params.get("hours")
    hours = remaining if hours in (None, "") else min(float(hours), remaining)
    if hours <= 0:
        raise ProposalError("hours ต้องมากกว่า 0")
    then_run = bool(params.get("then_run_pipeline"))
    title = f"ปิดครัว {dep} วันนี้ {hours:g} ชั่วโมง" + (" แล้ววางแผนใหม่" if then_run else "")
    return {"kind": kind, "params": {"department_id": dep, "date": str(row["capacity_date"])[:10], "hours": round(hours, 2),
                                     "then_run_pipeline": then_run},
            "title": title, "reason": reason}


# ---------------------------------------------------------------- tool ของแชท
def propose_action(ds, args: dict[str, Any]):
    try:
        p = build(ds, args["kind"], args.get("params"), args.get("reason") or "")
    except ProposalError as e:
        raise ValueError(str(e)) from None
    result = {"proposal": p["title"], "status": "รอผู้จัดการกดยืนยันบนการ์ด (ยังไม่ได้ทำอะไร)"}
    return result, {"type": "proposal", "source": "CHAT", **p}
