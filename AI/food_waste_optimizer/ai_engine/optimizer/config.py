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
    # ยอดขายใช้ quantile P10/P50/P90 ของ forecaster (demand.survival_segments) แทน demand_kappa เดิม
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
    # ASSUMPTION: ของที่ขายไม่หมดถูกเก็บเข้าห้องพักขยะตอนหมดเวลาขาย (ร้านปิดของวันหมดอายุ) แล้วรอรอบรับถัดไป
    #             รอบรับ end-of-life ต้องเริ่มหลังเวลานั้น + eol_lead_minutes
    eol_lead_minutes: int = 0
    kitchen_lead_minutes: int = 30          # ASSUMPTION: ครัวเริ่มงานได้หลังตอนนี้ + 30 นาที (วันอื่นเริ่มตอน store_open)
    # ASSUMPTION: เวลาเลิกกะครัว งานต้องเสร็จก่อนเวลานี้ (ไม่ใช่เวลาเริ่มขายแล้ว: เมนูเริ่มขายเมื่อ batch แรกเสร็จ
    #             due_by = เวลาเริ่ม + เวลาทำ x batch)
    kitchen_due_time: time = time(17, 0)

    # ---------------- ค่าเที่ยว partner
    # "dedicated" = partner มาเฉพาะของรอบนี้ คิด fixed_cost_per_trip + travel_cost_per_trip เต็ม และบังคับ min_kg_per_pickup
    # "scheduled" = ASSUMPTION: partner วิ่งรอบประจำมารับขยะอื่นของร้านอยู่แล้ว ค่าเที่ยว/ขั้นต่ำเป็นของสัญญาเดิม
    #               คิดเฉพาะ handling_fee_per_kg (ใช้ทำ scenario เปรียบเทียบ ยังไม่มีข้อมูลสัญญาจริงรองรับ)
    trip_cost_mode: str = "dedicated"
    # เที่ยวของวันถัดไป (ไม่ใช่วันรับรอบแรกของ partner) เช่น เก็บของที่หมดอายุพรุ่งนี้ไว้ขายต่อแล้วกำจัดพรุ่งนี้
    # คิดค่าเที่ยว x share: 1.0 = รอบนี้จ่ายเต็มเหมือนเที่ยวมาเฉพาะของรอบนี้
    # ASSUMPTION (ค่าเริ่มต้น 0, ยืนยันโดยทีม 21 ต.ค.): rolling horizon - Optimizer รันใหม่ทุกวัน เที่ยววันถัดไปจะถูกตัดสินใจ
    #   ในรอบนั้นและน่าจะใช้ร่วมกับ lot อื่น รอบนี้จึงคิดเฉพาะค่าต่อ kg (ไม่บังคับขั้นต่ำ) ของเที่ยววันถัดไป
    deferred_trip_cost_share: float = 0.0

    # ---------------- Solver
    unresolved_penalty_per_unit: float = 10_000.0   # หน่วยที่ไม่มีทางไปเลย ถูกปรับหนักเพื่อบังคับให้หาทางก่อน
    # ASSUMPTION: ของที่วางขายแล้วขายไม่หมดแต่ไม่มี partner end-of-life รับ (เช่น รับได้แค่ธนาคารอาหารที่ต้องการอายุเหลือ)
    #             ต้องทิ้งเองในร้าน คิดค่าเสียหายเพิ่ม = factor x unit_cost ต่อหน่วยที่คาดว่าเหลือ (ใช้ในเป้าหมายเท่านั้น
    #             ไม่นับในกำไรที่รายงาน) ให้ solver ชั่งกับการบริจาค/ส่ง partner ตอนนี้
    eol_no_route_penalty_factor: float = 1.0
    solver_time_limit_s: float = 30.0
    solver_mip_gap: float = 1e-4

    # ---------------- การส่ง decision
    # "extended" = ส่ง partner แต่ละประเภทเป็น action ของตัวเอง (ANIMAL_FEED / COMPOST / ANAEROBIC_DIGESTION / LANDFILL)
    #              DB และ server รับ 8 ค่าแล้ว (DISCARD = ทิ้งเองในร้าน ไม่มี partner)
    # "current"  = แบบเดิม: partner กำจัดส่งเป็น DISCARD + target_partner_id (ใช้กับ server รุ่นเก่าที่รับแค่ 4 ค่า)
    action_mode: str = "extended"
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