# Food-waste Optimizer (No-Waste-Bro)
---

## เริ่มใช้งานเร็ว

### ติดตั้ง

```bash
cd AI/food_waste_optimizer
pip install -r requirements.txt          # numpy + scipy (ต้อง scipy >= 1.9 ที่มี milp / HiGHS)
```

ในเครื่องทีมใช้ `server/.venv` ได้เลย (มี numpy 2.5 / scipy 1.18 / lightgbm ครบ ใช้รัน backtest ได้ด้วย)
บน Lambda ใช้ Python 3.12 + เวอร์ชันที่ล็อกใน `AI/pipeline/requirements.txt`

### รันเทสต์ (ไม่ต่อเน็ต ไม่แตะ DB)

```bash
python -m unittest discover -s ai_engine/tests -t .          # 64 เทสต์ ~1 นาที
python -m unittest ai_engine.tests.test_optimizer.Rolling -v # รันทีละกลุ่ม
```

### รัน Optimizer 1 รอบ (`run_optimize.py`)

| คำสั่ง | ทำอะไร | เขียน DB? |
| --- | --- | --- |
| `python run_optimize.py --dry-run` | GET ข้อมูลจริง → คำนวณ → พิมพ์รายงาน | ไม่ |
| `python run_optimize.py` | GET → คำนวณ → POST decision + คืน lot ที่ไม่ต้องทำอะไรเป็น IDLE | **เขียน** |
| `python run_optimize.py --run-id <uuid>` | ระบุรอบสแกนเอง (ไม่ใส่ = `suggested_run_id` ของ `GET /ai/optimize-runs`) | ตาม `--dry-run` |
| `python run_optimize.py --via-server [--dry-run]` | ให้ server รันเอง (`POST /ai/optimize`) | ตาม `--dry-run` |
| `python run_optimize.py --input output/<รอบ>/optimize_inputs.json` | รันซ้ำจากข้อมูลจริงที่บันทึกไว้ (ไม่ต่อ server) | ไม่ |
| `--days-ahead N` | วางแผนครัวตั้งแต่วันนี้ถึง N วันข้างหน้า (ค่าเริ่มต้น 1) | – |

- URL ของ server: env `API_BASE_URL` (ค่าเริ่มต้น `https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1` = Lambda บน AWS)
  ถ้ารัน server ในเครื่อง (`fastapi dev main.py` ในโฟลเดอร์ `server`) ตั้ง `API_BASE_URL=http://127.0.0.1:8000/api/v1`
- **โค้ดบน AWS อาจเก่ากว่าในเครื่อง** (ต้อง build image ใหม่ ดู `AI/pipeline/README.md`) ทดสอบ logic ใหม่ให้ชี้ไป server ในเครื่อง
- exit code: `0` สำเร็จ · `1` server error / ต่อ server ไม่ได้ · `2` แผนไม่ผ่านกฎตรวจ (ไม่บันทึกอะไร) ·
  `3` ไม่มีรอบสแกนที่พร้อมตัดสินใจ (วันที่สแกนไม่ตรง `DEMO_DATE` ของ server) — pipeline worker ใช้ code เหล่านี้
- ผลทุกรอบเก็บที่ `output/<วันที่>_<เวลา>_<โหมด>/` (env `OUTPUT_DIR` เปลี่ยนที่เก็บได้ บน Lambda ใช้ `/tmp`)

| ไฟล์ใน output | เนื้อหา |
| --- | --- |
| `optimize_inputs.json` | ข้อมูลที่ GET มา (ใช้กับ `--input` รันซ้ำได้) |
| `products.json` | `GET /products` (flag การกำจัดของสินค้า) |
| `plan.json` | แผนเต็ม: ต่อ lot / เที่ยวรถ / ถัง partner / งานครัว / baseline / คำเตือน |
| `decisions_request.json` | body ที่ POST ไป `/optimization-decisions` |
| `decisions_response.json` | สิ่งที่ server ตอบกลับ (มีเฉพาะรอบที่บันทึก) |
| `allocations.json` | kg / % / เงิน ต่อส่วนของ lot (ไม่เขียนลงตาราง ส่งให้ส่วนอื่นใช้) |
| `report.txt` | รายงานอ่านง่าย (ตัวเดียวกับที่พิมพ์บนจอ) |

### เรียกจากโค้ด Python

```python
from ai_engine.optimizer import run_optimizer, optimize_and_post, OptimizerConfig, ApiClient

# 1) มีข้อมูลอยู่แล้ว -> คำนวณอย่างเดียว ไม่แตะเน็ต/DB
result = run_optimizer(optimize_inputs_json, products_catalog=products_json)
result["plan"]             # แผนเต็ม (ดูหัวข้อ 4)
result["payload"]          # body ของ POST /optimization-decisions
result["allocations"]      # รายละเอียดต่อส่วนของ lot
result["lots_to_release"]  # lot ที่ควรคืนเป็น IDLE

# ปรับค่า / เวลาที่ใช้คิด
from datetime import datetime
from ai_engine.optimizer.config import BKK
result = run_optimizer(inputs, products_catalog=products,
                       now=datetime(2026, 10, 16, 9, 0, tzinfo=BKK),     # ไม่ส่ง = reference_date + เวลาไทยตอนนี้
                       cfg=OptimizerConfig(max_hold_days=3),
                       strict=False,          # True (ค่าเริ่มต้น) = แผนหลุดกฎ -> raise PlanValidationError
                       with_baselines=False)  # ไม่คำนวณ baseline เปรียบเทียบ (เร็วขึ้น ~3 เท่า)

# 2) อ่านข้อมูลจริงผ่าน server -> คำนวณ -> (dry_run=False) บันทึก
optimize_and_post(ApiClient(), run_id=None, dry_run=True)
```


### รายละเอียดทีละไฟล์

