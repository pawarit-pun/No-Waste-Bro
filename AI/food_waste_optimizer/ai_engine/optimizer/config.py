"""PART 0 — ค่าตั้งต้นทั้งหมดของ Optimizer + เวลาที่ใช้คิด (แก้ที่นี่ที่เดียว)

เวลา (ย้ายมาจาก ai_engine/clock.py ที่ถูกยุบแล้ว):
  วันที่  = reference_date ที่ server ส่งมาใน GET /ai/optimize-inputs (= DEMO_DATE ใน server/.env หรือวันนี้ตามเวลาไทย)
  เวลา   = นาฬิกาไทยตอนที่รันโปรแกรม (ไม่มี DEMO_TIME แล้ว รันตอนไหนก็ใช้เวลานั้นคิด)
  ฝั่ง server ใช้กติกาเดียวกันใน server/core/dates.py: now_bkk()

ค่าที่เขียน ASSUMPTION = สมมติฐานที่ยังไม่มีในข้อมูล/เอกสาร ปรับได้โดยส่ง OptimizerConfig(...) ใหม่เข้า run_optimizer(cfg=...)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

BKK = ZoneInfo("Asia/Bangkok")


def simulated_now(reference_date: date, clock: Optional[datetime] = None) -> datetime:
    """วันเวลาที่ Optimizer ใช้คิด = reference_date + เวลานาฬิกาไทยตอนนี้ (หรือเวลาของ clock ที่ส่งมา)"""
    wall = (clock or datetime.now(BKK)).astimezone(BKK)
    return datetime.combine(reference_date, wall.time().replace(microsecond=0), tzinfo=BKK)


@dataclass(frozen=True)
class OptimizerConfig:
    model_version: str = "optimizer_v3"

    # ---------------- Markdown (ลดราคา)
    # นโยบายร้าน: ลดได้ 20-80% ระดับที่ใช้จริง = ระดับที่ forecaster ส่ง shelf มา (ตอนนี้ 0 / 20 / 30 / 50)
    # ระดับที่ forecaster ไม่ได้พยากรณ์จะไม่ถูกใช้ (ไม่เดายอดขายเอง)
    allowed_discounts: tuple = (20, 30, 40, 50, 60, 70, 80)
    # ใช้ยอดขายแบบระวัง = expected - kappa x (expected - low_qty) กันพยากรณ์เกินจริง (0 = เชื่อ expected เต็ม, 1 = ใช้ low_qty)
    demand_kappa: float = 0.5
    # lost_sales_other_lots x (regular_price - base_cost) x factor = กำไรที่ล็อตอื่นของสินค้าเดียวกันเสียไปเมื่อลดราคาล็อตนี้
    lost_sales_margin_factor: float = 1.0

    # ---------------- เวลา
    store_open: time = time(8, 0)          # ตรงกับ STORE_OPEN_HOUR / STORE_CLOSE_HOUR ของ risk_forecaster
    store_close: time = time(22, 0)
    # shelf / recipe_demand ของ forecaster คิด "ตั้งแต่เปิดร้านวันนี้" ถ้ารันช้ากว่านั้นให้หักชั่วโมงที่ผ่านไปแล้ว
    # ASSUMPTION: ยอดขายกระจายเท่ากันทุกชั่วโมงที่ร้านเปิด
    scale_by_open_hours: bool = True
    expiry_cutoff: time = time(23, 59, 59)  # lot หมดอายุสิ้นวัน expiration_date (ประกาศ สธ. 367)
    lead_time_minutes: int = 60             # ASSUMPTION: เวลาเตรียม/แพ็คของก่อน partner มารับ
    max_pickup_wait_days: int = 7
    kitchen_lead_minutes: int = 30          # ASSUMPTION: ครัวเริ่มงานได้หลังตอนนี้ + 30 นาที
    kitchen_due_time: time = time(17, 0)    # ASSUMPTION: งานครัวต้องเสร็จก่อน 17:00 (= due_by ตัวอย่างใน Swagger)

    # ---------------- Solver
    unresolved_penalty_per_unit: float = 10_000.0   # หน่วยที่ไม่มีทางไปเลย ถูกปรับหนักเพื่อบังคับให้หาทางก่อน
    solver_time_limit_s: float = 30.0
    solver_mip_gap: float = 1e-4

    # ---------------- การส่ง decision
    # "current"  = action_type ที่ DB มีตอนนี้ (MARKDOWN / KITCHEN_REPURPOSE / DONATE / DISCARD)
    # "extended" = หลังรัน sql/001_schema_fixes.sql ข้อ 1 และแก้ server ให้รับ ANIMAL_FEED / COMPOST / ...
    action_mode: str = "current"
    partner_due_by: bool = True             # ส่งเวลารับของของ partner ใน due_by
    missing_flag_policy: str = "deny"       # ไม่มี allow_animal_feed ฯลฯ ในข้อมูล -> ถือว่าไม่อนุญาต
    process_ai_statuses: tuple = ("PROCESSING",)   # lot ที่ Risk Scanner ส่งต่อแล้วยังไม่มี task (CHECKED / IDLE ข้าม)
    release_no_action_lots: bool = True     # lot ที่ไม่ต้องทำอะไร (ขายราคาปกติได้หมด) -> IDLE ให้สแกนใหม่พรุ่งนี้
    # วันที่อ้างอิงของ server ต้องตรงกับวันที่รอบสแกน (shelf / recipe_demand คิดจากวันนั้น) ไม่ตรง = หยุด ไม่บันทึก
    allow_stale_scan: bool = False

    # ---------------- เกณฑ์เตือน (ไม่บล็อก)
    warn_trip_cost_per_kg: float = 100.0
    warn_kitchen_utilization: float = 0.9


# วิธีภายใน -> action_type ที่ส่งเข้า POST /optimization-decisions
ACTION_BY_METHOD = {
    "current": {
        "MARKDOWN": "MARKDOWN", "KITCHEN": "KITCHEN_REPURPOSE", "DONATION": "DONATE",
        "ANIMAL_FEED": "DISCARD", "COMPOSTING": "DISCARD", "ANAEROBIC_DIGESTION": "DISCARD",
        "LANDFILL": "DISCARD", "UNRESOLVED": "DISCARD",
    },
    "extended": {
        "MARKDOWN": "MARKDOWN", "KITCHEN": "KITCHEN_REPURPOSE", "DONATION": "DONATE",
        "ANIMAL_FEED": "ANIMAL_FEED", "COMPOSTING": "COMPOST", "ANAEROBIC_DIGESTION": "ANAEROBIC_DIGESTION",
        "LANDFILL": "LANDFILL", "UNRESOLVED": "DISCARD",
    },
}
PARTNER_TYPES = ("DONATION", "ANIMAL_FEED", "COMPOSTING", "ANAEROBIC_DIGESTION", "LANDFILL")