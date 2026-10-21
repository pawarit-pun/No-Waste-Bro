# LLM Task Agent

เปลี่ยน decision จาก Optimizer เป็น plan ของ task (priority, คำสั่งงาน, ขั้นตอนทีละข้อ, เหตุผลสำหรับผู้จัดการ)
แล้วส่งเข้าคิวรออนุมัติ **ไม่มีการอนุมัติอัตโนมัติ** task ถึงมือพนักงานเมื่อผู้จัดการกดอนุมัติใน dashboard เท่านั้น

```
GET /optimization-decisions?status=PENDING
  -> Build Facts      ตัวเลขทุกตัวมาจาก decision ไม่ใช่ AI
  -> Retrieve SOP     Bedrock Knowledge Base กรอง action_type = action หรือ ALL
  -> REQUIRED_STEPS   โค้ดกำหนด title + ลำดับขั้น + ข้อมูลที่แต่ละขั้นต้องมี
  -> LLM              Nova Lite เขียน detail ของแต่ละขั้น + ai_reasoning
  -> Validate         ตัวเลข / title / ข้อมูลบังคับ / ชื่อ SOP / พ.ศ. / ความยาว / เงื่อนไขหยุด
       ไม่ผ่าน -> Nova Lite แก้ 1 ครั้ง -> Qwen3 Next -> ข้อความมาตรฐาน (ทุก decision ได้ plan เสมอ, model_used = TEMPLATE)
  -> POST /pending-tasks   ส่ง plan + model_used เข้าคิว (WAITING) แยก batch: งานทั่วไป 1 ก้อน, งานครัวแยกตามครัว + วัน
  -> PATCH /inventory-lots/ai-status   lot ที่ส่ง plan ครบทุก decision -> CHECKED (เรียกครั้งเดียว)
  (ผู้จัดการ) POST /pending-tasks/approve -> server สร้าง task, มอบหมายพนักงาน, จองครัว
  -> report JSON      audit trail ทุกรอบ
```

## ใครทำอะไร

| ส่วนของ task | ใครทำ |
| --- | --- |
| `priority` | โค้ด (heuristic ของ Prototype ไม่ใช่นโยบายร้านจริง) |
| `staff_instructions` | โค้ด (template ต่อ action) |
| title และลำดับของ `instruction_steps` | โค้ด (`REQUIRED_STEPS`) |
| `detail` ของแต่ละขั้น, `ai_reasoning` | LLM แล้วผ่าน validator |

## ไฟล์

| ไฟล์ | หน้าที่ |
| --- | --- |
| `config.py` | ค่าตั้งต้นทั้งหมด อ่านจาก env / `.env` |
| `models.py` | รูปแบบ decision และ task (ขีดจำกัดตรงกับ server) |
| `api_client.py` | GET decision, POST plan เข้าคิว (`/pending-tasks`), PATCH ai_status ของ lot |
| `facts.py` | Build Facts |
| `steps.py` | REQUIRED_STEPS, staff_instructions, ข้อความมาตรฐาน, priority |
| `knowledge_base.py` | ค้น SOP จาก Knowledge Base |
| `llm.py` | prompt, เรียก Bedrock Converse, parse JSON |
| `validate.py` | ตรวจคำตอบ LLM |
| `task_generator.py` | ประกอบ task จากส่วนของโค้ดและส่วนที่เขียนแล้ว |
| `agent.py` | ร้อยทุกขั้น, retry, แยก batch, POST plan เข้าคิว, ตั้ง lot เป็น CHECKED, report |
| `main.py` | รันจากเครื่อง / CloudShell |
| `handler.py` | entry point ของ AWS Lambda |
| `mock_data.py` | decision ตัวอย่างครบ 4 action สำหรับทดสอบ |
| `tests/test_agent.py` | test แบบ offline (ไม่ต้องต่อ AWS) |

## ติดตั้ง

