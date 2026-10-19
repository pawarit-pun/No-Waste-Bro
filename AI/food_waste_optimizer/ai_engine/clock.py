"""PART 0 — นาฬิกาของระบบ (เวลาไทย) ใช้ร่วมกันทุกโมดูล

- วันที่อ้างอิง (reference_date) = วันนี้ตามเวลาไทย หรือ DEMO_DATE ใน .env ถ้าตั้งไว้
- เวลาในวัน: ถ้าตั้ง DEMO_DATE จะใช้ DEMO_TIME (ค่าเริ่มต้น 08:00) เพราะ partner มี "ช่วงเวลารับของ"
  (pickup_time_start/end) ต้องรู้ว่าตอนนี้ (ที่จำลอง) กี่โมงถึงเช็คได้ว่ารับทันวันนี้ไหม
- ชื่อฟังก์ชัน BKK / today_bkk ตรงกับ core.dates ของ API server เพื่อสลับใช้แทนกันได้
"""
from __future__ import annotations

import os
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

BKK = ZoneInfo("Asia/Bangkok")
DEFAULT_DEMO_TIME = time(8, 0)


def _env(name: str) -> Optional[str]:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def load_env(path: str | Path = ".env") -> None:
    """โหลดไฟล์ .env แบบง่าย (ไม่ทับค่าที่ตั้งไว้ใน environment แล้ว)"""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def today_bkk() -> date:
    demo = _env("DEMO_DATE")
    return date.fromisoformat(demo) if demo else datetime.now(BKK).date()


def now_bkk() -> datetime:
    """เวลาที่ใช้จำลอง: DEMO_DATE + DEMO_TIME ถ้าตั้ง DEMO_DATE ไม่งั้นเวลาจริง"""
    demo = _env("DEMO_DATE")
    if not demo:
        return datetime.now(BKK)
    t = time.fromisoformat(_env("DEMO_TIME") or DEFAULT_DEMO_TIME.isoformat())
    return datetime.combine(date.fromisoformat(demo), t, tzinfo=BKK)


def now_for(reference_date: date) -> datetime:
    """เวลาจำลองของวัน reference_date (ใช้เวลาจาก now_bkk ถ้าวันตรงกัน ไม่งั้น DEFAULT_DEMO_TIME)"""
    current = now_bkk()
    if current.date() == reference_date:
        return current
    return datetime.combine(reference_date, DEFAULT_DEMO_TIME, tzinfo=BKK)
