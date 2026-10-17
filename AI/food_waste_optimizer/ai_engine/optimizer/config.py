"""PART 0 — ค่าที่ปรับได้ทั้งหมดของ Optimizer อยู่ที่นี่ที่เดียว

ค่าที่ไม่ได้มาจาก Supabase / Swagger / คำสั่งงาน เป็น "สมมติฐานที่ผมตั้งเอง" (ทำเครื่องหมาย ASSUMPTION)
ให้ทีมปรับได้โดยสร้าง OptimizerConfig(...) ใหม่แล้วส่งเข้า run_optimizer(cfg=...)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class OptimizerConfig:
    model_version: str = "optimizer_v2"

    # --- Markdown (จากคำสั่งงาน: 20-80%) 0 = ขายราคาปกติ (ไม่ต้องทำอะไร) ---
    markdown_levels: tuple = (0, 20, 30, 40, 50, 60, 70, 80)
    # ASSUMPTION: ใช้ demand แบบระวัง = expected - kappa*(expected - low) กันพยากรณ์เกิน
    demand_kappa: float = 0.5

    # --- เวลา ---
    # ASSUMPTION: lot หมดอายุสิ้นวันของ expiration_date
    expiry_cutoff: time = time(23, 59, 59)
    # ASSUMPTION: ต้องเตรียมของ/แพ็คก่อน partner มารับ (นาที)
    lead_time_minutes: int = 60
    max_pickup_wait_days: int = 7
    # ASSUMPTION: ครัวเริ่มงานได้หลังเวลาปัจจุบัน + kitchen_lead_minutes และต้องเสร็จก่อน kitchen_due_time
    kitchen_lead_minutes: int = 30
    kitchen_due_time: time = time(17, 0)

    # --- Solver ---
    # หน่วยที่ไม่มีทางไปเลย (ไม่มี partner รับ) โดนปรับหนักเพื่อบังคับให้ solver หาทางก่อน
    unresolved_penalty_per_unit: float = 10_000.0
    solver_time_limit_s: float = 30.0
    solver_mip_gap: float = 1e-4

    # --- การส่งเข้า POST /optimization-decisions ---
    # "current"  = enum action_type ที่มีอยู่จริงตอนนี้ (MARKDOWN/KITCHEN_REPURPOSE/DONATE/DISCARD)
    # "extended" = หลังรัน sql/001_schema_fixes.sql และแก้ API ให้รับ ANIMAL_FEED/COMPOST/ANAEROBIC_DIGESTION/LANDFILL
    action_mode: str = "current"
    # ส่งเวลารับของของ partner ใน due_by ด้วย (ฟิลด์นี้บังคับเฉพาะ KITCHEN แต่ไม่ห้ามใน action อื่น)
    partner_due_by: bool = True
    # ถ้า API ไม่ส่ง allow_animal_feed/... มา: "deny" = ถือว่าไม่อนุญาต, "allow" = ถือว่าอนุญาต
    missing_flag_policy: str = "deny"

    # --- เกณฑ์เตือน (ไม่ใช่กฎบล็อก) ---
    warn_trip_cost_per_kg: float = 100.0
    warn_kitchen_utilization: float = 0.9


# method ภายใน -> action_type ที่ส่งเข้า API
ACTION_BY_METHOD = {
    "current": {
        "MARKDOWN": "MARKDOWN",
        "KITCHEN": "KITCHEN_REPURPOSE",
        "DONATION": "DONATE",
        "ANIMAL_FEED": "DISCARD",
        "COMPOSTING": "DISCARD",
        "ANAEROBIC_DIGESTION": "DISCARD",
        "LANDFILL": "DISCARD",
        "UNRESOLVED": "DISCARD",
    },
    "extended": {
        "MARKDOWN": "MARKDOWN",
        "KITCHEN": "KITCHEN_REPURPOSE",
        "DONATION": "DONATE",
        "ANIMAL_FEED": "ANIMAL_FEED",
        "COMPOSTING": "COMPOST",
        "ANAEROBIC_DIGESTION": "ANAEROBIC_DIGESTION",
        "LANDFILL": "LANDFILL",
        "UNRESOLVED": "DISCARD",
    },
}
