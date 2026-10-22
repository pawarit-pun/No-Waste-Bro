# No-Waste-Bro AI: Forecaster + Risk Scanner

ประเมินว่าล็อตไหนจะขายไม่ทันก่อนหมดอายุ แล้วส่งผลให้ Optimizer (`AI/food_waste_optimizer/`) ตัดสินใจว่าจะลดราคา
ส่งเข้าครัว บริจาค หรือกำจัด

```
GET /ai/scan-inputs ──► Forecaster ──► Risk Scanner ──► shelf curve + recipe_demand ──► POST /risk-assessments
 (ล็อต IDLE, ยอดขาย       (ความต้องการ     (score, level,      (เฉพาะ HIGH / CRITICAL)        │ RPC save_risk_run
  56 วัน, ปัจจัยรายวัน)      ต่อวัน)          sellable_hours)                                  ▼
                                   forecast_runs, lot_risk_assessments, lot_shelf_forecasts, recipe_demand_forecasts
                                                                  ──► GET /ai/optimize-inputs ──► Optimizer
```

## โครงสร้างโฟลเดอร์

```
AI/
├── README.md                       (ของ main ไม่แก้ กันชนตอน merge)
├── food_waste_optimizer/           ทีม Optimizer
└── risk_forecaster/                ← งานนี้ทั้งหมด
    ├── train_forecaster.py         1) เทรน Forecaster + วัดผล + บันทึกโมเดล
    ├── calibrate_risk.py           2) เลือก cutoff ระดับความเสี่ยงจากผลจริงรายล็อต
    ├── run_scan.py                 3) รอบสแกน (local อ่าน CSV / api เรียก server จริง)
    ├── forecaster/                 ── ทำนายยอดขาย
    │   ├── features.py             feature แบบ origin (ใช้ทั้งเทรนและทำนาย)
    │   └── model.py                class Forecaster: same-dow / LightGBM, lift ของการลดราคา, phi_k
    ├── risk_scanner/               ── ประเมินความเสี่ยง + ส่งต่อ Optimizer
    │   ├── risk.py                 risk_score, risk_level, sellable_hours, แบ่งความต้องการให้แต่ละล็อต
    │   ├── nb.py                   Negative Binomial (โอกาสขายหมด, ช่วง low-high)
    │   └── handoff.py              shelf curve (ลด x% ขายได้เท่าไร) + recipe_demand
    ├── common/                     ── ใช้ร่วมกัน
    │   ├── config.py               ค่าตั้งต้นทั้งหมด (แก้ที่นี่ที่เดียว)
    │   └── sources.py              LocalSource (CSV) / ApiSource (route จริงของ server)
    ├── tools/build_dataset.py      คัดลอกผล simulate.py มาเป็น data/mock_v3 + สร้าง training_dataset.csv
    ├── data_checks/validate_mock_data.py   ตรวจ mock data + pipeline ทั้งเส้น (5 ข้อ)
    ├── data/
    │   ├── mock_v3/                ข้อมูลเทรน 1 ปี + ผลรายล็อต + ล็อต demo
    │   └── reference/              products.json, recipes.json (snapshot จาก Supabase)
    ├── docs/criteria_sources.md    ที่มาของเกณฑ์และตัวเลขอ้างอิงทุกตัว
    ├── models/                     โมเดล (.pkl ไม่เข้า git) + metrics + risk_thresholds.json
    └── output/                     ผลแต่ละรอบสแกน (ไม่เข้า git)
```

ทุกคำสั่งรันจากโฟลเดอร์ `AI/risk_forecaster` (import เป็น `from common import config`, `from forecaster.model import Forecaster`,
`from risk_scanner import risk`)

## ติดตั้ง

