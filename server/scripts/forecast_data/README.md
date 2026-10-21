# Mock data (simulate.py v4)

สร้าง `daily_context` + `product_daily` (ย้อนหลัง 365 วันถึง 15 ต.ค. 2569) + `inventory_lots` (lot demo) ชุดเดียวกัน
วัน demo = **2026-10-16 (ศุกร์)** ต้องตรงกับ `DEMO_DATE` ใน `server/.env` และ `DemoDate` ตอน `sam deploy`

## Reset + สร้างใหม่ (คำสั่งเดียว)

```bash
cd server
bash scripts/reset_mock_lots.sh        # ถามยืนยันก่อนลบ  (--yes = ไม่ถาม)
```

1. `simulate.py` -> `data/*.csv` (seed ตายตัว รันซ้ำได้ผลเดิม)
2. `python -m scripts.load_mock_data` -> ล้าง task / decision / ผลสแกน / forecast / การจองครัว แล้วแทนที่
   `inventory_lots`, `product_daily`, `daily_context` และ baseline ของ `demo_reset()`
3. `AI/risk_forecaster/tools/build_dataset.py` -> CSV ชุดเดียวกันไป `data/mock_v3` (Forecaster ใน image เทรนจากที่นี่)

แล้ว build + deploy worker ใหม่ (คำสั่งอยู่ท้าย output ของสคริปต์) ต้องมี python ที่มี `numpy` + `pandas` (`PY_DATA`)
และ python ของ server ที่มี `supabase` (`PY_SERVER`, ค่าเริ่มต้น `.venv/bin/python`)

## lot demo v4 (27 ล็อต)

หลักการ (ไม่ได้กำหนดระดับความเสี่ยงหรือทางจัดการเอง):
- 1 สินค้ามีหลายล็อตซ้อนกันบนชั้นเหมือนห้างจริง: ล็อตเก่าใกล้หมดอายุ + ล็อตใหม่ที่เพิ่งรับ ลูกค้าส่วนหนึ่งหยิบของใหม่
  (`NEWEST_PICK_SHARE`) ล็อตเก่าจึงเหลือมากขึ้น
- วันรับเข้า = วันที่มีรอบส่งของของสินค้านั้น (`delivery_dow`), จำนวน = ลังเต็ม (`case_pack`)
- ยอดที่ขายไปแล้ว (เริ่ม -> คงเหลือ) ถูกจำลองพร้อมยอดขายย้อนหลัง สต็อกปิดวันที่ 15 ต.ค. ใน `product_daily` = ผลรวมของ lot พอดี
- LOT-000001..013 เหมือน v3 ทุกค่า (`demo_seed()` และเทสต์ยังอ้างถึงได้) มี 1 กรณีผิดปกติที่ตั้งใจใส่: กล้วยรับเข้าเกินใบสั่ง

ผลตรวจ: รัน Risk Scanner (โหมด local) + Optimizer ตัวจริงกับข้อมูลชุดนี้ (`*` = แผนกำจัดวันถัดไปแบบชั่วคราว
lot ถูกคืน IDLE ให้สแกนใหม่) ระดับความเสี่ยงอาจต่างเล็กน้อยบน AWS เพราะตอนตรวจเทรน Forecaster ด้วย gradient boosting
ของ scikit-learn แทน LightGBM (ติดตั้งในเครื่องตรวจไม่ได้) ส่วน optimizer ใช้ผลชุดนี้เป็นเทสต์ `MockV4`