| ไฟล์ | ฟังก์ชัน / class หลัก | หน้าที่ |
| --- | --- | --- |
| `run_optimize.py` | `main()`, `format_report()`, `run_local_file()` | CLI ของรอบ Optimizer: เลือกรอบสแกน → `optimize_and_post` → เขียนไฟล์ใน `output/` → พิมพ์รายงาน |
| `config.py` | `OptimizerConfig`, `simulated_now()`, `ACTION_BY_METHOD`, `BKK` | ค่าที่ปรับได้ทั้งหมด (หัวข้อ 6) เวลาที่ใช้คิด = `reference_date` ของ server + เวลานาฬิกาไทยตอนรัน |
| `models.py` | `Inputs.from_json()`, `Lot`, `Product`, `Partner`, `Recipe`, `ShelfRow`, `StockLot` | อ่าน JSON ตามชื่อ field ของ Swagger/Supabase; แปลง G/ML (KG, L × 1000); เติม flag การกำจัดจาก `GET /products`; อ่าน `waste_history` + `partner_bins` |
| `demand.py` | `lot_curve()`, `survival_segments()`, `expected_sold()`, `menu_segments()`, `remaining_fraction()` | แปลง P10/P50/P90 เป็นช่วงที่แต่ละหน่วยบนชั้นมีโอกาสขายออก, หักชั่วโมงขายที่ผ่านไปแล้วถ้ารันสาย |
| `rules.py` | `lot_skip_reasons`, `markdown_tiers`, `partner_reasons`, `next_pickup`, `eol_pickup`, `bin_pickup`, `calls_per_week`, `partner_trip_cost`, `sell_end`, `kitchen_*` | กฎล้วน (ไม่แตะ DB/solver) ทุกกฎคืน "รหัสเหตุผล" ให้ RAG อธิบายได้ |
| `context.py` | `build_context()`, `PartnerCtx`, `LotCtx`, `_partner_mode()`, `_lost_sales_disposal()`, `_build_kitchen()` | ประกอบทุกอย่างก่อนเข้า solver: ทางเลือกต่อ lot (ราคา, partner ตอนนี้ / หลังหมดเวลาขาย), โหมด BIN/DEDICATED ของ partner, งานครัว + FEFO |
| `solver.py` | `solve()`, `Switches`, `Solution` | MILP: ตัวแปร shelf / tier / segment / y / ym / x / z / w / งานครัว / FEFO (รายละเอียดใน docstring ต้นไฟล์) `Switches` ใช้ปิดบางทางเพื่อคำนวณ baseline |
| `plan.py` | `build_plan()`, `compute_baselines()`, `_provisional_lots()`, `_partner_bins()`, `_trips()` | ผล solver → portion ต่อ lot (หน่วยเต็ม + เงินค่าคาดหมาย), เที่ยวรถ, สถานะถัง partner, งานครัว, สรุป, เทียบ baseline, คำเตือน |
| `validate.py` | `validate_plan()`, `fefo_simulation()` | ตรวจแผนซ้ำจากข้อมูลดิบ H1-H7 (หัวข้อ 7) หลุดข้อไหน = ไม่บันทึก |
| `decisions.py` | `build_decisions()`, `validate_payload()` | แผน → decision ตามคอลัมน์ `optimization_decisions` + `alternatives` (ทางเลือกอื่น + ทางที่ถูกตัดพร้อมเหตุผล) + `allocations` |
| `io.py` | `ApiClient`, `pick_run()`, `load_from_api()` | เรียก route ของ server; `ApiClient(transport=...)` ใส่ transport ปลอมตอนเทสต์ได้ |
| `pipeline.py` | `run_optimizer()`, `optimize_and_post()`, `lots_to_release()`, `check_scan_date()`, `attach_decision_ids()` | ทางเข้าหลัก ลำดับ: H0 → context → solve → plan → validate → decisions |

ลำดับการทำงานใน `run_optimizer()`:

```
Inputs.from_json → check_scan_date (H0) → build_context → solve → build_plan (+ compute_baselines)
                 → validate_plan (H1-H7) → build_decisions → validate_payload → lots_to_release
```

---

## ข้อมูลเข้า / ข้อมูลออก

### ข้อมูลเข้า: `GET /api/v1/ai/optimize-inputs?run_id=...&days_ahead=1&waste_history_days=28`

| ส่วน | มาจาก | ใช้ทำอะไร |
| --- | --- | --- |
| `reference_date`, `run_id` | server (`DEMO_DATE` หรือวันนี้) | วันที่ใช้คิด (ต้องตรงกับวันที่สแกน ดู H0) |
| `at_risk_lots[]` | `lot_risk_assessments` (HIGH / CRITICAL) + `lot` (`inventory_lots`) + `shelf` (`lot_shelf_forecasts`) | lot ที่ต้องตัดสินใจ; `shelf` = ยอดขายที่ลด 0/20/30/50% (expected / low=P10 / high=P90 / `lost_sales_other_lots`) |
| `recipe_demand[]` | `recipe_demand_forecasts` | ความต้องการเมนูครัว (`menu_qty` / `low_qty` / `high_qty`) |
| `products[]`, `recipes[]` | `products`, `recipes` + ingredients | ราคา ต้นทุน น้ำหนักสุทธิ flag อนุญาต / สูตร |
| `kitchen_capacity[]` | `kitchen_capacity` | ชั่วโมงครัวที่เหลือต่อแผนกต่อวัน |
| `donation_partners[]` | `donation_partners` | ค่าเที่ยว (fixed + travel) handling buyback ขั้นต่ำ/ความจุ วัน-เวลารับ หมวดที่รับ อายุขั้นต่ำ |
| `ingredient_stock[]` | `inventory_lots` ของวัตถุดิบ | สต็อกวัตถุดิบรองของครัว (ตัดแบบ FEFO) |
| `waste_history` | `product_daily.waste_qty` ย้อนหลัง 28 วัน | ของทิ้ง kg/วัน แยกหมวด → ปริมาณที่คุ้มต่อเที่ยวรถ partner |
| `partner_bins[]` | decision ที่มี `target_partner_id` ที่ task ยังไม่เสร็จ | ของที่รอ partner อยู่แล้ว (`open_kg`, `oldest_at`) |

`GET /products` ใช้เติม `allow_animal_feed / allow_composting / allow_anaerobic_digestion / allow_landfill`
(optimize-inputs ไม่ได้ส่งมา) ไม่มี flag = ไม่อนุญาต (`missing_flag_policy="deny"`)