```bat
cd AI\risk_forecaster
python -m venv .venv
.venv\Scripts\activate            :: macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## ทำทั้งเส้นตั้งแต่ข้อมูลจนถึงสแกน

| # | โฟลเดอร์ | คำสั่ง | ทำอะไร | ทำเมื่อไร |
| --- | --- | --- | --- | --- |
| 1 | `server/scripts/forecast_data` | `python fetch_weather.py` | ดึงอากาศจริงกรุงเทพฯ 365 วัน + พยากรณ์ 10 วัน (Open-Meteo) | อยากได้อากาศใหม่ |
| 2 | `server/scripts/forecast_data` | `python simulate.py` | สร้างยอดขาย 1 ปี (14 สินค้า) + ล็อต demo 13 ล็อต + ผลรายล็อต | แก้ simulator / อากาศใหม่ |
| 3 | `AI/risk_forecaster` | `python tools\build_dataset.py ..\..\server\scripts\forecast_data\data data\mock_v3` | คัดลอกผลมาที่ AI + join เป็น training_dataset.csv | หลังข้อ 2 |
| 4 | `AI/risk_forecaster` | `python train_forecaster.py` | เทรน + บันทึก `models/forecaster_v3.pkl` | ข้อมูลเปลี่ยน / ย้ายโฟลเดอร์ |
| 5 | `AI/risk_forecaster` | `python calibrate_risk.py` | เลือก cutoff → **เขียนทับ** `models/risk_thresholds.json` | หลังข้อ 4 (ถ้าตั้ง cutoff เองไว้ ห้ามรัน) |
| 6 | `AI/risk_forecaster` | `python data_checks\validate_mock_data.py` | ตรวจ 5 ข้อ | หลังข้อ 4-5 |
| 7 | `AI/risk_forecaster` | `python run_scan.py` | สแกนแบบ local (อ่าน CSV ไม่แตะ Supabase) | ทดสอบ / ปรับ cutoff |
| 8 | `server` | `python -m scripts.load_mock_data` | ลบข้อมูลเดิมใน Supabase แล้วโหลด daily_context / product_daily / inventory_lots ชุดใหม่ + snapshot ล็อต demo | หลังข้อ 2 (ใช้ venv ของ server) |
| 9 | `server` | `fastapi dev main.py` | เปิด API (`DEMO_DATE=2026-10-16` ใน `server/.env`) | ก่อนข้อ 10 |
| 10 | `AI/risk_forecaster` | `python run_scan.py --source api --dry-run` แล้ว `python run_scan.py --source api` | รอบจริง: อ่านจาก server, POST ผลลง Supabase | demo / ใช้งาน |
| 11 | Supabase SQL Editor | `select demo_reset();` | ล้างผลสแกน / งาน / decision คืนล็อต demo เป็นค่าตั้งต้น | ก่อน demo รอบใหม่ |

โหมด `api` อ่าน URL จาก `API_BASE_URL` (ค่าเริ่มต้น `https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1` = server บน AWS)
ใช้ server ในเครื่องแทน: `set API_BASE_URL=http://127.0.0.1:8000/api/v1`

ผลแต่ละรอบอยู่ใน `output/<วันที่>_<เวลา>_<โหมด>/`: `scan_inputs.json`, `risk_assessments_request.json`,
`risk_assessments_response.json` (โหมด api), `summary.csv`

## ส่งผลไปยังไง (รอบจริง โหมด api)

1. `GET /ai/scan-inputs?history_days=56` → ล็อต IDLE, สินค้า, ยอดขาย 56 วันล่าสุด, ปัจจัยรายวันวันนี้ถึง 7 วันข้างหน้า
2. `PATCH /inventory-lots/ai-status` → ทุกล็อตที่ได้มาเป็น `PROCESSING`
3. Forecaster → Risk Scanner → shelf curve (เฉพาะ HIGH / CRITICAL) → recipe_demand
4. `POST /risk-assessments` (ทุกล็อต) → server เรียก RPC `save_risk_run` บันทึก 4 ตารางใน transaction เดียว
   (`forecast_runs`, `lot_risk_assessments`, `lot_shelf_forecasts`, `recipe_demand_forecasts`) คืน `run_id`
