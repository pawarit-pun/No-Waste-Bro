#!/usr/bin/env bash
# Reset inventory_lots + สร้าง mock data ชุด v4 (lot demo 27 ล็อต) แล้วโหลดขึ้น Supabase
#
# ใช้งาน (จากโฟลเดอร์ server):
#   bash scripts/reset_mock_lots.sh           # ถามยืนยันก่อนลบข้อมูลใน Supabase
#   bash scripts/reset_mock_lots.sh --yes     # ไม่ถาม
#
# ลำดับ:
#   1. scripts/forecast_data/simulate.py        -> data/{daily_context,product_daily,inventory_lots_demo}.csv
#      (lot demo + ยอดขายย้อนหลัง 365 วันจำลองพร้อมกัน สต็อกปิดวันที่ 15 ต.ค. = ผลรวมของ lot พอดี)
#   2. python -m scripts.load_mock_data          -> ล้าง task / decision / ผลสแกน / forecast / การจองครัว
#                                                  แล้วแทนที่ inventory_lots + product_daily + daily_context + baseline
#   3. AI/risk_forecaster/tools/build_dataset.py -> คัดลอก CSV ชุดเดียวกันไป data/mock_v3 (+ training_dataset.csv)
#                                                  Forecaster ใน image ของ worker เทรนจากไฟล์นี้ตอน build
#
# ไม่แตะ products / recipes / donation_partners / kitchen_capacity / staff
# วัน demo = 2026-10-16 (ตรงกับ DEMO_DATE ของ server และ DemoDate ตอน sam deploy)
#
# env ที่เปลี่ยนได้:
#   PY_SERVER  python ที่มี supabase (ค่าเริ่มต้น .venv/bin/python ของ server ถ้ามี ไม่งั้น python3)
#   PY_DATA    python ที่มี numpy + pandas (ค่าเริ่มต้น python3) ติดตั้ง: python3 -m pip install numpy pandas
set -euo pipefail

cd "$(dirname "$0")/.."            # server/
SERVER_DIR="$(pwd)"
AI_RF="${SERVER_DIR}/../AI/risk_forecaster"
DEMO_DATE_FIXED="2026-10-16"

PY_SERVER="${PY_SERVER:-$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)}"
PY_DATA="${PY_DATA:-python3}"

echo "→ ตรวจ python"
"${PY_SERVER}" -c "import supabase" 2>/dev/null \
  || { echo "✗ ${PY_SERVER} ไม่มี supabase (ตั้ง PY_SERVER=<python ของ server>)" >&2; exit 1; }
"${PY_DATA}" -c "import numpy, pandas" 2>/dev/null \
  || { echo "✗ ${PY_DATA} ไม่มี numpy / pandas: ${PY_DATA} -m pip install numpy pandas (หรือตั้ง PY_DATA=...)" >&2; exit 1; }
env_date="$(grep -E '^DEMO_DATE=' .env 2>/dev/null | cut -d= -f2- || true)"
if [ "${env_date}" != "${DEMO_DATE_FIXED}" ]; then
  echo "✗ server/.env มี DEMO_DATE=${env_date:-<ว่าง>} ต้องเป็น ${DEMO_DATE_FIXED} (lot demo ออกแบบไว้สำหรับวันนั้น)" >&2
  exit 1
fi

echo "→ 1) simulate.py"
(cd scripts/forecast_data && "${PY_DATA}" simulate.py)

echo "→ 2) โหลดขึ้น Supabase (ลบข้อมูลเดิมของตารางที่เกี่ยวข้อง)"
"${PY_SERVER}" -m scripts.load_mock_data --src scripts/forecast_data/data --demo-date "${DEMO_DATE_FIXED}" "$@"

echo "→ 3) คัดลอก CSV ไป AI/risk_forecaster/data/mock_v3"
(cd "${AI_RF}" && "${PY_DATA}" tools/build_dataset.py "${SERVER_DIR}/scripts/forecast_data/data" data/mock_v3)
chmod -R a+rX "${AI_RF}/data" "${SERVER_DIR}/../AI/food_waste_optimizer"   # Lambda อ่านไฟล์ใน image ด้วย user อื่น

echo
echo "✓ เสร็จ ขั้นต่อไป (จากโฟลเดอร์ No-Waste-Bro): build + deploy ใหม่ ให้ Forecaster ใน image เทรนจากข้อมูลชุดนี้"
echo "  ./AI/pipeline/build_worker.sh && cd server && ./scripts/build_lambda.sh && sam deploy --parameter-overrides \\"
echo "    SupabaseServiceRoleKey=\"\$(grep '^SUPABASE_SERVICE_ROLE_KEY=' .env | cut -d= -f2-)\" \\"
echo "    WorkerImageUri=\"\$(cat ../AI/pipeline/.last_image_uri)\" DemoDate=${DEMO_DATE_FIXED}"