### ข้อมูลออก: `run_optimizer()` คืน dict

| key | เนื้อหา |
| --- | --- |
| `plan` | `lots[]` (ต่อ lot: `portions[]` แต่ละวิธี หน่วย % kg เงิน + `explain` เหตุผล), `trips[]` (เที่ยวรถ), `partner_bins[]` (ถัง partner: ควรเรียกรถเมื่อไร), `kitchen_jobs[]`, `kitchen_usage`, `summary` (สัดส่วนรวม เงินรวม `reconciliation_ok`), `baselines`, `warnings`, `skipped_lots`, `solver` |
| `payload` | `{"optimizer_version", "decisions": [...]}` → `POST /optimization-decisions` |
| `allocations` | ต่อส่วนของ lot: `units`, `share_pct`, `weight_kg`, `revenue_thb`, `cost_thb`, `cogs_thb`, `net_profit_thb`, `decision_index` (→ `decision_id` หลังบันทึก) |
| `lots_to_release` | lot ที่ไม่ต้องทำอะไรรอบนี้ → `PATCH /inventory-lots/ai-status` เป็น `IDLE` ให้สแกนใหม่พรุ่งนี้ |
| `violations`, `payload_errors` | ผลตรวจ H1-H7 / ตรวจแบบ server (ว่าง = ผ่าน) |

ช่องของ decision: `assessment_id, action_type, action_quantity, discount_pct, new_recommended_price, target_recipe_id,
batch_count, target_partner_id, due_by, expected_profit_impact, decision_score, alternatives`

`action_type` (โหมด `extended`): `MARKDOWN`, `KITCHEN_REPURPOSE`, `DONATE`, `ANIMAL_FEED`, `COMPOST`,
`ANAEROBIC_DIGESTION`, `LANDFILL`, `DISCARD` (ไม่มี partner รับ ทิ้งเองในร้าน)

`plan.baselines` เทียบกับการไม่ใช้ Optimizer (ใช้โมเดลยอดขายเดียวกัน):
`do_nothing_no_disposal_cost`, `regular_price_then_landfill`, `markdown_then_landfill`, `optimized`,
`improvement_vs_regular_then_landfill_thb`

---

## หลักการตัดสินใจ (business logic)

### เป้าหมาย = กำไรสุทธิสูงสุดของ lot เสี่ยงทั้งหมด

- ทุกหน่วยของ lot ถูกนับต้นทุนสินค้า (`unit_cost`) ครั้งเดียวในทางที่มันไป ทุกทางจึงเทียบกันตรง ๆ ได้
- `net_profit = revenue − cost − cogs` ต่อ portion
  - revenue = ขายหน้าร้าน | ส่วนแบ่งรายได้เมนู | buyback × kg (อาหารสัตว์)
  - cost = ค่าเที่ยว + handling × kg | ค่าไฟน้ำ+วัตถุดิบรองของครัว | เงินที่ล็อตอื่นเสียเพราะลดราคา
- หน่วยที่ไม่มีทางไปเลย (`res`) ถูกปรับ 10,000 บาท/หน่วย บังคับให้หาทางก่อนเสมอ

### ยอดขายแบบความน่าจะเป็น (newsvendor) — `demand.py`

- ใช้ quantile ของ forecaster ตรง ๆ: `low_qty` = P10, `expected_qty` = P50, `high_qty` = P90
- P(ความต้องการ ≥ k) ลากเส้นตรงผ่าน (0, 1) (P10, 0.9) (P50, 0.5) (P90, 0.1) (P90 + (P90 − P50), 0)
  → หน่วยที่วางบนชั้นแต่ละช่วงขายออกด้วยโอกาสเฉลี่ย ≈ 0.95 / 0.7 / 0.3 / 0.05 (หน่วยเกินหาง = 0)
- ส่วนที่คาดว่าขายไม่หมด (1 − p) ไปทางกำจัด "หลังหมดเวลาขาย" (END_OF_LIFE) solver จึงชั่งเองว่า
  วางขายต่อคุ้มกว่าดึงออกตอนนี้ไหม
- รันสาย: ยอดขาย × ชั่วโมงร้านเปิดที่เหลือ / ชั่วโมงทั้งช่วง (ร้านเปิด 08:00-22:00)
- lot ขายได้ถึง **ร้านปิดของวันหมดอายุ** (`sell_end`) หมดอายุ 23:59:59 ของ `expiration_date`

### ลดราคา (MARKDOWN)

- 1 lot 1 ราคา ระดับที่เลือกได้ = ระดับที่ forecaster พยากรณ์มา (ตอนนี้ 20/30/50%) ที่ราคาไม่ต่ำกว่า `min_allowed_price`
- **ติดป้ายทุกชิ้นที่วางบนชั้น** (`action_quantity` = ทุกหน่วยบนชั้นที่ราคานั้น ไม่ใช่แค่ยอดที่คาดว่าขายได้)
- เมื่อ task ลดราคาเสร็จ server แยกหน่วยที่ติดป้ายเป็น lot ใหม่ (`MARKDOWN_SPLIT`) สถานะ `IDLE`
  → ของที่ขายไม่หมดถูกสแกน/วางแผนกำจัดใหม่ **รอบถัดไปด้วยจำนวนจริง** รอบนี้ไม่ออก decision กำจัดให้
  (ค่าประมาณอยู่ใน `alternatives[0]` `handled_by = NEXT_RUN` และ `ym` ใน solver)
- **ต้นทุนที่ล็อตอื่นเสีย (cannibalization)**: ลดราคา lot นี้แล้ว lot อื่นของสินค้าเดียวกันขายได้น้อยลง
  `lost_sales_other_lots` หน่วย (Risk Scanner คำนวณ) คิดเป็น
  `lost × (regular_price + ค่ากำจัดต่อหน่วยของทาง end-of-life ที่ถูกสุด) × lost_sales_factor`
  เพราะของ lot อื่นซื้อมาแล้ว (ต้นทุนจม) ขายไม่ออก 1 หน่วย = เสียรายได้เต็มราคา + ต้องจ่ายค่ากำจัดหน่วยนั้นเพิ่ม