5. `PATCH /inventory-lots/ai-status` → ล็อต LOW / MEDIUM กลับเป็น `IDLE` (พรุ่งนี้สแกนใหม่ เพราะความเสี่ยงเพิ่มเมื่อใกล้หมดอายุ)
   ล็อต HIGH / CRITICAL ค้าง `PROCESSING` ให้ Optimizer รับต่อ
6. Optimizer เรียก `GET /ai/optimize-inputs?run_id=...` ได้ `at_risk_lots` (HIGH / CRITICAL + `shelf`) และ `recipe_demand`

ถ้าพังระหว่างขั้น 3-4 ทุกล็อตถูกตั้งกลับเป็น `IDLE` อัตโนมัติ

## Forecaster (`forecaster/`)

ทำนาย**ความต้องการต่อวันที่ราคาเต็ม** (μ) ของแต่ละสินค้า ตั้งแต่วันนี้จนถึงวันหมดอายุของล็อต

- **ยอดสะอาด**: ไม่ใช้วันที่ของหมดชั้น (ยอดถูกตัด) และวันลดราคาทั้งวัน
  ยกเว้น RTE ที่ลดเฉพาะของเหลือช่วงค่ำ (`CLEARANCE_ONLY_CATEGORIES`)
- **feature**: สินค้า, หมวด, horizon (1-14 วัน), วันในสัปดาห์, วันหยุด, ก่อนหยุดยาว, ช่วงเงินเดือนออก, ฝน (ทั้งวัน / 16-20 น. / หนัก),
  อุณหภูมิ, อายุสินค้า, lag 7 / 28 / 56 วัน, EWM 7 วัน, ค่าเฉลี่ยวันเดียวกันในสัปดาห์
- **โมเดล**: same-dow (baseline) vs LightGBM Poisson 4 ชุด parameter (`LGBM_GRID`) เลือกบน validation ด้วย WAPE
- **แบ่งข้อมูลตามเวลา** (rolling origin, ห้ามสุ่ม): train ที่เหลือ / validation 20% / test 20% ล่าสุด (ข้อมูล 1 ปี ≈ 219 / 73 / 73 วัน)
  test ใช้วัดผลครั้งเดียว จากนั้นเทรนใหม่ด้วยข้อมูลทั้งหมดเป็นโมเดลใช้งานจริง
- **lift ของการลดราคา** 20 / 30 / 50%: จากวันที่ลดทั้งวัน เทียบกับยอดที่โมเดลคาด
- **phi_k** = variance / mean ของยอดรวม k วัน จาก residual บน validation ใช้กับ Negative Binomial

ผลล่าสุดดูที่ `models/forecaster_v3_metrics.json` (WAPE แยกโมเดล / horizon / หมวด, phi_k, lift)
และ `models/forecaster_v3_feature_importance.csv`

## Risk Scanner (`risk_scanner/risk.py`)

### สูตร

```
days_to_expiry   = expiration_date - reference_date
วันที่ยังขายได้     = days_to_expiry + 1                    (ขายได้ถึงสิ้นวันหมดอายุ: ประกาศ สธ. ฉบับ 367)
sellable_hours   = (days_to_expiry + 1) x 14 - ชั่วโมงที่ผ่านไปแล้ววันนี้      (ร้านเปิด 08:00-22:00)

ความต้องการรวม D  = Σ μ(สินค้า, วัน) ตั้งแต่วันนี้ถึงวันหมดอายุ                (จาก Forecaster)
แบ่ง D ให้แต่ละล็อตของสินค้าเดียวกัน ทีละวัน:
    40% ไปล็อตใหม่สุด (NEWEST_PICK_SHARE) ที่เหลือแบบ FIFO (หมดอายุก่อนได้ก่อน)
    ส่วนที่ล็อตไหนรับไม่ไหว (ของหมด) ไหลไปล็อตถัดไป
ขายได้ (got)      = min(จำนวนคงเหลือ, ความต้องการที่มาถึงล็อตนั้น)
เหลือ (leftover)  = จำนวนคงเหลือ - got

risk_score       = leftover / จำนวนคงเหลือ x 100        (= % ของล็อตที่คาดว่าจะเหลือทิ้ง, หมดอายุแล้ว = 100)
sell_through_probability = P(ความต้องการ >= จำนวนคงเหลือ)    Negative Binomial, mean = ความต้องการของล็อต,
                                                            variance = phi_k x mean (k = วันที่ยังขายได้)
```