```bash
python -m venv .venv313
.venv313\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

ค่าใน `.env.example` เป็นค่าเริ่มต้นอยู่แล้ว ใส่เฉพาะที่ต้องการเปลี่ยน
AWS credentials ไม่ใส่ใน `.env` ให้ใช้ `aws configure`, CloudShell หรือ role ของ Lambda

ใช้ได้เฉพาะ model ID แบบ On-demand ที่ไม่ขึ้นต้นด้วย `us.` หรือ `global.` เพราะ SCP ของ sandbox บล็อก region อื่น

## วิธีรัน

ค่าเริ่มต้นคือ **ดูอย่างเดียว ไม่ POST** ต้องใส่ `--post` จึงจะส่ง plan เข้าคิวรออนุมัติจริง

```bash
# 1. test (ไม่ต้องต่อ AWS)
python tests/test_agent.py

# 2. offline ล้วน: ดูโครง task จาก mock_data
python main.py --source mock --no-llm --no-kb

# 3. mock_data + Knowledge Base + LLM จริง (ต้องมีสิทธิ์ AWS)
python main.py --source mock

# 4. decision จริงจาก server: ดูก่อน แล้วค่อย POST
python main.py --source api
python main.py --source api --post
```

ตัวเลือกอื่น: `--run-id`, `--limit N`, `--now 2026-10-19T08:00:00+07:00`

ผลแต่ละรอบอยู่ใน `output/task_agent_<เวลา>.json` มี task ทุกตัว, โมเดลที่ใช้, คำตอบดิบของโมเดล,
ข้อผิดพลาดที่ validator เจอ, SOP ที่ดึงมา และผล POST (`review_ids` ของ plan ที่เข้าคิว, `summary.plans_queued`)

## Deploy เป็น Lambda

- Runtime Python 3.12, handler `handler.lambda_handler`, timeout 300 วินาที, memory 256 MB
  (API Gateway timeout ~29 วินาที จึงต้องเรียกแบบ async หรือจาก scheduler ไม่ใช่ endpoint ที่รอผล)
- ต้อง package `pydantic`, `httpx`, `python-dotenv` ไปด้วย (`boto3` มีใน runtime แล้ว)
- env: ตาม `.env.example` และตั้ง `OUTPUT_DIR=/tmp/task_agent`
- event (ไม่ใส่ก็ได้): `{"run_id": "...", "dry_run": false, "limit": 5}`
- สิทธิ์ของ execution role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "bedrock:InvokeModel",
     "Resource": ["arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0",
                  "arn:aws:bedrock:us-east-1::foundation-model/qwen.qwen3-next-80b-a3b"]},
    {"Effect": "Allow", "Action": "bedrock:Retrieve",
     "Resource": "arn:aws:bedrock:us-east-1:566254752430:knowledge-base/N0NJ2UIEIU"}
  ]
}
```

## ข้อจำกัดที่รู้แล้ว

- `priority` เป็น heuristic ของ Prototype ไม่ใช่นโยบายร้านจริง
- `GET /optimization-decisions` ส่ง `partner` มาเฉพาะ DONATE งาน DISCARD ที่มี partner จึงเห็นแค่รหัส ไม่เห็นชื่อ
- `POST /pending-tasks` ส่งทั้ง batch หรือไม่ส่งเลย ถ้า batch ล้ม (เช่น decision ไม่ใช่ PENDING แล้ว 409) decision ของ batch นั้นยังเป็น PENDING และ lot นั้นยังเป็น PROCESSING (อยู่ใน `lot_status.pending_lots` ของ report)
- ครัวถูกจองตอนผู้จัดการอนุมัติ ไม่ใช่ตอน agent ส่ง plan ถ้าครัวเต็มผู้จัดการจะเห็น error ตอนกดอนุมัติ
- `--source api` แบบไม่ใส่ `--post` จะไม่ PATCH lot แต่แสดงว่าจะตั้ง lot ไหนเป็น CHECKED
- งานกำจัดผ่าน partner (`ANIMAL_FEED` / `COMPOST` / `ANAEROBIC_DIGESTION` / `LANDFILL`) ใช้ขั้นตอนและ SOP ชุดเดียวกับ `DISCARD` ที่มี partner (KB ยังไม่มีเอกสารที่ติด tag 4 ค่านี้)
- `DISCARD` = ทิ้งเองในร้าน ไม่มี partner