- ราคาปกติ (tier 0%) ไม่ถูกตัดทิ้งแม้คาดว่าขายได้ 0 ตราบที่ยังมีเวลาขาย (กฎ K5) วางขายต่อไม่มีต้นทุนเพิ่ม

### Rolling horizon: แผนชั่วคราว (provisional) และการคืน lot เป็น IDLE

- lot ที่ **ขายราคาปกติ + หมดอายุวันอื่น + ของที่คาดว่าเหลือไปถังของ partner โหมด BIN เท่านั้น + ไม่มี decision อื่น**
  = แผนชั่วคราว ไม่ออก decision รอบนี้ lot ถูกคืน `IDLE` (`lots_to_release`) ให้รอบสแกนพรุ่งนี้ตัดสินใจใหม่ด้วยจำนวนจริง
  (เช่น พรุ่งนี้อาจบริจาคได้ขณะยังเข้าเกณฑ์อายุ)
- กันบั๊กเดิม "เที่ยวฟรี": ค่ากำจัดต่อ kg ของแผนชั่วคราวเท่ากับของ decision จริง (ใช้ `fee_per_kg` เดียวกัน)
  และ lot ที่อยู่ในเที่ยวเต็ม (full call) หรือมี decision อื่น (ลดราคา/ครัว/ดึงออก) ต้องออก decision รอบนี้ (กฎ H7)
- lot ที่หมดอายุวันนี้ = ไม่มีรอบสแกนก่อนกำจัด → ออก decision END_OF_LIFE รอบนี้ (`due_by` = เวลารับหลังหมดเวลาขาย,
  `action_quantity` = จำนวนที่คาดว่าเหลือ ปัดขึ้น พนักงานกำจัดตามที่เหลือจริง)

###  Partner (on-call) โหมด BIN / DEDICATED — `context._partner_mode`

partner ทุกรายเป็นแบบเรียกรถ ทุกครั้งที่เรียกจ่าย `fixed_cost_per_trip + travel_cost_per_trip` เต็ม
(บริจาคคิดแค่ fixed) + `handling_fee_per_kg` × kg − `buyback_price_per_kg` × kg

| โหมด | เมื่อไร | คิดค่าเที่ยวอย่างไร |
| --- | --- | --- |
| **BIN** (สะสมในถัง) | ปริมาณที่คุ้มต่อเที่ยว ≥ `min_kg_per_pickup` | เฉลี่ยต่อ kg: `fee_per_kg = ค่าเรียกรถ / economic_call_kg` |
| **DEDICATED** (เรียกเฉพาะ) | ปริมาณที่คุ้ม < ขั้นต่ำ หรือไม่มีประวัติของทิ้ง หรือไม่มีตารางรับ | จ่ายเต็มต่อเที่ยว (ตัวแปร `z`) และของรอบนี้ต้องถึงขั้นต่ำ (P7/H4) |

ปริมาณที่คุ้มที่สุดภายในเพดานเวลา:

```
calls_per_week   = จำนวนวันเรียกรถน้อยสุดต่อสัปดาห์ (เลือกจากวันที่ partner มารับ) ที่ช่องว่างระหว่างครั้ง
                   ≤ max(max_hold_days, ช่องว่างของตารางรับเอง)          (rules.calls_per_week)
economic_call_kg = min(ความจุต่อเที่ยว, ของทิ้ง kg/วันของหมวดที่ partner รับ × 7 / calls_per_week)
fee_per_kg       = ค่าเรียกรถ / economic_call_kg
cost_per_kg      = fee_per_kg + handling − buyback
```

- เวลารับของที่ดึงออกตอนนี้ (BIN) = รอบรับหลังถังน่าจะถึงปริมาณที่คุ้ม (นับของในถังอยู่แล้วจาก `partner_bins`)
  แต่ไม่เกินเพดานเวลา (`max_wait_days`) ถ้าเกินใช้รอบสุดท้ายก่อนเพดาน (`rules.bin_pickup`)
- ของ END_OF_LIFE เข้าถังหลังหมดเวลาขาย รอเต็ม 1 รอบ (ไม่รู้ว่าถังมีเท่าไรตอนนั้น)
- **เพดานเที่ยวเต็ม (full call, วิธี ก)**: ของที่ขายไม่ได้แล้วก้อนใหญ่ (ดึงออกจาก lot ที่ไม่มีราคาขาย + ของเหลือ y/ym)
  ต่อ (partner, วันรับ) จ่าย `min(fee_per_kg × kg, ค่าเรียกรถ 1 ครั้ง)` ไม่ใช่คิดต่อ kg ซ้ำหลายสิบเที่ยว
  (ตัวแปร `w` + `full_kg` ใน `solver._full_call_cap`) ของที่ยังขายได้แต่ดึงออกตอนนี้ไม่เข้าเพดานนี้ (กันของดีติดรถไปฟรี)
- เกินความจุไม่ผิดกฎ: จ่ายค่าเที่ยวครั้งเดียว รอบขนเพิ่มของเที่ยวเดียวกันไม่มีค่าเที่ยว (`trips[].rounds`)
- `plan.partner_bins[]` บอกพนักงาน/ผู้จัดการว่าถังแต่ละ partner ควรเรียกรถเมื่อไร:
  `call_now`, `expected_call_at`, `must_call_by`, `call_reason` =
  `ECONOMIC_SIZE` (ถึงปริมาณที่คุ้ม) / `HOLD_LIMIT` (ใกล้เพดานเวลา) / `OVERDUE` (เกินเพดานแล้ว) / `THIS_RUN`

ข้อมูล partner ปัจจุบันใน Supabase (22 ต.ค. 2026):

