"""Enum ที่ตรงกับ enum type ใน Supabase"""
from enum import Enum


class ActionType(str, Enum):
    MARKDOWN = "MARKDOWN"                        # ลดราคา
    KITCHEN_REPURPOSE = "KITCHEN_REPURPOSE"      # ส่งเข้าครัว
    DONATE = "DONATE"                            # บริจาค (partner)
    ANIMAL_FEED = "ANIMAL_FEED"                  # ส่งทำอาหารสัตว์ (partner)
    COMPOST = "COMPOST"                          # ส่งทำปุ๋ยหมัก (partner)
    ANAEROBIC_DIGESTION = "ANAEROBIC_DIGESTION"  # ส่งโรงก๊าซชีวภาพ (partner)
    LANDFILL = "LANDFILL"                        # ส่งฝังกลบ (partner)
    DISCARD = "DISCARD"                          # ทิ้งเองในร้าน ไม่มี partner


# action ที่ส่งให้ partner → (partner_type ที่รับได้, flag ของสินค้าที่ต้องเป็น true)
PARTNER_ACTIONS: dict[ActionType, tuple[frozenset[str], str]] = {
    ActionType.DONATE: (frozenset({"DONATION", "FOOD_BANK", "CHARITY", "COMMUNITY", "TEMPLE"}), "allow_donation"),
    ActionType.ANIMAL_FEED: (frozenset({"ANIMAL_FEED"}), "allow_animal_feed"),
    ActionType.COMPOST: (frozenset({"COMPOSTING"}), "allow_composting"),
    ActionType.ANAEROBIC_DIGESTION: (frozenset({"ANAEROBIC_DIGESTION"}), "allow_anaerobic_digestion"),
    ActionType.LANDFILL: (frozenset({"LANDFILL"}), "allow_landfill"),
}


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class LotAIStatus(str, Enum):
    IDLE = "IDLE"
    PROCESSING = "PROCESSING"
    CHECKED = "CHECKED"


class DecisionStatus(str, Enum):
    PENDING = "PENDING"            # LLM ยังไม่ได้เขียน task
    IN_REVIEW = "IN_REVIEW"        # LLM ส่ง plan แล้ว รอผู้จัดการอนุมัติ (pending_tasks = WAITING)
    REJECTED = "REJECTED"          # ผู้จัดการปฏิเสธ plan (ไม่มี task)
    TASK_CREATED = "TASK_CREATED"  # ผู้จัดการอนุมัติแล้ว สร้าง task ให้ staff แล้ว


class ReviewStatus(str, Enum):
    WAITING = "WAITING"    # รอผู้จัดการอนุมัติ (ไม่มีการอนุมัติอัตโนมัติ)
    APPROVED = "APPROVED"  # อนุมัติแล้ว สร้าง ai_recommended_tasks แล้ว
    REJECTED = "REJECTED"  # ปฏิเสธแล้ว (มีเหตุผลใน review_note)


class StaffRole(str, Enum):
    MANAGER = "MANAGER"  # เข้า web dashboard
    STAFF = "STAFF"      # เข้า staff mobile app


class TaskStatus(str, Enum):
    PENDING = "PENDING"            # รอ staff เริ่มทำ
    IN_PROGRESS = "IN_PROGRESS"    # staff กำลังทำ
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