| lot | สินค้า | รับเข้า → หมดอายุ | เริ่ม → คงเหลือ | ที่มา | ระดับ (score) | Optimizer 09:00 | Optimizer 19:00 |
|---|---|---|---|---|---|---|---|
| LOT-000001 | DAI-001 | 10-09 → 10-18 | 220 → 150 | หมดอายุก่อน ได้ demand ก่อนแบบ FIFO | MEDIUM (58) | – | – |
| LOT-000002 | DAI-001 | 10-15 → 10-24 | 180 → 172 | lot เดิมของ v3 | LOW (0) | – | – |
| LOT-000003 | DAI-002 | 09-19 → 10-17 | 200 → 45 | lot เดิมของ v3 | MEDIUM (59) | – | – |
| LOT-000004 | MEA-001 | 10-13 → 10-17 | 80 → 58 | เหลือราว 1 ใน 4 (score ~25) | HIGH (75) | MARKDOWN 20% 45, ANAEROBIC_DIGESTION* 11, KITCHEN 2 | MARKDOWN 20% 29, ANAEROBIC_DIGESTION* 27, KITCHEN 2 |
| LOT-000005 | MEA-002 | 10-11 → 10-17 | 40 → 24 | lot เดิมของ v3 | HIGH (65) | MARKDOWN 20% 14, ANAEROBIC_DIGESTION* 6, KITCHEN 4 | MARKDOWN 20% 9, ANAEROBIC_DIGESTION* 15 |
| LOT-000006 | SEA-001 | 10-14 → 10-16 | 30 → 20 | หมดอายุวันนี้ ของเหลือเยอะ | CRITICAL (73) | MARKDOWN 20% 9, ANAEROBIC_DIGESTION* 5, KITCHEN 6 | MARKDOWN 20% 2, LANDFILL 18 |
| LOT-000007 | PRO-001 | 10-12 → 10-17 | 100 → 50 | เหลือราว 1 ใน 5 (score ~15-20) | HIGH (78) | MARKDOWN 20% 38, ANIMAL_FEED* 12 | MARKDOWN 20% 24, ANIMAL_FEED* 26 |
| LOT-000008 | PRO-002 | 10-14 → 10-18 | 120 → 90 | lot เดิมของ v3 | CRITICAL (82) | MARKDOWN 20% 42, ANIMAL_FEED* 48 | MARKDOWN 20% 32, ANIMAL_FEED* 55, KITCHEN_INGREDIENT 3 |
| LOT-000009 | BAK-001 | 10-13 → 10-17 | 100 → 70 | เหลือราว 1 ใน 3 (score ~30-35) | MEDIUM (57) | – | – |
| LOT-000010 | BAK-002 | 10-14 → 10-17 | 26 → 22 | lot เดิมของ v3 | CRITICAL (85) | MARKDOWN 20% 10, ANIMAL_FEED* 12 | MARKDOWN 20% 6, ANIMAL_FEED* 16 |
| LOT-000011 | BAK-003 | 10-14 → 10-17 | 70 → 55 | ขนมปังพุดดิ้งจากครัว | HIGH (79) | MARKDOWN 20% 20, ANIMAL_FEED* 35 | MARKDOWN 20% 13, ANIMAL_FEED* 42 |
| LOT-000012 | RTE-002 | 10-15 → 10-16 | 40 → 30 | สลัดอกไก่ หมดอายุวันนี้ | HIGH (52) | ขายปกติ 13, ANAEROBIC_DIGESTION* 17 | ขายปกติ 3, LANDFILL 27 |
| LOT-000013 | BAK-001 | 10-11 → 10-15 | 60 → 8 | หมดอายุ 15 ต.ค. แต่ยังค้างชั้น | CRITICAL (100) | LANDFILL 8 | LANDFILL 8 |
| LOT-000014 | SEA-001 | 10-15 → 10-17 | 15 → 12 | ปลารอบส่งเมื่อวาน (3 ลัง) ซ้อนกับ LOT-000006 ที่หมดอายุวันนี้ | LOW (0) | – | – |
| LOT-000015 | MEA-002 | 10-14 → 10-20 | 15 → 13 | สเต็กรอบพุธ ซ้อน LOT-000005 (ขายวันละ ~6 แพ็ก): เนื้อล้นชั้น | LOW (0) | – | – |
| LOT-000016 | MEA-001 | 10-12 → 10-16 | 40 → 18 | อกไก่รอบจันทร์ หมดอายุวันนี้ ยังเหลือเกือบครึ่ง | MEDIUM (31) | – | – |
| LOT-000017 | MEA-001 | 10-15 → 10-19 | 30 → 30 | อกไก่รอบเมื่อวาน ยังไม่ได้ขาย (ล็อตใหม่ ความเสี่ยงต่ำ) | LOW (0) | – | – |
| LOT-000018 | DAI-002 | 09-18 → 10-16 | 144 → 30 | โยเกิร์ตรอบศุกร์ 18 ก.ย. (6 ลัง) หมดอายุวันนี้ (อายุ 28 วัน) | HIGH (46) | ขายปกติ 11, ANAEROBIC_DIGESTION* 3, KITCHEN_INGREDIENT 8, KITCHEN_INGREDIENT 8 | MARKDOWN 20% 5, LANDFILL 25 |
| LOT-000019 | DAI-002 | 10-13 → 11-10 | 96 → 96 | โยเกิร์ตรอบอังคาร ยังสด (ล็อตควบคุม ความเสี่ยงต่ำ) | LOW (0) | – | – |
| LOT-000020 | PRO-001 | 10-15 → 10-20 | 220 → 205 | กล้วยรับเข้าเกินใบสั่ง 22 ลัง (ขายวันละ ~19): ของล้นที่ยังสด | HIGH (66) | MARKDOWN 20% 98, ANIMAL_FEED* 106, KITCHEN 1 | MARKDOWN 20% 84, ANIMAL_FEED* 121 |
| LOT-000021 | PRO-001 | 10-11 → 10-16 | 60 → 22 | กล้วยรอบอาทิตย์ หมดอายุวันนี้ สุกจัด | HIGH (49) | MARKDOWN 20% 17, ANAEROBIC_DIGESTION* 4, KITCHEN 1 | MARKDOWN 20% 3, LANDFILL 19 |
| LOT-000022 | PRO-002 | 10-15 → 10-19 | 24 → 24 | ผักกาดรอบเมื่อวาน 2 ลัง ซ้อน LOT-000008 | LOW (0) | – | – |
| LOT-000023 | PRO-002 | 10-12 → 10-16 | 36 → 12 | ผักกาดรอบจันทร์ หมดอายุวันนี้ (วัตถุดิบรองของสลัด) | MEDIUM (36) | – | – |
| LOT-000024 | BAK-001 | 10-15 → 10-19 | 36 → 30 | ขนมปังแซนวิชรอบเมื่อวาน 3 ลัง | LOW (0) | – | – |
| LOT-000025 | BAK-002 | 10-15 → 10-18 | 8 → 8 | เค้กกล้วยรอบเมื่อวาน 2 ลัง ซ้อน LOT-000010 | LOW (0) | – | – |
| LOT-000026 | BAK-002 | 10-13 → 10-16 | 8 → 6 | เค้กกล้วยรอบอังคาร หมดอายุวันนี้ | HIGH (56) | MARKDOWN 20% 4, ANAEROBIC_DIGESTION* 2 | LANDFILL 6 |
| LOT-000027 | BAK-003 | 10-15 → 10-18 | 24 → 20 | ขนมปังพุดดิ้งที่ครัวอบเมื่อวาน ซ้อน LOT-000011 | LOW (8) | – | – |

