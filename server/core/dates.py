from datetime import date, datetime
from zoneinfo import ZoneInfo

from configs.config import db_env

BKK = ZoneInfo("Asia/Bangkok")


def today_bkk() -> date:
    """วันที่ปัจจุบันตามเวลาไทย หรือ DEMO_DATE ใน .env (ใช้ตอน demo)"""
    if db_env.demo_date:
        return date.fromisoformat(db_env.demo_date)
    return datetime.now(BKK).date()


def now_bkk() -> datetime:
    """วันเวลาที่ระบบใช้คิด = วันที่จาก today_bkk() (DEMO_DATE ถ้าตั้งไว้) + เวลาของนาฬิกาไทยตอนที่รัน

    ใช้กับงานที่ขึ้นกับเวลาในวัน เช่น Optimizer เช็คช่วงเวลารับของของ partner และชั่วโมงครัวที่เหลือของวันนี้
    ไม่มีค่าเวลาใน .env: รันตอนไหน ก็ใช้เวลานั้นคิด (ย้ายมาจาก AI/food_waste_optimizer/ai_engine/clock.py)
    """
    return datetime.combine(today_bkk(), datetime.now(BKK).timetz())