| partner | ประเภท | fixed + travel (บาท/ครั้ง) | handling/kg | buyback/kg | ขั้นต่ำ / ความจุ kg | วันรับ (1=จ) เวลา |
| --- | --- | --- | --- | --- | --- | --- |
| P-ADG-01 | ก๊าซชีวภาพ | 1,750 + 100.64 | 0.90 | – | 5 / 60 | 1-7, 07-10 |
| P-ANI-01 | อาหารสัตว์ | 1,000 + 37.74 | 0.30 | 0.92 | 5 / 90 | 2,3,4,6, 16-18 |
| P-CMP-01 | ปุ๋ยหมัก | 1,600 + 53.465 | 0.60 | – | 4 / 90 | 1,2,4,6, 13-16 |
| P-DON-01 | บริจาค | 550 | – | – | 4 / 50 | 1,3,5,6,7, 09-11 (อายุเหลือ ≥ 2 วัน) |
| P-LDF-01 | ฝังกลบ | 650 + 78.625 | 1.15 | – | 1 / 90 | 1-6, 20-22 |

### ครัว (KITCHEN_REPURPOSE) — `context._build_kitchen`

- 1 งาน (สูตร, วัน, lot หลัก) = 1 decision; `batch_count` ใช้จองชั่วโมงครัวตอนผู้จัดการอนุมัติ
- ต้นทุน = Cost_Primary (หน่วย × `unit_cost` ของ lot หลัก) + `utility_cost` (ไฟ + น้ำ + วัตถุดิบรอง)
- เวลา: เริ่ม = ตอนนี้ + 30 นาที (วันอื่น = เปิดร้าน), เมนูเริ่มขายเมื่อ batch แรกเสร็จ,
  `due_by` = เริ่ม + เวลาทำ × batch ต้องไม่เกินเลิกกะ (17:00) และไม่เกินเวลาหมดอายุของ lot หลัก
- ยอดขายเมนูใช้ P10/P50/P90 จาก `recipe_demand` แบบเดียวกับหน้าร้าน เมนูที่ขายไม่ออกไม่มีรายได้
- วัตถุดิบรอง: DB ตัดเองแบบ FEFO (หมดอายุก่อนตัดก่อน) ตอนงานเสร็จ Optimizer จำลอง FEFO เอง (ตัวแปร `c, u, g`)
  และนับว่า lot เสี่ยงที่ถูก FEFO ตัดไปก็ถูกใช้ด้วย (lot เหล่านั้นไม่มี decision ของตัวเอง แต่มีใน allocations `covered_by_decision_index`)

### การส่ง decision

- ขายราคาปกติ ไม่มี decision
- `decision_score` = สัดส่วนต้นทุนที่กู้คืนได้ (0-1) = 1 + `expected_profit_impact` / ต้นทุนสินค้า
- `alternatives` = ทางเลือกอื่นของหน่วยเดียวกันพร้อมกำไร + ทางที่ถูกตัดพร้อมรหัสเหตุผล (ให้ RAG อธิบาย "ทำไมไม่ ...")

---

## รหัสเหตุผล / คำเตือน / กฎตรวจ

รหัสเหล่านี้ไปอยู่ใน `plan.lots[].explain`, `plan.warnings`, `alternatives` ของ decision (RAG ใช้อธิบาย)
`llm-task-agent/facts.py` แปลเป็นภาษาคนโดยจับจากชื่อหลังรหัส (เช่น `..._NO_SALES_EXPECTED`, `..._BELOW_MIN_KG`)
**ตั้งชื่อเหตุผลใหม่ อย่าลืมเพิ่มคำแปลใน `facts.py`**

| กลุ่ม | รหัส | ความหมาย |
| --- | --- | --- |
| ข้าม lot | `A0_STATUS_<s>`, `A0_ALREADY_DECIDED`, `A0_NO_STOCK`, `A0_UNKNOWN_PRODUCT` | ไม่ใช่ PROCESSING / มี decision แล้ว / ของหมด / ไม่รู้จักสินค้า |
| ข้อมูลเก่า | `A1_STALE_QTY/EXPIRY/...` | จำนวน/วันหมดอายุเปลี่ยนหลังสแกน (เตือน ใช้ค่าปัจจุบัน) |
| ลดราคา | `K0`-`K6` | หมดอายุ / ห้ามลด / ต่ำกว่าราคาต่ำสุด / ไม่อยู่ในนโยบาย / ราคาเปลี่ยน / ไม่มีเวลาขายหรือลดแล้วขายไม่ได้ / ลดมากขึ้นแต่ไม่ขายเพิ่ม |
| partner | `P1`-`P8` | flag สินค้า / ไม่รับหมวด / ไม่มีรอบรับ / อายุไม่พอ ณ วันรับ / ของหมดอายุห้ามบริจาค / ความจุ / ไม่ถึงขั้นต่ำ (DEDICATED) / ไม่มีน้ำหนัก |
| ครัว | `U0`-`U8` | สูตรไม่ active / ไม่มีแผนก / สินค้าห้ามเข้าครัว / ชั่วโมงไม่พอ / หมดอายุก่อนเสร็จ / ไม่มีคนซื้อเมนู / หน่วยไม่ตรง / ไม่รู้จักผลผลิต / วัตถุดิบไม่พอ |
| คำเตือนแผน | `A2_UNRESOLVED`, `A2_EOL_NO_ROUTE(_NEXT_RUN)` | มีหน่วยไม่มีทางไป / ของเหลือไม่มี partner รับ |
| | `A3_TRIP_COST_PER_KG` | ค่าเที่ยวต่อ kg สูงเกินเกณฑ์ |
| | `A4_SOLVER_NOT_OPTIMAL` | solver หมดเวลาก่อนได้คำตอบที่ดีที่สุด |
| | `A5_CALL_PARTNER` | ถัง partner ถึงเวลาเรียกรถแล้ว / คาดว่าถึงก่อนรอบรับนี้ |
| | `A6_BIN_BELOW_MIN_KG` | ต้องเรียกรถ (ใกล้เพดานเวลา) ทั้งที่ถังยังไม่ถึงขั้นต่ำ |
| คำเตือน context | `W0_DISPOSAL_FLAGS_MISSING` | ไม่มี flag การกำจัดของสินค้า (ไม่ได้ส่ง products) |
| | `W1_KITCHEN_NEAR_FULL` | ครัวใช้เกิน 90% |
| | `W2_PARTNER_DEDICATED` | partner ต้องเรียกรถเฉพาะ (ของไม่ถึงขั้นต่ำภายในเพดานเวลา) |
| | `W3_PICKUP_GAP_OVER_HOLD` | ตารางรับห่างกว่า `max_hold_days` |
| | `T1_NOW_NOT_REFERENCE_DATE` | เวลาที่ใช้คิดไม่ใช่วันเดียวกับ reference_date |

