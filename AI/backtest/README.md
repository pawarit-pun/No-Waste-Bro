# Backtest (โค้ด AI บน main)

วัดผลของ Risk Scanner + Forecaster + Optimizer **บน main** บนร้านจำลอง 60 วัน (ช่วง test ของ Forecaster)
ใช้กติกาและข้อมูลชุดเดียวกับ backtest ของ `optimizer-update` (22 ต.ค.) แต่นโยบาย 3 จำลองวงจร lot ตามแนวคิดของ main:
decision เอาของออกเฉพาะเที่ยวที่รับวันนี้ เที่ยววันอื่นเป็นแผนชั่วคราว แล้ว lot คืน IDLE ให้ตัดสินใจใหม่ในวันนั้น

## รัน

```bash
cd AI/backtest
python run_backtest.py                                   # 60 วัน ทั้ง 2 กติการถ (~5-10 นาที)
python run_backtest.py --disposal dedicated --days 7     # รันเร็ว
python run_backtest.py --approve-rate 0.8                # ผู้จัดการปฏิเสธ task 20%
python run_backtest.py --render-only                     # สร้าง HTML ใหม่จาก JSON เดิม
python -m unittest test_backtest -v                      # เทสต์ (~20 วินาที)
```

ใช้ Python ที่มี lightgbm + scipy (เช่น `server/.venv`) ผลอยู่ที่ `output/backtest_report_<กติการถ>.html` และ `.json`

## กดรันครั้งเดียว (one-shot): วันเดียว ไม่คิดถึงวันข้างหน้า

```bash
python run_oneshot.py                                         # 27 lot ของ demo วันที่ 2026-10-16 (~5 วินาที)
python run_oneshot.py --source history --date 2026-09-18      # lot บนชั้นเช้าวันนั้น + ลูกค้าจริง
```

- เหมือนกดปุ่ม Run demo 1 ครั้ง: สแกนทุก lot → Optimizer → task วันนี้ → ขาย 1 วัน → ปิดร้าน → สรุปผลวันนั้น
- ไม่มีของเข้าร้าน ไม่มีรอบสแกนพรุ่งนี้ ครัวใช้ชั่วโมงของวันนี้เท่านั้น รถแบบ dedicated
- `demo`: ลูกค้าวันที่ 16 ต.ค. ไม่มีใน mock (จบ 15 ต.ค.) ใช้ `latent_demand` เฉลี่ยวันเดียวกันของ 4 สัปดาห์ก่อน, Forecaster ตัวจริง
- `history`: ลูกค้าจริงของวันนั้น, Forecaster เทรนใหม่ด้วยข้อมูลก่อนวันนั้น
- กำไรวันนี้ตัดต้นทุนของหมดอายุที่ยังค้างในร้าน (ขายไม่ได้แล้ว) สต็อกที่ยังขายได้คิดที่ต้นทุน
  ผลวันเดียวเข้าข้างการลดราคา (ของที่ขายลดราคาวันนี้อาจขายราคาเต็มได้พรุ่งนี้) รายงานจึงแสดงมูลค่าราคาปกติของสต็อกเหลือด้วย
- ผล: `output/oneshot_<source>_<วันที่>.html` + `.json` (task ที่ Optimizer สั่ง, แผนชั่วคราว, ระดับความเสี่ยง, baseline ของ Optimizer)

## ไฟล์

| ไฟล์ | หน้าที่ |
| --- | --- |
| `world.py` | โลกจำลอง: lot, ลูกค้า, ขาย, ถัง / รถ partner, บัญชีเงิน, นโยบาย 1-2 (ไม่ import Optimizer) |
| `policy_lifecycle.py` | นโยบาย 3: SCAN → OPTIMIZE → TASKS → ลงมือ → สถานะ lot (IDLE / PROCESSING / CHECKED) |
| `run_backtest.py` | CLI + สรุปผล + รายงาน HTML (60 วัน) |
| `run_oneshot.py` | กดรันครั้งเดียว: 1 วัน ทุกนโยบาย + รายงาน HTML |
| `test_backtest.py` | เทสต์โลกจำลอง วงจร lot และรันจริง 3 วัน |
| `data/supabase_2026-10-22.json` | สินค้า / สูตร / partner / ครัว จาก Supabase 22 ต.ค. (fixture ของ main ยังเป็นค่า partner ชุดเก่า) |
| `data/reference_optimizer-update.json` | ผล backtest ของ `optimizer-update` ไว้เทียบในรายงาน (กติการถ bins) |

