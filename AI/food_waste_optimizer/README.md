# Food-waste Optimizer (refactor จาก database.py -> Supabase/Swagger จริง)

ทุก route เรียกผ่าน `https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1/`
(ตั้งไว้เป็นค่าเริ่มต้นใน `optimizer/io.py` เปลี่ยนได้ด้วย env `API_BASE_URL`)

## ใช้งาน (ฟังก์ชันที่คนอื่นเรียกได้)

```python
from ai_engine.optimizer import run_optimizer, optimize_and_post, run_full_pipeline, OptimizerConfig

# 1) มีข้อมูลอยู่แล้ว (JSON ของ GET /ai/optimize-inputs) -> ไม่แตะเน็ต
result = run_optimizer(inputs_json, demand=None)      # {"plan", "payload", "violations", "payload_errors"}

# 2) ดึงข้อมูลจริง -> optimize -> (POST /optimization-decisions)
optimize_and_post(run_id=None, dry_run=True)          # dry_run=True ไม่เขียนอะไร  /  False = POST จริง
optimize_and_post(source="supabase", dry_run=True)    # อ่านตาราง Supabase ตรง ๆ แทน route

# 3) ขั้น 1-5 ทั้งหมดด้วย mock forecaster
run_full_pipeline(dry_run=True)                       # dry_run=False = PATCH PROCESSING + POST risk + POST decisions
```

ทดสอบ offline (ข้อมูลจากภาพ Supabase): `python -m ai_engine.demo.run_offline --date 2026-10-16 --time 08:00`
เทสต์: `python -m unittest ai_engine.tests.test_optimizer -v` (40 เทสต์)

> ⚠ "Try it out" / `dry_run=False` เขียนข้อมูลจริงลง Supabase รวมถึงจองชั่วโมงครัว (POST /tasks) ทดสอบ staging ก่อน

## แผนที่ของโค้ด (แต่ละ PART ทำอะไร)

| PART | ไฟล์ | หน้าที่ |
| --- | --- | --- |
| 0 | `clock.py`, `optimizer/config.py` | เวลาไทย + `DEMO_DATE`/`DEMO_TIME`; ค่า tunable ทั้งหมด + map action_type |
| 1 | `optimizer/models.py` | แปลง JSON ตาม Swagger เป็น object; แปลงหน่วย G/ML (KG, L ×1000) |
| 2 | `optimizer/rules.py`, `optimizer/demand.py` | กฎ Markdown (K0-K6): หมดอายุ, ราคาต่ำสุด, demand, ลดแล้วไม่คุ้ม |
| 3 | `optimizer/rules.py` | กฎ Partner (P1-P8): วัน/เวลารับ, หมวด, อายุคงเหลือ, kg ขั้นต่ำ/สูงสุด, flag; ต้นทุนเที่ยว |
| 4 | `optimizer/context.py` | เอากฎไปตรวจกับข้อมูลจริงทุก lot/partner/สูตร (+ครัว, ingredient_stock) เหลือเฉพาะทางที่ผ่านกฎ |
| 5 | `optimizer/solver.py` | MILP (HiGHS) แบ่งทุก lot พร้อมกัน กำไรสุทธิสูงสุด |
| 6 | `optimizer/plan.py` | สัดส่วน % ต่อ lot, เงินที่ได้/เสีย, เหตุผลที่ตัดทาง, baseline เปรียบเทียบ |
| 7 | `optimizer/validate.py` | ตรวจแผนซ้ำจากข้อมูลดิบ (ตาข่ายนิรภัย) ก่อนส่ง |
| 8 | `optimizer/decisions.py` | Plan -> payload ของ POST /optimization-decisions + จำลองการตรวจของ server |
| 9 | `optimizer/io.py` | ApiClient (urllib), loader จาก Supabase, เติม flag การกำจัดให้ products |
| 10 | `optimizer/pipeline.py` | ฟังก์ชันครอบ `run_optimizer` / `optimize_and_post` / `run_full_pipeline` |
| — | `forecaster/mock_forecaster.py` | mock risk+forecast ตามฟิลด์ `lot_risk_assessments` (1 lot = 1 สินค้า) |