กฎตรวจแผน (หลุดข้อไหน = ไม่บันทึก exit code 2):

| รหัส | ตรวจอะไร |
| --- | --- |
| `H0_SCAN_DATE_MISMATCH` | วันที่สแกน (วันหมดอายุ − days_to_expiry) ต้องเท่ากับ `reference_date` ของ server (`pipeline.check_scan_date`) |
| `H1` | ทุกหน่วยของทุก lot มีทางไปครบ ไม่ติดลบ |
| `H2` | ไม่ใช้วิธีที่สินค้าไม่อนุญาต / partner ไม่รับหมวด |
| `H3` | ลดราคา: ราคาเดียวต่อ lot, ไม่ต่ำกว่าราคาต่ำสุด, ไม่ขายเกินยอดที่คาด, ไม่ขายของหมดอายุ |
| `H4` | partner: วัน-เวลารับ, อายุคงเหลือ, ขั้นต่ำต่อเที่ยว (DEDICATED), END_OF_LIFE ต้องรับหลังหมดเวลาขาย |
| `H5` | ครัว: ชั่วโมง, lot หลักพอ, เสร็จก่อนหมดอายุ, อยู่ในกะ, ไม่ผลิตเกินความต้องการเมนู |
| `H6` | จำลองการตัดสต็อก FEFO ของ DB แล้วต้องตรงกับแผน และสต็อกต้องพอ |
| `H7` | แผนชั่วคราวได้เฉพาะ lot ที่ไม่มี decision อื่น |

---

## การเชื่อมกับส่วนอื่นของระบบ

| ที่ | ไฟล์ | เกี่ยวกับ Optimizer อย่างไร |
| --- | --- | --- |
| server route | `server/routers/ai.py` | `GET /ai/optimize-inputs` (รวม `waste_history`, `partner_bins` ใหม่), `WASTE_HISTORY_DAYS = 28` |
| server route | `server/routers/optimizer.py` | `POST /ai/optimize` (server รัน Optimizer เอง), `GET /ai/optimize-runs` (รอบที่พร้อมตัดสินใจ) |
| server service | `server/services/optimizer.py` | `load_engine()` import โค้ดจากโฟลเดอร์นี้ (env `OPTIMIZER_PATH` เปลี่ยนที่ได้) ต้องมี numpy + scipy ใน venv ของ server |
| server schema | `server/schemas/responses.py` | `WasteHistory`, `PartnerBin` ของ optimize-inputs |
| server task | `server/services/task_actions.py` | task ลดราคาเสร็จ → lot `MARKDOWN_SPLIT` เป็น `IDLE` (`_release_markdown_split`) |
| pipeline | `AI/pipeline/worker.py`, `Dockerfile` | ขั้น OPTIMIZE: `python run_optimize.py --run-id <id>` timeout 150 วินาที, อ่าน exit code |
| Risk Scanner | `AI/risk_forecaster/risk_scanner/handoff.py` | สร้าง `shelf` (expected / P10 / P90 / `lost_sales_other_lots`) ที่ Optimizer ใช้ |
| LLM Task Agent | `AI/llm-task-agent/` | อ่าน decision ไปสร้างงาน; `facts.py` แปลรหัสเหตุผลเป็นภาษาคน |
| Backtest | `AI/backtest/run_backtest.py` | เรียก `run_optimizer` ทุกวันในร้านจำลองเพื่อวัดผล (หัวข้อ 10) |

เวลา: server ใช้ `DEMO_DATE` (ใน `.env` หรือ env) เป็น "วันนี้" ส่วน Optimizer ใช้ `reference_date` ที่ server ส่งมา
+ เวลานาฬิกาไทยตอนรัน (ไม่มี `DEMO_TIME` แล้ว) ดู `server/core/dates.py` และ `config.simulated_now`

---

## เทสต์

`ai_engine/tests/test_optimizer.py` 64 เทสต์ ใช้ข้อมูลจริงจาก fixture (ไม่ต่อเน็ต) เทสต์ที่ต้องการกรณีที่ข้อมูลจริงไม่มี
จะแก้สำเนาของ fixture ในเทสต์เอง (ฟังก์ชัน `forward()` / `shelf_rows()`)

| กลุ่ม | ทดสอบอะไร |
| --- | --- |
| `Units` | แปลงหน่วย, ปัดราคา, เวลาที่ใช้คิด, สัดส่วนชั่วโมงขาย |
| `Rules` | ระดับราคา, ของหมดอายุ, วัน-เวลารับ, ค่าเที่ยว, กฎ partner, flag หาย, **K5 เก็บราคาปกติไว้**, **ต้นทุน lost sales เต็มราคา + ค่ากำจัด** |
| `RealDataPlan` | แผนจากข้อมูลจริงผ่านกฎ / ทุกหน่วยมีทางไป / ดีกว่า baseline / payload ตรงคอลัมน์ |
| `TimeOfDay` | รันทุกชั่วโมงของวันแล้วผ่านกฎ |
| `Lifecycle` | รันซ้ำไม่บันทึกซ้ำ, ข้าม lot CHECKED, H0, validator จับแผนปลอม |
| `TestOnlyScenarios` | บริจาคชนะเมื่อถูกกว่า, FEFO ของครัว |
| `Io` | ApiClient (transport ปลอม): dry-run ไม่เขียน, รันจริง POST แล้วผูก decision_id |
| `NewsvendorDemand` | ช่วงโอกาสขายจาก P10/P50/P90 |
| `EndOfLifePickup` | รอบรับหลังหมดเวลาขาย, รวมเที่ยววันเดียวกัน |
| `TripCost` | ค่าเที่ยวตามโหมด, เกินความจุจ่ายครั้งเดียว |
| `PartnerBins` | calls_per_week, ปริมาณที่คุ้ม, เพดานเวลา, ถังเต็มเรียกรถ, full call, ของดีไม่ติดรถฟรี, solver ไม่พัง |
| `Rolling` | แผนชั่วคราว / คืน IDLE / decision ของ lot ที่หมดอายุคืนนี้ / ค่า kg เท่ากัน / ไม่มีเที่ยวฟรี |
| `MarkdownWholeShelf` | ติดป้ายทุกชิ้น, ของเหลือไม่มี decision รอบนี้, ค่าประมาณกำจัดต่อ kg |
| `KitchenTiming` | เวลาเริ่มขายเมนู, งานที่เสร็จไม่ทันถูกตัด |
| `MockV4` | ข้อมูล mock หลายกรณี ทุกชั่วโมงผ่านกฎ, มีหลาย action type |