**ตัวอย่าง** LOT-000001 นม DAI-001 คงเหลือ 150 ขวด หมดอายุอีก 2 วัน (ขายได้ 3 วัน) ความต้องการ ≈ 35 ขวด/วัน
→ D ≈ 105 แต่มีล็อตใหม่ของสินค้าเดียวกัน (LOT-000002) แบ่ง 40% ไป → ล็อตนี้ขายได้ ≈ 63
→ เหลือ ≈ 87 → **score ≈ 58** (คาดว่าทิ้ง 58% ของล็อต)

### ระดับ (`models/risk_thresholds.json`)

| ระดับ | เงื่อนไข (ตั้งไว้ตอนนี้) | ส่งต่อ Optimizer | หลังสแกน |
| --- | --- | --- | --- |
| CRITICAL | หมดอายุแล้ว หรือ score ≥ **80** | ส่ง | ค้าง PROCESSING |
| HIGH | score **60-79** | ส่ง | ค้าง PROCESSING |
| MEDIUM | score **40-59** | ไม่ส่ง | คืน IDLE สแกนใหม่พรุ่งนี้ |
| LOW | score < **40** | ไม่ส่ง | คืน IDLE สแกนใหม่พรุ่งนี้ |

`last_day_bump: true` = วันสุดท้าย (`days_to_expiry = 0`) และยังคาดว่าจะเหลือ → ขยับขึ้น 1 ระดับ
(ล็อตที่จะหมดอายุวันนี้ไม่ต้องรอถึงพรุ่งนี้)

- แก้ cutoff = แก้ไฟล์นี้แล้วรัน `run_scan.py` ใหม่ ไม่ต้องเทรนใหม่ ไม่กระทบ mock data
  (simulate.py ไม่อ่าน cutoff, score ไม่เปลี่ยน เปลี่ยนแค่ระดับที่ได้)
- `calibrate_risk.py` เขียนทับไฟล์นี้ด้วยชุดที่ macro-F1 สูงสุดบน validation (ลองทุกชุดจาก `CUTOFF_CANDIDATES` 0, 10, ..., 90
  ± last_day_bump) ถ้าตั้งเองให้ commit ไฟล์ไว้ ดูผลของแต่ละ HIGH cutoff ใน `forward_by_high_cutoff_test`
- ไม่มีไฟล์ → ใช้ `DEFAULT_THRESHOLDS` ใน `common/config.py` (30 / 50 / 80)
- ระดับที่ส่งต่อ: `FORWARD_LEVELS` ใน `common/config.py` และ `AT_RISK_LEVELS` ใน `server/routers/ai.py` (ต้องตรงกัน)

## ผลที่ส่งให้ Optimizer (`risk_scanner/handoff.py`)

- `shelf` (ต่อล็อต HIGH / CRITICAL ที่ยังไม่หมดอายุ): "ลด x% ตั้งแต่เปิดร้านวันนี้จนหมดอายุ" ที่ 0 / 20 / 30 / 50%
  (ข้ามระดับที่ต่ำกว่า `min_allowed_price` หรือสินค้าห้ามลด) ล็อตที่ลดราคาได้ลูกค้าก่อน ยอด x lift
  `expected_qty`, `low_qty` / `high_qty` (ยอดของล็อตเมื่อความต้องการของสินค้าอยู่ที่ P10 / P90 ของ NB แบ่งผ่านคิวเดียวกัน
  ล็อตท้ายคิวจึงไม่เป็น 0 ทั้งช่วง), `lost_sales_other_lots` (ล็อตอื่นของสินค้าเดียวกันขายได้น้อยลง)
