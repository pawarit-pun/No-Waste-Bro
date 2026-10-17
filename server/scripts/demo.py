"""ล้าง / ใส่ข้อมูล demo (เรียกฟังก์ชันใน Postgres ที่สร้างจาก scripts/demo_functions.sql)

ใช้งาน (รันในโฟลเดอร์ server):
    python -m scripts.demo reset-seed                  # ล้างแล้วใส่ข้อมูล demo ของวันนี้ (ใช้บ่อยสุด)
    python -m scripts.demo reset                       # ล้างอย่างเดียว
    python -m scripts.demo seed                        # ใส่ข้อมูล demo (ต้อง reset ก่อน)
    python -m scripts.demo reset-seed --date 2026-10-20
    python -m scripts.demo snapshot                    # หลังโหลด mock data ชุดใหม่: เก็บ lot ตอนนี้เป็นค่าตั้งต้น
"""
import argparse
import json
import sys
from datetime import date

from postgrest.exceptions import APIError

from core.dates import today_bkk
from db.supabase import supabase


def call(fn: str, day: date) -> dict:
    param = "p_ref" if fn == "demo_snapshot" else "p_today"
    return supabase.rpc(fn, {param: day.isoformat()}).execute().data


def show_reset(r: dict) -> None:
    print(f"✓ reset ({r['demo_date']}): ลบ task {r['tasks_deleted']}, decision {r['decisions_deleted']}, "
          f"assessment {r['assessments_deleted']}, lot ที่เกิดจาก demo {r['lots_deleted']} | "
          f"คืนค่า lot {r['lots_restored']} | คืนชั่วโมงครัว {r['kitchen_days_released']} วัน")


def show_seed(r: dict) -> None:
    print(f"✓ seed ({r['demo_date']}): สร้าง {len(r['tasks'])} task")
    for t in r["tasks"]:
        extra = f"  pickup {t['pickup']}" if t.get("pickup") else ""
        print(f"   {t['staff']}  {t['lot_id']}  {t['action']:<18} {t['status']}{extra}")
    for b in r["kitchen_bookings"]:
        print(f"   จองครัว {b['department_id']} {b['date']} {b['hours']} ชม.")


def main() -> None:
    parser = argparse.ArgumentParser(description="จัดการข้อมูล demo ของ No-Waste-Bro")
    parser.add_argument("command", choices=["reset", "seed", "reset-seed", "snapshot"])
    parser.add_argument("--date", type=date.fromisoformat, default=None,
                        help="วัน demo (YYYY-MM-DD) ค่าเริ่มต้น = วันนี้ (หรือ DEMO_DATE ใน .env)")
    args = parser.parse_args()
    day = args.date or today_bkk()

    try:
        if args.command in ("reset", "reset-seed"):
            show_reset(call("demo_reset", day))
        if args.command in ("seed", "reset-seed"):
            show_seed(call("demo_seed", day))
        if args.command == "snapshot":
            r = call("demo_snapshot", day)
            print(f"✓ snapshot: เก็บ {r['lots']} lot เป็นค่าตั้งต้น (วันอ้างอิง {r['reference_date']})")
    except APIError as e:
        print(f"✗ {e.message}", file=sys.stderr)
        if "Could not find the function" in (e.message or ""):
            print("  → ยังไม่ได้รัน scripts/demo_functions.sql ใน Supabase SQL Editor", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