## หลักการคำนวณ (ตามคำสั่งงาน)

- **กำไรต่อทางเลือกนับต้นทุนสินค้า (COGS = `unit_cost`) ทุกทาง** ทุกหน่วยนับครั้งเดียว เทียบกันตรง ๆ ได้
  `DISCARD = −จำนวน × unit_cost` เหมือนตัวอย่างใน Swagger
- **1 lot มีราคาเดียว** -> เลือกระดับส่วนลดได้ 1 ระดับ (0 = ราคาปกติ, 20-80%) ระดับที่ราคา < `min_allowed_price`
  หรือยอดขายที่คาดไม่เพิ่มจากระดับที่ลดน้อยกว่า ถูกตัด *สินค้าทุกตัวมี `min_allowed_price` = 50% ของราคาปกติ ระดับ 60-80% จึงถูกตัดเสมอ*
- **ยอดขายแบบความน่าจะเป็น (newsvendor)** แทน `demand_kappa` เดิม: ใช้ quantile ของ forecaster ตรง ๆ
  (`low_qty` = P10, `expected_qty` = P50, `high_qty` = P90) P(D ≥ k) ลากเส้นตรงผ่าน (0,1) (P10,0.9) (P50,0.5) (P90,0.1)
  -> หน่วยที่วางบนชั้นในแต่ละช่วงขายออกด้วยโอกาสเฉลี่ย ≈ 0.95 / 0.7 / 0.3 / 0.05 (`demand.survival_segments`)
  อ้างอิงหลัก critical fractile ของ newsvendor (Arrow, Harris & Marschak 1951)
- **วางขายก่อน กำจัดของที่เหลือทีหลัง (END_OF_LIFE)**: ส่วนที่คาดว่าขายไม่หมดไปรอบรับรอบแรกหลังหมดเวลาขาย
  (ร้านปิดของวันหมดอายุ) solver เลือกเองว่าวางขายต่อคุ้มกว่าดึงออกตอนนี้ไหม
  decision ของ END_OF_LIFE มี `due_by` = เวลารับ, `action_quantity` = จำนวนที่คาดว่าเหลือ (ปัดขึ้น) staff กำจัดตามที่เหลือจริง
  เงินในแผนเป็นค่าคาดหมาย ส่วนจำนวนหน่วยปัดเป็นจำนวนเต็มให้รวมเท่ากับ lot (H1)
- **task เอาของออกตรงกับวันที่ลงมือจริง**: decision ของ partner / ทิ้ง ออกเฉพาะเที่ยวที่รับ "วันนี้" เที่ยววันอื่นเป็น
  แผนชั่วคราว (`details.provisional`) ไม่มี decision แล้ว lot ถูกสแกนใหม่และตัดสินใจในวันนั้น: lot ที่ไม่มี decision อื่น
  คืน IDLE ทันที (`lots_to_release`), lot ที่มี task อื่นคืน IDLE ตอน task เสร็จ / ถูกปฏิเสธ (`release_lot_if_idle` ใน
  `server/scripts/lot_lifecycle.sql`) server ตรวจซ้ำใน `validate_payload` (due_by ต้องเป็นวันนี้)
- **Partner**: Total Cost = `fixed_cost_per_trip` + `travel_cost_per_trip` (ต่อเที่ยว แบ่งตาม kg ระหว่าง lot ที่ไปเที่ยวเดียวกัน)
  + kg × `handling_fee_per_kg`; **DONATION คิดแค่ fixed**; ANIMAL_FEED มีรายได้ kg × `buyback_price_per_kg` (0.92)
  1 เที่ยว = (partner, วันที่รับ) ต้อง ≥ `min_kg_per_pickup` (0 = ไม่มีเกณฑ์) และ ≤ ความจุ; weight = น้ำหนักสุทธิจริงจาก `net_content_*`
  ของที่ดึงออกตอนนี้กับของ END_OF_LIFE ที่ตกวันเดียวกันใช้เที่ยวเดียวกัน (เวลารับ = ช้าสุดของวันนั้น แล้วตรวจกฎซ้ำ)
  `trip_cost_mode="scheduled"` = scenario ที่ partner วิ่งรอบประจำอยู่แล้ว (คิดแค่ต่อ kg) · `deferred_trip_cost_share`
  = สัดส่วนค่าเที่ยวของ "วันถัดไป" ที่รอบนี้ต้องแบก