เพิ่มเทสต์ใหม่: ใช้ `run(data, "09:00", with_baselines=False)` กับสำเนา `copy.deepcopy(REAL)` แล้วตรวจ `r["plan"]` / `r["payload"]`

---

## Backtest วัดผลกระทบ

`AI/backtest/run_backtest.py` จำลองร้านจาก `AI/risk_forecaster/data/mock_v3` แล้วให้ 3 นโยบายจัดการ lot ชุดเดียวกัน
ลูกค้าชุดเดียวกัน (`latent_demand`):

1. ร้านแบบเดิม: ขายราคาปกติ ของหมดอายุไปฝังกลบ
2. ลดราคาตามกฎตายตัวตามวันที่เหลือ (3 ช่วงส่วนลด เทียบกับช่วงที่ดีที่สุด)
3. Risk Scanner + Forecaster + Optimizer ทุกเช้า 08:00 (Forecaster เทรนใหม่ด้วยข้อมูลก่อน 2026-08-04 เท่านั้น ไม่เห็นยอดขายช่วงทดสอบ)

```bash
cd AI/backtest
python run_backtest.py                                # 60 วัน 2026-08-17 -> 2026-10-15 (~12 นาที)
python run_backtest.py --start 2026-08-04 --days 73   # ช่วง test เต็ม
python run_backtest.py --render-only                  # สร้าง HTML ใหม่จาก output/backtest_result.json (ไม่รันใหม่)
```

ผล (60 วัน หลังแก้ 3 จุดในหัวข้อ 11): กำไรสุทธิ ร้านเดิม 258,658 / กฎตายตัว (ช่วงต่ำ) 184,491 / **ของเรา 261,792 บาท**
= **+1.21%** เทียบร้านเดิม (ได้ 16% ของเพดานที่ประหยัดได้ 19,215 บาท) และ +41.9% เทียบกฎตายตัว
ฝังกลบลด 18.6% รายละเอียดใน `AI/backtest/output/backtest_report.html`

backtest เป็นเครื่องมือหา bug ทางธุรกิจที่ดีที่สุดที่มี: ทุกครั้งที่แก้ logic ของ Optimizer ให้รันซ้ำแล้วเทียบตัวเลข

---

## สิ่งที่เปลี่ยนเมื่อ 22 ต.ค. 2026 (เส็งทำเอง)


### ลดราคา: ติดป้ายทั้งชั้น + วางแผนของเหลือรอบหน้า

- MARKDOWN `action_quantity` = ทุกหน่วยบนชั้น (เดิม = เฉพาะยอดที่คาดว่าขายได้ ทำให้ชั้นมีของสองราคา)
- ของเหลือจากการลดราคาไม่มี decision รอบนี้ (`ym` ในเป้าหมายเป็นค่าประมาณ) server แยก lot `MARKDOWN_SPLIT` → `IDLE`
  (`server/services/task_actions.py`)

### Rolling horizon + กันบั๊กเที่ยวฟรี

- แผนชั่วคราว (provisional) + `lots_to_release` + กฎ H7 (หัวข้อ 5.4)
- `pipeline.lots_to_release` = lot ที่ทุก portion เป็น SELL_REGULAR, KITCHEN_INGREDIENT (วัตถุดิบรองที่ DB ตัดให้งานครัว
  decision อยู่ที่ lot หลัก) หรือแผนชั่วคราว; lot ที่มี task คืน IDLE ตอน task เสร็จ / ถูกปฏิเสธ
  (`release_lot_if_idle` ใน `server/scripts/lot_lifecycle.sql`)

### ค่าเที่ยว partner แบบเรียกรถเฉพาะ (on-call)

- โหมด BIN / DEDICATED (`context._partner_mode`), ค่าเที่ยวเฉลี่ยต่อ kg จาก `product_daily.waste_qty`
- "ปริมาณที่คุ้มที่สุดภายในเพดานเวลา" (`max_hold_days`, `calls_per_week`, `economic_call_kg`) แทนการเรียกรถเมื่อถึง min_kg
- ถังที่มีของอยู่แล้ว (`partner_bins` จาก server) นับรวมตอนคิดเวลารับ
- เพดานเที่ยวเต็ม (วิธี ก): ของที่ขายไม่ได้ก้อนใหญ่จ่ายไม่เกินค่าเรียกรถ 1 ครั้ง (`solver._full_call_cap` เขียนในหน่วย kg
  เพื่อไม่ให้ HiGHS พัง "Status 4 Solve error")
- `plan.partner_bins[]` + คำเตือน `A5_CALL_PARTNER`, `A6_BIN_BELOW_MIN_KG`, `W2_PARTNER_DEDICATED`, `W3_PICKUP_GAP_OVER_HOLD`
- กฎ H4 ขั้นต่ำต่อเที่ยวตรวจเฉพาะ DEDICATED
- server: `GET /ai/optimize-inputs` ส่ง `waste_history` + `partner_bins` เพิ่ม (query `waste_history_days`)
- fixture อัปเดตตามข้อมูล partner จริงใน Supabase + `waste_history` 28 วัน

### แก้จากผล backtest (3 จุด ทำให้ผลจาก −2.42% เป็น +1.21% เทียบร้านเดิม)

