"""ค่าตั้งต้นทั้งหมดของ Forecaster + Risk Scanner (แก้ที่นี่ที่เดียว)"""
import json
import os
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = AI_DIR / "data"
MOCK_DIR = DATA_DIR / "mock_v3"                       # CSV ที่ใช้ทั้งเทรนและโหมด local
REFERENCE_DIR = DATA_DIR / "reference"                # products.json / recipes.json (ข้อมูลที่ scan-inputs ไม่ส่งมา)
MODEL_DIR = AI_DIR / "models"
OUTPUT_DIR = AI_DIR / "output"

MODEL_VERSION = "forecaster_v3"
RISK_MODEL_VERSION = "risk-v3"

# API (โหมด api) ใส่ใน env ของเครื่องที่รัน
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1")
HISTORY_DAYS = 56                                     # ส่งให้ GET /ai/scan-inputs?history_days= (lag 56 วัน)

# ร้านเปิด 08:00-22:00 (นิยามของ product_daily: opening 08:00, closing 22:00)
STORE_OPEN_HOUR = 8
STORE_CLOSE_HOUR = 22

# ---------------------------------------------------------------- Forecaster
MAX_HORIZON = 14                                      # เทรนทำนายล่วงหน้า 1-14 วัน (เกินนี้ใช้ horizon 14)
MIN_HISTORY_DAYS = 14                                 # origin ต้องมีประวัติอย่างน้อยกี่วันถึงใช้เทรน
# แบ่งข้อมูลตามเวลา (rolling origin, Hyndman): test = 20% ล่าสุด, validation = 20% ก่อนหน้า, ที่เหลือ = train
TEST_FRACTION = 0.20
VAL_FRACTION = 0.20
MIN_WINDOW_DAYS = 28
LGBM_GRID = [
    dict(num_leaves=7, min_child_samples=20, learning_rate=0.05, n_estimators=300),
    dict(num_leaves=15, min_child_samples=20, learning_rate=0.03, n_estimators=400),
    dict(num_leaves=15, min_child_samples=40, learning_rate=0.03, n_estimators=600),
    dict(num_leaves=31, min_child_samples=40, learning_rate=0.02, n_estimators=600),
]
DISCOUNT_LEVELS = (0, 20, 30, 50)
# วัน "ลดทั้งวัน" = ขายราคาลดได้อย่างน้อย 90% ของยอดทั้งวัน (แยกจากการลดเฉพาะของเหลือช่วงค่ำ)
# v3.1: เดิม 0.5 ทำให้วันลดของเหลือ 30% ช่วงค่ำปนเข้ากลุ่ม "ลดทั้งวัน 30%" lift 30% จึงเท่ากับ 20% (x1.112)
# ที่ 0.9: x1.112 / x1.163 / x1.333 เรียงถูก (simulator ตั้ง x1.12 / x1.20 / x1.35)
FULL_DAY_MARKDOWN_SHARE = 0.9
MIN_LIFT_DAYS = 10
# หมวดที่ลดราคาเฉพาะ "ของเหลือช่วงค่ำ" (วันที่ลดราคาแปลว่ามีของเหลือ ยอดขายไม่ถูกตัดหัว และเพิ่มขึ้นเล็กน้อยเท่านั้น)
CLEARANCE_ONLY_CATEGORIES = ("READY_TO_EAT",)

# ---------------------------------------------------------------- Risk Scanner
# สัดส่วนลูกค้าที่หยิบล็อตที่ใหม่ที่สุดแทนล็อตที่หมดอายุก่อน (ที่เหลือหยิบแบบ FIFO)
# งานวิจัยกับห้างใหญ่ในยุโรป (MSOM 2026) พบว่าลูกค้าเลือกของใหม่สุดเป็นหลัก (LEFO) แต่ไม่มีตัวเลขสัดส่วนที่ใช้ได้ทั่วไป
# 0.4 = ค่าเดียวกับ simulator ของ mock data (PICK_NEWEST_SHARE, ASSUMPTION) ควรปรับเมื่อมียอดขายแยกตามล็อต
NEWEST_PICK_SHARE = 0.4
# cutoff ของ score (% ที่คาดว่าจะเหลือทิ้ง) ค่าจริงมาจาก calibrate_risk.py -> models/risk_thresholds.json
CUTOFF_CANDIDATES = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90)
DEFAULT_THRESHOLDS = {"MEDIUM": 30, "HIGH": 50, "CRITICAL": 80, "last_day_bump": True}
FORWARD_LEVELS = ("HIGH", "CRITICAL")                 # ส่งต่อ Optimizer
RETURN_TO_IDLE_LEVELS = ("LOW", "MEDIUM")             # คืนเป็น IDLE ให้สแกนใหม่พรุ่งนี้


def load_thresholds():
    path = MODEL_DIR / "risk_thresholds.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: data[k] for k in DEFAULT_THRESHOLDS}
    return dict(DEFAULT_THRESHOLDS)
