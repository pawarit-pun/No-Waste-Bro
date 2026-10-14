"""ข้อความที่แสดงในหน้า Swagger UI (/docs) สำหรับ Team AI"""

APP_TITLE = "No-Waste-Bro API"
APP_VERSION = "0.2.0"

APP_DESCRIPTION = """
API สำหรับระบบลด Food Waste ใน Hypermarket ใช้ร่วมกันระหว่าง **AI Agent**, **Admin Dashboard** และ **Staff Mobile App**
ข้อมูลทั้งหมดอยู่บน Supabase ทุก route ขึ้นต้นด้วย `/api/v1`

## AI Pipeline Flow

AI Agent เรียก route ตามลำดับนี้ในการสแกน 1 รอบ (1 run)

| ขั้น | Route | ทำอะไร | ค่าที่ต้องเก็บไว้ใช้ต่อ |
| --- | --- | --- | --- |
| 1 | `PATCH /inventory-lots/ai-status` | ล็อก lot ที่กำลังสแกนเป็น `PROCESSING` | – |
| 2 | `GET /ai/scan-inputs` | ดึง lot + ยอดขาย ไปทำ **Risk Scanner + Forecast** | – |
| 3 | `POST /risk-assessments` | บันทึกผลความเสี่ยงของแต่ละ lot | `run_id`, `assessment_id` ของแต่ละ lot |
| 4 | `GET /ai/optimize-inputs?run_id=...` | ดึงข้อมูลให้ **Optimizer** ตัดสินใจ (ลดราคา / เข้าครัว / บริจาค / ทิ้ง) | – |
| 5 | `POST /tasks` | ให้ **LLM** สร้าง task ให้ staff (ใส่ `assessment_id` มาด้วย) | `task_id` |
| 6 | `PATCH /inventory-lots/ai-status` | เปลี่ยน lot ที่สแกนเสร็จเป็น `CHECKED` | – |

## เรื่องที่ควรรู้

- **วันที่อ้างอิง (`reference_date`)** = วันนี้ตามเวลาไทย หรือค่า `DEMO_DATE` ใน `.env` ของ server ถ้าตั้งไว้ ใช้ค่านี้คำนวณวันหมดอายุ
- **ค่าเฉลี่ยยอดขาย** (`daily_sales_velocity`) คำนวณจากวันขายล่าสุดใน `sales_history` ไม่ใช่วันนี้
- **หน่วยสินค้า:** lot นับเป็นชิ้น/แพ็ค แต่สูตรอาหารใช้ G / ML ให้แปลงผ่าน `net_content_value` + `net_content_unit` ของสินค้า (KG / L ให้คูณ 1000)
- **ราคาต่ำสุด:** DB ไม่ยอมให้ตั้งราคา lot ต่ำกว่า `min_allowed_price` ของสินค้า
- **การทดสอบด้วย "Try it out" เขียนข้อมูลจริงลง Supabase** รวมถึงจองชั่วโมงครัวจริง
"""

TAGS_METADATA = [
    {
        "name": "AI",
        "description": "ข้อมูล input สำหรับ AI Agent: `scan-inputs` สำหรับ Risk Scanner + Forecast "
                       "และ `optimize-inputs` สำหรับ Optimizer ทั้งสอง route อ่านข้อมูลอย่างเดียว",
    },
    {
        "name": "Risk Assessments",
        "description": "บันทึกผล Risk Scanner + Forecast ของแต่ละรอบสแกน (run)",
    },
    {
        "name": "Tasks",
        "description": "Task ที่ AI แนะนำให้ staff ทำ (ลดราคา / ส่งเข้าครัว / บริจาค / ทิ้ง)",
    },
    {
        "name": "Inventory Lots",
        "description": "Lot สินค้าในสต็อก รวมถึงการเปลี่ยน `ai_status` ระหว่างสแกน",
    },
    {
        "name": "Kitchen",
        "description": "ความจุครัว (ชั่วโมงต่อวัน) และการจองชั่วโมงครัว",
    },
    {
        "name": "Products",
        "description": "ข้อมูลหลักของสินค้า",
    },
]