- **วัน/เวลารับ**: weekday ต้องอยู่ใน `pickup_days` (1=จ…7=อา) และอยู่ใน `pickup_time_start–end` ถ้าวันนี้หมดช่วงแล้วเลื่อนไปวันถัดไป
  `min_days_before_expiry` ตรวจ ณ **วันรับ** (NULL/0 = ไม่มีเกณฑ์ รับของหมดอายุได้)
- **ครัว**: Total Cost = Cost_Primary (units × `unit_cost` ของ lot) + `utility_cost` (รวมค่าไฟ+น้ำ+วัตถุดิบรองแล้ว)
  เวลา: เริ่ม = ตอนนี้ + `kitchen_lead_minutes` (วันอื่น = เปิดร้าน), เมนูเริ่มขายเมื่อ batch แรกเสร็จ,
  `due_by` = เริ่ม + เวลาทำ × batch (ไม่ใช่ 17:00 ตายตัวแล้ว) ต้องไม่เกินเลิกกะ `kitchen_due_time` และเวลาหมดอายุของ lot หลัก
  ยอดขายเมนูใช้ P10/P50/P90 (`low_qty` / `menu_qty` / `high_qty`) แบบเดียวกับหน้าร้าน เมนูที่ทำแล้วขายไม่ออกไม่มีรายได้
  ตรวจ: สูตร active, แผนกตรงกับสูตร, `kitchen_capacity` (FULL = 0), ทำเสร็จก่อนหมดอายุ (due_by ต้องไม่เกินเวลาหมดอายุของ lot),
  วัตถุดิบหลักมาจาก lot เสี่ยง, **วัตถุดิบรองของทุกงานรวมกันต้องไม่เกิน `ingredient_stock`** (นับแยกตามวันหมดอายุ)
- ผลลัพธ์ต่อ run: สัดส่วน % ต่อ lot และรวม, kg, รายรับ/ค่าใช้จ่าย/กำไรสุทธิ, เปรียบเทียบกับ "ไม่ใช้ Optimizer"

## ค่าที่ผมตั้งเองและยังต้องให้ยืนยัน (ASSUMPTION — แก้ใน `OptimizerConfig`)

1. `lead_time_minutes=60` เตรียมของก่อน partner มารับ · `kitchen_lead_minutes=30` · `kitchen_due_time=17:00` (เลิกกะครัว)
2. lot หมดอายุสิ้นวันของ `expiration_date` (23:59:59) · หมดเวลาขาย = ร้านปิด (22:00) ของวันหมดอายุ
3. ยอดขายกระจายเท่ากันทุกชั่วโมงที่ร้านเปิด · CDF ของ demand เป็นเส้นตรงระหว่าง P10/P50/P90 และหางถึง P90 + (P90 − P50)
4. ความหนาแน่น ML/L = 1 kg/L (น้ำหนักจริงรวมบรรจุภัณฑ์ไม่มีใน DB)
5. วัตถุดิบหลัก (primary) ต้องมาจาก lot เสี่ยงเท่านั้น (ซื้อ/ใช้สต็อกปกติแทนไม่ได้)
6. ของที่ขายไม่หมดเก็บในห้องพักขยะรอรอบรับถัดไป (`eol_lead_minutes=0`, รอได้ไม่เกิน `max_pickup_wait_days=7`)
7. ของที่ขายไม่หมดแต่ไม่มี partner end-of-life รับ: ค่าเสียหายในเป้าหมาย = `eol_no_route_penalty_factor` (1.0) × unit_cost
8. `trip_cost_mode="dedicated"` (ค่าเริ่มต้น ตรงกับข้อมูล) / `"scheduled"` (ยังไม่มีข้อมูลสัญญารองรับ)
9. `deferred_trip_cost_share=0.0` (rolling horizon) เที่ยววันถัดไปคิดเฉพาะต่อ kg เพราะรอบหน้าตัดสินใจใหม่และน่าจะใช้เที่ยวนั้น
   ร่วมกับ lot อื่น ตั้ง 1.0 = คิดเต็มเหมือนเที่ยวมาเฉพาะของรอบนี้ (ระวังกว่า แต่ทิ้งของที่ยังขายได้ล่วงหน้า)
