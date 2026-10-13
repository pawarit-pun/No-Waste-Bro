from datetime import date, datetime
from zoneinfo import ZoneInfo

from configs.config import db_env

BKK = ZoneInfo("Asia/Bangkok")


def today_bkk() -> date:
    """วันที่ปัจจุบันตามเวลาไทย หรือ DEMO_DATE ใน .env (ใช้ตอน demo)"""
    if db_env.demo_date:
        return date.fromisoformat(db_env.demo_date)
    return datetime.now(BKK).date()