- ล็อตหมดอายุ: `shelf = []` เหลือแค่ช่องทางกำจัด
- `recipe_demand` (ต่อสูตร active): ความต้องการเมนูในช่วงอายุเมนู - ของเมนูบนชั้น เรียงตามรายได้ที่คาด

## ข้อมูล

| ไฟล์ (`data/mock_v3/`) | 1 แถว = | ใช้ทำอะไร | เข้า Supabase |
| --- | --- | --- | --- |
| `product_daily.csv` | สินค้า x วัน (16 ต.ค. 68 - 15 ต.ค. 69) | เทรน | ✓ `product_daily` |
| `daily_context.csv` | วัน (+ พยากรณ์ 10 วัน) | เทรน / ทำนาย | ✓ `daily_context` |
| `inventory_lots_demo.csv` | ล็อต demo 13 ล็อต (วัน demo 16 ต.ค.) | สแกน | ✓ `inventory_lots` |
| `training_dataset.csv` | 3 ไฟล์บน join กัน + products | เทรน | ✗ |
| `lot_daily.csv` | ล็อต x วัน ของคงเหลือตอนเปิดร้าน | `calibrate_risk.py` | ✗ |
| `lot_outcomes.csv` | ล็อต: ขาย / เสียหาย / หมดอายุทิ้งจริง | score จริงสำหรับ calibrate | ✗ |

`data/reference/products.json`, `recipes.json` = snapshot จาก Supabase (scan-inputs ไม่ส่ง `allow_*`, ขนาดบรรจุ, สูตร)
ถ้าแก้สินค้า / สูตรใน Supabase ต้องอัปเดตไฟล์นี้ด้วย

## ฝั่ง server ที่งานนี้เพิ่ม / แก้

| ไฟล์ | อะไร |
| --- | --- |
| `server/routers/risk_assessments.py`, `server/schemas/risk_assessment.py` | `POST /risk-assessments` รับ `shelf`, `sellable_hours`, `recipe_demand`, `run_metrics` |
| `server/routers/ai.py`, `server/schemas/responses.py` | `GET /ai/optimize-inputs` คืน `shelf` + `recipe_demand`, ส่งเฉพาะ HIGH / CRITICAL |
| `server/scripts/forecast_tables.sql` | ตาราง `forecast_runs`, `lot_shelf_forecasts`, `recipe_demand_forecasts`, RPC `save_risk_run` (รันแล้ว) |
| `server/scripts/demo_functions.sql` | `demo_reset` ลบตาราง forecast ด้วย (รันแล้ว) |
| `server/scripts/forecast_data/fetch_weather.py`, `simulate.py` | สร้าง mock data 1 ปี |
| `server/scripts/load_mock_data.py` | โหลด mock data ขึ้น Supabase |

## ข้อควรระวัง

- `models/*.pkl` ไม่เข้า git: clone ใหม่ / ย้ายโฟลเดอร์ / แก้โค้ด Forecaster ต้องรัน `train_forecaster.py` ก่อน `run_scan.py`
- ยอดขายของเมนูครัวที่ไม่มีล็อต IDLE ไม่มาใน scan-inputs จึงใช้จาก `data/mock_v3/product_daily.csv` (โหมด api แจ้ง "อาจไม่อัปเดต")
- score แยกเป็น 2 กลุ่ม (ขายหมด = 0 / เหลือเยอะ = 40+) เพราะล็อต demo ออกแบบให้ชัด ถ้าอยากได้ช่วงกลาง ปรับจำนวนใน `TRACKED` ของ `simulate.py`
- ความต้องการรายวันคิดเต็มวัน (sellable_hours เป็นข้อมูลให้ Optimizer ยังไม่หักชั่วโมงที่ผ่านไปออกจาก score)
