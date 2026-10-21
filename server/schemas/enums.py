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
    PENDING = "PENDING"            # ยังไม่มี task
    TASK_CREATED = "TASK_CREATED"  # LLM สร้าง task แล้ว


class StaffRole(str, Enum):
    MANAGER = "MANAGER"  # เข้า web dashboard
    STAFF = "STAFF"      # เข้า staff mobile app


class TaskStatus(str, Enum):
    PENDING = "PENDING"            # รอ staff เริ่มทำ
    IN_PROGRESS = "IN_PROGRESS"    # staff กำลังทำ
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