## กติกาที่เหมือน backtest 22 ต.ค.

- ข้อมูล `mock_v3`: สต็อกวันแรก `lot_daily`, ของเข้าร้าน `lot_outcomes`, ลูกค้า `latent_demand`
- 2026-08-17 → 2026-10-15, Forecaster เทรนด้วยข้อมูลก่อน 2026-08-04 เท่านั้น
- ลูกค้า: lot ลดราคาได้ก่อน (× `TRUE_LIFT`), 40% หยิบ lot ใหม่สุด, ที่เหลือ FIFO
- นโยบาย 1 ร้านแบบเดิม / 2 ลดราคาตามกฎตายตัว (เทียบกับช่วงที่ดีที่สุด) / 3 product, สูตรกำไรสุทธิและความเสียหายเดิม
- กติการถ `bins` ให้ผลนโยบาย 1-2 ตรงกับ backtest 22 ต.ค. ทุกบาท (มีเทสต์คุม)

## นโยบาย 3 แบบ main (ต่างจาก 22 ต.ค.)

| ขั้น | ทำอะไร | อ้างอิง |
| --- | --- | --- |
| SCAN | lot `IDLE` ที่ยังมีของ **รวมที่หมดอายุแล้ว** · LOW / MEDIUM → IDLE · HIGH / CRITICAL → PROCESSING | `GET /ai/scan-inputs` ไม่กรองวันหมดอายุ |
| OPTIMIZE | `run_optimizer` ของ main ค่าเริ่มต้น ไม่มี `waste_history` / `partner_bins` | `run_optimize.py` |
| TASKS | decision 1 ตัว = task 1 ตัว อนุมัติตาม `--approve-rate` | Review Queue |
| ลงมือ | MARKDOWN แยก lot ใหม่ (IDLE) · ครัว · partner วันนี้ · แผนชั่วคราวไม่ทำอะไร | `lot_lifecycle.sql` |
| สถานะ | `lots_to_release` → IDLE · มี task → CHECKED → IDLE ตอน task จบ | `release_lot_if_idle` |
| หมดอายุ | ไม่มี decision = ค้างในร้าน รอรอบสแกนพรุ่งนี้ (ไม่ทิ้งเองอัตโนมัติ) ปิดรอบทิ้ง landfill | |

## กติการถ (`--disposal`)

- `dedicated`: รถของ partner มาทุกวันที่มีรอบรับและมีของรอ คิดค่าเที่ยวเต็มทุกครั้ง (วิธีที่ Optimizer บน main คิดต้นทุน)
- `bins`: ถังสะสม เรียกรถเมื่อถึงปริมาณที่คุ้มหรือของรอเกิน 2 วัน (เหมือน 22 ต.ค. ใช้เทียบกับผลของ `optimizer-update`)

## ตัวชี้วัดเพิ่ม (หัวข้อ "วงจร lot แบบ main" ในรายงาน)

task ต่อวัน · % task เอาของออกที่ due วันนี้ (ต้อง 100%) · วันที่ได้แผนชั่วคราว · หน่วย × วัน ของหมดอายุค้างในร้าน
(คืนแรก / เกิน 1 คืน) · ของหมดอายุที่ไม่เคยได้ decision · lot ค้าง PROCESSING · จำนวนการสแกน

## ข้อจำกัด

ข้ามขั้น LLM task agent · ทุก task เสร็จในวันที่ออก (งานครัวของพรุ่งนี้ทำวันนี้เหมือน 22 ต.ค.) · staff เอาของออกได้ตามจำนวนจริง ·
มูลค่าเมนูครัวใช้ค่าคาดหมายของแผน · ข้อมูล mock 24 SKU