1. **K5 (`rules.markdown_tiers`)**: ราคาปกติไม่ถูกตัดทิ้งเมื่อคาดว่าขายได้ 0 ตราบที่ยังมีเวลาขาย
   เดิม solver ไม่มีทาง "วางขายต่อ" ต้องดึงของไปฝังกลบตอน 08:00 ทั้งที่ยังขายได้ถึงปิดร้าน
2. **ต้นทุน lost sales (`rules.markdown_tiers` + `context._lost_sales_disposal`)**: คิดเต็มราคา + ค่ากำจัด
   (เดิมคิดแค่ margin = ราคา − ต้นทุน ทั้งที่ต้นทุนจมแล้ว ทำให้ลดราคาเกินจำเป็น)
   ค่า config เปลี่ยนชื่อ `lost_sales_margin_factor` → `lost_sales_factor`
3. **Risk Scanner (`AI/risk_forecaster/risk_scanner/handoff.py`)**: P10/P90 ของ lot = ยอดที่ lot ได้เมื่อความต้องการของสินค้า
   อยู่ที่ P10/P90 แล้วแบ่งผ่านคิวเดียวกัน (เดิม lot ท้ายคิว FIFO ได้ P10 = P50 = P90 = 0 ไม่มีความไม่แน่นอนเลย)

### อื่น ๆ

- `run_optimize.py --input`: เดิมใช้ `products` ของ optimize_inputs (ไม่มี flag การกำจัด) แทน `products.json`
  ทำให้รันซ้ำจากไฟล์แล้วทุก partner ถูกปฏิเสธ (`W0_DISPOSAL_FLAGS_MISSING` + `A2_UNRESOLVED`) แก้ให้ใช้ `products.json` แล้ว

เทสต์จาก 40 → 64 เทสต์ (เพิ่มกลุ่ม `TripCost`, `PartnerBins`, `Rolling`, `MarkdownWholeShelf` และเทสต์ K5 / lost sales)

---

## ปัญหาที่ยังค้าง / ข้อควรระวัง

- **Lambda บน AWS ยังรันโค้ดเก่า** ต้อง build image ใหม่ (`AI/pipeline/build_worker.sh`) + `sam deploy` ถึงจะได้ logic ใหม่
  decision ที่บันทึกเมื่อ 17-18 ต.ค. มาจาก logic ก่อนแก้ backtest
- **`max_hold_days = 2`** เป็นสมมติฐาน ค่านี้คุมทั้งความถี่เรียกรถและค่าเที่ยวต่อ kg ควรให้ทีม/ร้านยืนยัน
  (backtest: ทุกนโยบายเรียกรถฝังกลบ 32 ครั้งเท่ากันเพราะเพดานนี้ ค่าเรียกรถจึงลดไม่ได้)
- **Risk Scanner จับ lot ที่จะเหลือได้ราว 45%** (recall บนช่วง test) lot ที่หลุดไม่ถึง Optimizer เลย เป็นตัวจำกัดผลมากที่สุด
- lot ที่ถูกใช้เป็นวัตถุดิบรองแบบ FEFO อย่างเดียว (ไม่มี decision ของตัวเอง) อาจค้างสถานะ `PROCESSING`
- จำนวนหน่วยที่ DB ตัดแบบ FEFO ปัดต่อ task อาจต่างจากที่ Optimizer จำลองเล็กน้อย
- query `products` / `at_risk` ฝั่ง server ยังไม่แบ่งหน้า (Supabase คืนครั้งละ 1,000 แถว)
- DB ยังไม่มีการบันทึกยอดขายจริงต่อ lot หลังลดราคา (วัดผลจริงได้จาก backtest เท่านั้น)
- ผลขึ้นกับเวลาที่รัน (ยอดขายที่เหลือ, รอบรับของ partner, ชั่วโมงครัว) รันตอนเช้าก่อนเปิดร้านให้ผลดีที่สุด
- ข้อเสนอเปลี่ยน schema เดิม (เพิ่ม kg / % / เวลารับ ใน `optimization_decisions`, ตารางจองความจุ partner) ยังไม่ได้ทำ
  ตอนนี้ข้อมูลเหล่านี้อยู่ใน `alternatives[0]` และ `allocations`

---

## แก้ปัญหาที่เจอบ่อย

| อาการ | สาเหตุ / วิธีแก้ |
| --- | --- |
| exit 3 "ไม่มีรอบสแกนที่พร้อมตัดสินใจ" | วันที่สแกนไม่ตรง `DEMO_DATE` ของ server: สแกนใหม่ (`cd ../risk_forecaster && python run_scan.py --source api`) หรือรัน server ในเครื่องด้วย env `DEMO_DATE=<วันที่สแกน>` (ไม่ต้องแก้ `.env`) หรือ `--run-id` |
| `H0_SCAN_DATE_MISMATCH` | เหมือนข้างบน (รอบสแกนเก่า) |
| exit 2 แผนไม่ผ่านกฎ | ดู `violations` ที่พิมพ์ออกมา รันซ้ำด้วย `--input output/<รอบ>/optimize_inputs.json` แล้วดีบักในเครื่อง |
| server ตอบ 503 "โหลด Optimizer ไม่ได้" | venv ของ server ไม่มี numpy/scipy หรือหาโฟลเดอร์ไม่เจอ (ตั้ง `OPTIMIZER_PATH`) |
| `A4_SOLVER_NOT_OPTIMAL` / ช้า | lot เยอะมาก: เพิ่ม `solver_time_limit_s` หรือปิด baseline (`with_baselines=False`) |
| ตัวอักษรไทยเพี้ยนบน Windows console | `set PYTHONIOENCODING=utf-8` (ถ้ารัน `python -I` env นี้ไม่มีผล ใช้ `sys.stdout.reconfigure(encoding="utf-8")`) |
| ไฟล์ชื่อซ้ำกับ module มาตรฐาน (เช่น `inspect.py`) ในโฟลเดอร์ที่รัน | Python import ไฟล์นั้นแทน stdlib → เปลี่ยนชื่อไฟล์ |