สรุปผลตรวจ: CRITICAL 4 / HIGH 9 / MEDIUM 5 / LOW 9 -> ส่ง Optimizer 13 ล็อต (v3: 4 ล็อต)

| เวลาที่รัน | decision | action_type ที่ได้ |
|---|---|---|
| 07:00-09:00 | 26-27 | MARKDOWN, KITCHEN_REPURPOSE, ANIMAL_FEED, ANAEROBIC_DIGESTION, LANDFILL |
| 10:00-15:00 | 27-29 | เหมือนด้านบน (ครัวลดลงตามชั่วโมงที่เหลือ) |
| 17:00-23:00 | 21-25 | เหมือนด้านบน ครัวเหลือ 1 งาน ส่วนที่ทิ้งเพิ่มขึ้น |

ไม่ได้: **DONATE** (lot ที่ส่งถึง optimizer ส่วนใหญ่เหลืออายุ < 2 วัน; กล้วย LOT-000020 เข้าเกณฑ์แต่วางขาย+ส่งอาหารสัตว์คุ้มกว่า
ค่าเที่ยว 550 บาท), **COMPOST** (1,653 บาท/เที่ยว + ขั้นต่ำ 100 kg แพงกว่าอาหารสัตว์/ฝังกลบ), **DISCARD** (ฝังกลบรับทุกหมวด
ทุกสินค้าจึงมีทางไป) เป็นผลตามข้อมูล partner จริงใน DB ไม่ใช่ข้อผิดพลาด

`data_checks/validate_mock_data.py` ผ่านทุกข้อ: สต็อกสมดุล, ของหมดชั้น/ของทิ้งตามเป้า (ทิ้งรวม 5.5%, หมดชั้น 12.3%),
วัดผลการลดราคาได้, LightGBM ชนะ baseline, lot demo มีครบทุกระดับ