10. partner ที่ไม่ใช่ DONATION ส่งเป็น action ของตัวเอง (`action_mode="extended"`) ถ้า server รุ่นเก่าใช้ `"current"`

## ปัญหาที่พบ (รายละเอียด + SQL ใน `sql/001_schema_fixes.sql`)

1. **`action_type` ไม่มีวิธีกำจัดผ่าน partner** (ANIMAL_FEED/COMPOST/AD/LANDFILL) -> เพิ่มค่า enum
2. **`optimization_decisions` ไม่เก็บ kg / % / เวลารับ / แยกต้นทุน** -> เพิ่ม 4 คอลัมน์ (ตอนนี้ใส่ใน `alternatives[0]`)
3. **`min_days_before_expiry` เป็น NULL ใน 4/5 partner** แต่ API ประกาศ int บังคับ -> `NOT NULL DEFAULT 0`
4. **ไม่มี demand ราย % ส่วนลด และ demand เมนู** -> `lot_risk_assessments.demand_curve` + ตาราง `recipe_menu_demand`
5. **ไม่มีตารางจองความจุ partner ต่อรอบรับ** -> `partner_pickup_bookings`
6. **งานครัวใช้วัตถุดิบหลายตัวจองชั่วโมงซ้ำ** ถ้าแตกเป็นหลาย decision (server จองตาม batch_count ของทุก task) ->
   ตอนนี้ส่ง 1 decision ต่องานที่ lot หลัก; lot ที่เป็นวัตถุดิบรอง/หลักรองจึง **ไม่มี decision ของตัวเอง** (รายชื่ออยู่ใน
   `alternatives[0].primary_lots / secondary_lots`) ถ้าต้องการให้มีทุก lot ดู SQL ข้อ 6
7. **ไม่มีเส้นทาง "ทิ้งเองในร้าน"** ทุกหน่วยที่เหลือต้องจ่ายค่าเที่ยว partner (≥ 650 บาท/เที่ยวของ landfill) เศษน้อย ๆ จึงแพงมาก
   (ดูคำเตือน `A2_TRIP_COST_PER_KG`) ถ้าร้านทิ้งเองได้ฟรีให้บอก จะเพิ่มเป็นเส้นทาง SELF_DISCARD

## แพตช์ฝั่ง API ที่แนะนำ (โค้ด API ไม่ได้อยู่ใน scope ที่ให้แก้ จึงแนบเป็นข้อเสนอ)

```python
# routers/ai.py — ส่ง flag การกำจัดมาใน products (ตอนนี้ select ไม่มี จึงต้องเติมจาก Supabase)
products = supabase.table("products").select(
    "product_id, name, category, unit_of_measure, net_content_value, net_content_unit, base_cost, regular_price, "
    "min_allowed_price, allow_markdown, allow_kitchen_repurposing, allow_donation, "
    "allow_animal_feed, allow_composting, allow_anaerobic_digestion, allow_landfill").execute().data
# schemas/responses.py — ProductRule เพิ่ม 4 field Optional[bool] เหล่านั้น
#                        DonationPartnerRow.min_days_before_expiry: Optional[int] = None
# services/decisions.py — (partner["min_days_before_expiry"] or 0)
```

## ความปลอดภัย

`.env` ที่แนบมามี `SUPABASE_SERVICE_ROLE_KEY` (สิทธิ์เต็ม ข้าม RLS) ถือว่าหลุดแล้ว ควร rotate ใน Supabase
และอย่า commit — ใช้ `.env.example` เป็นแบบ
