"""ดึงอากาศจริงจาก Open-Meteo (กรุงเทพฯ 13.75, 100.50) ให้ simulate.py

ใช้งาน (ต้องออกอินเทอร์เน็ตไป archive-api.open-meteo.com และ api.open-meteo.com ได้):
    python3 fetch_weather.py                              # ประวัติ 365 วันถึง 15 ต.ค. 2569 + พยากรณ์ 16-25 ต.ค.
    python3 fetch_weather.py --start 2025-10-16 --end 2026-10-15

เขียนทับ data/weather_archive.json และ data/weather_forecast.json (รูปแบบเดียวกับไฟล์เดิม)
simulate.py จะเริ่มประวัติจากวันแรกในไฟล์ archive เอง
"""
import argparse
import json
import urllib.parse
import urllib.request
from datetime import date, timedelta

LAT, LON, TZ = 13.75, 100.50, "Asia/Bangkok"
DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum"
HOURLY = "precipitation"


def fetch(base, **params):
    query = urllib.parse.urlencode(dict(latitude=LAT, longitude=LON, timezone=TZ, daily=DAILY, hourly=HOURLY, **params))
    with urllib.request.urlopen(f"{base}?{query}", timeout=60) as res:
        return json.load(res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 15))
    ap.add_argument("--start", type=date.fromisoformat, default=None)
    ap.add_argument("--forecast-to", type=date.fromisoformat, default=date(2026, 10, 25))
    args = ap.parse_args()
    start = args.start or args.end - timedelta(days=364)

    archive = fetch("https://archive-api.open-meteo.com/v1/archive",
                    start_date=start.isoformat(), end_date=args.end.isoformat())
    forecast = fetch("https://api.open-meteo.com/v1/forecast",
                     start_date=(args.end + timedelta(1)).isoformat(), end_date=args.forecast_to.isoformat())
    for name, data in (("data/weather_archive.json", archive), ("data/weather_forecast.json", forecast)):
        days = data["daily"]["time"]
        missing = sum(v is None for v in data["daily"]["precipitation_sum"])
        with open(name, "w") as f:
            json.dump(data, f)
        print(f"{name}: {days[0]} -> {days[-1]} ({len(days)} วัน, ค่าว่าง {missing})")


if __name__ == "__main__":
    main()
