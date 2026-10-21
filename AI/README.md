# AI (Risk Scanner + Forecast → Optimizer → RAG/LLM)

## 1. ข้อมูลสำหรับเทรน: `AI/data/`

| ไฟล์ | เนื้อหา |
| --- | --- |
| `training_dataset.csv` | ตารางเดียวพร้อมเทรน = `product_daily` + `daily_context` + `products` |
| `product_daily.csv` | สินค้า × วัน: ยอดเปิด/รับเข้า/ขายราคาเต็ม/ขายราคาลด/ทิ้ง/คงเหลือ, ของหมด (`is_stockout`, `stockout_hour`) |
| `daily_context.csv` | 1 วัน: วันหยุด, วันเงินเดือน, ฝน, อุณหภูมิ |
| `products.csv` | หมวด, ราคา, `shelf_life_days` |
| `data_dictionary.csv` | คำอธิบายและที่มาของทุกคอลัมน์ |

อัปเดตข้อมูล: รัน `python -m scripts.export_training_data` ในโฟลเดอร์ `server` (เขียนทับ `AI/data/`)

## 2. Input ตอนทำนาย: `GET /api/v1/ai/scan-inputs?history_days=28`

| ส่วน | เนื้อหา |
| --- | --- |
| `reference_date` | "วันนี้" ของระบบ ใช้นับ `days_to_expiry` (demo ใช้ `2026-10-16`) |
| `inventory_lots` | lot ที่ต้องประเมิน (`ai_status = IDLE`) |
| `products` | หมวด, ราคา, `shelf_life_days` |
| `product_daily` | ยอดขายย้อนหลัง `history_days` วัน **ถึงเมื่อวาน** (ไม่มีของวันนี้ เพราะเป็นสิ่งที่ต้องทำนาย) |
| `daily_context` | วันนี้ถึง 7 วันข้างหน้า ถ้ามี lot หมดอายุช้ากว่านั้นจะยืดถึงวันหมดอายุล่าสุด (อากาศเป็นค่าพยากรณ์) ปัจจัยของวันในอดีตใช้จาก `AI/data/daily_context.csv` |

- ถ้าโมเดลไม่ใช้ยอดขายล่าสุดเป็น feature ส่ง `history_days=0` (`product_daily` = `[]`)
- **คอลัมน์ชุดเดียวกับข้อมูลเทรน** ให้คำนวณ feature ด้วยโค้ดเดียวกันทั้งตอนเทรนและตอนทำนาย
- `latent_demand` ใช้วัดผลโมเดลเท่านั้น **ห้ามใช้เป็น feature**
- วันที่ `is_stockout = true` ยอดขายต่ำกว่า demand จริง (censored)
- สินค้าเดียวมีหลาย lot ได้ (เช่น DAI-001) ให้แบ่ง demand แบบ FIFO

รายละเอียดที่มาของข้อมูล: `server/README.md` หัวข้อ **Forecast Data**

## 3. Output: `POST /api/v1/risk-assessments`

ดู `server/schemas/risk_assessment.py` (ต่อ lot: `days_to_expiry`, `forecast_daily_demand`,
`predicted_units_sold_before_expiry`, `predicted_leftover_units`, `sell_through_probability`, `risk_score` 0–100, `risk_level`)
