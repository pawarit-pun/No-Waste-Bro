"""ข้อความที่แสดงในหน้า Swagger UI (/docs) สำหรับ Team AI"""

APP_TITLE = "No-Waste-Bro API"
APP_VERSION = "0.3.0"

APP_DESCRIPTION = """
API สำหรับระบบลด Food Waste ใน Hypermarket ใช้ร่วมกันระหว่าง **AI Agent**, **Admin Dashboard** และ **Staff Mobile App**
ข้อมูลทั้งหมดอยู่บน Supabase ทุก route ขึ้นต้นด้วย `/api/v1`

## AI Pipeline Flow

AI Agent เรียก route ตามลำดับนี้ในการสแกน 1 รอบ (1 run)

| ขั้น | Route | ใครเรียก | ทำอะไร | ค่าที่ต้องเก็บไว้ใช้ต่อ |
| --- | --- | --- | --- | --- |
| 1 | `GET /ai/scan-inputs` | Risk Scanner + Forecast | ดึง lot ที่ยัง `IDLE` + ยอดขายของสินค้านั้น ไปประเมินความเสี่ยงและพยากรณ์ | `lot_id` ที่ได้ |
| 2 | `PATCH /inventory-lots/ai-status` | AI | ล็อก lot ที่ได้จากขั้น 1 เป็น `PROCESSING` | – |
| 3 | `POST /risk-assessments` | Risk Scanner | บันทึกผลความเสี่ยงของแต่ละ lot | `run_id`, `assessment_id` |
| 4 | `GET /ai/optimize-inputs?run_id=...` | Optimizer | ดึงข้อมูลไปตัดสินใจ (ลดราคา / เข้าครัว / บริจาค / ทิ้ง) | – |
| 5 | `POST /optimization-decisions` | Optimizer | บันทึกการตัดสินใจ **รวมตัวเลขทั้งหมด** | `decision_id` |
| 6 | `GET /optimization-decisions?status=PENDING` | LLM (RAG) | ดึง decision + context ไปเขียนคำสั่งงาน | `decision_id` |
| 7 | `POST /tasks` | LLM | สร้าง task จาก decision (ส่งแค่ข้อความ + priority) **server มอบหมาย staff ให้อัตโนมัติ** | `task_id` |
| 8 | `PATCH /inventory-lots/ai-status` | AI | เปลี่ยน lot ที่สแกนเสร็จเป็น `CHECKED` | – |

**lot แต่ละตัวถูกสแกนครั้งเดียว:** `scan-inputs` ส่งเฉพาะ lot ที่เป็น `IDLE` เมื่อเป็น `PROCESSING` / `CHECKED` แล้วจะไม่ถูกสแกนอีก

**หลักการ:** Optimizer เป็นเจ้าของตัวเลข LLM เป็นเจ้าของข้อความ
ตัวเลขใน task (ส่วนลด จำนวน สูตร batch partner due_by) คัดลอกจาก decision เสมอ LLM จึงแต่งตัวเลขเองไม่ได้

## หลังสร้าง task: Staff mobile app

server มอบหมาย task ให้ staff ที่ดูแลหมวดสินค้านั้นตั้งแต่ตอนสร้าง (`assigned_staff_id`)
mobile app subscribe Supabase Realtime เพื่อรู้ทันทีว่ามีงานใหม่ แล้วเรียก `GET /tasks?staff_id=...`

```js
supabase.channel('my-tasks')
  .on('postgres_changes',
      { event: '*', schema: 'public', table: 'ai_recommended_tasks',
        filter: 'assigned_staff_id=eq.STF-003' },
      () => refetchTasks())          // GET /api/v1/tasks?staff_id=STF-003
  .subscribe()
```

staff ทำงานตามลำดับ: `POST /tasks/{id}/accept` → `POST /tasks/{id}/complete` (หรือ `reject`)
`complete` อัปเดตสต็อกจริง: ลดราคาแยกเป็น lot ใหม่, งานครัวตัดวัตถุดิบทุกตัวแล้วสร้าง lot ผลผลิต, บริจาค/ทิ้งตัดสต็อก

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
        "name": "Optimization Decisions",
        "description": "ผลของ Optimizer (ตัวเลขทั้งหมดของ task) เก็บไว้ก่อนส่งให้ LLM เขียนคำสั่งงาน",
    },
    {
        "name": "Tasks",
        "description": "Task ที่ AI แนะนำให้ staff ทำ (ลดราคา / ส่งเข้าครัว / บริจาค / ทิ้ง) ระบบมอบหมาย staff ตามหมวดสินค้า และมีคิวงานสำหรับ mobile app",
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
        "name": "Staff",
        "description": "พนักงาน 2 role: MANAGER (web dashboard) และ STAFF (mobile app) ใช้กับหน้าเลือกผู้ใช้ (ยังไม่มี login)",
    },
    {
        "name": "Products",
        "description": "ข้อมูลหลักของสินค้า",
    },
]
