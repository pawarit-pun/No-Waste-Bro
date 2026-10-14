"""Enum ที่ตรงกับ enum type ใน Supabase"""
from enum import Enum


class ActionType(str, Enum):
    MARKDOWN = "MARKDOWN"
    KITCHEN_REPURPOSE = "KITCHEN_REPURPOSE"
    DONATE = "DONATE"
    DISCARD = "DISCARD"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class LotAIStatus(str, Enum):
    IDLE = "IDLE"
    PROCESSING = "PROCESSING"
    CHECKED = "CHECKED"
