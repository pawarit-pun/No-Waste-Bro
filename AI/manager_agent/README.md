# Manager Agent (Phase 1)

ผู้ช่วย AI ของผู้จัดการบน web dashboard ตอบเป็นภาษาไทย **อ่านข้อมูลอย่างเดียว** (ไม่อนุมัติ ไม่สร้าง task ไม่เปลี่ยนราคา)
รันเป็น Lambda `ManagerAgentFunction` จาก image เดียวกับ AI pipeline worker (`AI/pipeline/Dockerfile`)
server เรียกผ่าน `POST /api/v1/agent/ask` แบบรอผล

```
คำถาม + บทสนทนา + หน้าที่เปิดอยู่
  -> Bedrock Converse (Nova Lite) + toolConfig
  -> โมเดลขอเรียก tool -> รัน tool (GET ของ server / Optimizer dry-run) -> ส่งผลกลับ   (สูงสุด 8 ครั้ง)
  -> คำตอบ -> guard (ตัวเลข วันที่ เวลา รหัส lot ต้องมาจากผล tool)
       ไม่ผ่าน -> Nova แก้ 1 ครั้ง -> Qwen3 Next ทำต่อจากผล tool เดิม -> ข้อความสำเร็จรูป + การ์ด
```

| tool | ข้อมูลจาก | ใช้ตอบ |
| --- | --- | --- |
| `get_store_snapshot` | `GET /inventory-lots`, `/tasks`, `/pending-tasks`, `/ai/pipeline-runs` | วันนี้มีอะไรด่วน |
| `list_at_risk_lots` | `GET /inventory-lots` (ผลสแกนล่าสุด) | lot ไหนเสี่ยง |
| `get_lot` | `GET /inventory-lots`, `/tasks`, `/pending-tasks` | lot นี้เป็นยังไง |
| `list_tasks` | `GET /tasks` | งานไหนค้าง / เลยกำหนด |
| `get_plan` | `GET /ai/optimize-inputs` + `run_optimizer` (dry-run) | แผนวันนี้ดีกว่าเดิมแค่ไหน |
| `explain_decision` | เหมือน `get_plan` + `GET /optimization-decisions` | ทำไมเลือกวิธีนี้ |
| `what_if` | `run_optimizer` 2 รอบ (จริง / แก้ข้อมูล) | ถ้าไม่ลดราคา / partner ไม่มา / ครัวว่าง x ชม. / ยอดขาย x เท่า |
| `search_sop` | Bedrock Knowledge Base | ขั้นตอน / นโยบายร้าน |

ตัวเลขทุกตัวคำนวณใน tool (`whatif.compare` คืนส่วนต่างให้แล้ว) โมเดลแค่เล่าผล
Optimizer ของ agent คิดทุก lot ของรอบสแกนล่าสุด รวม lot ที่สร้าง task แล้ว (`data.AGENT_OPT_CFG`) จึงอาจต่างจาก decision
ที่บันทึกตอนรัน pipeline ถ้าเวลาหรือข้อมูลเปลี่ยน (tool แจ้งใน `note` และแนบ `saved_decisions`)

## รัน

```bash
cd AI
python manager_agent/check_models.py                          # โมเดลเรียก tool ได้ไหม (22 ต.ค. ได้ TOOL_USE_OK ทั้งสองตัว)
python -m unittest manager_agent.tests.test_agent -v          # เทสต์ offline (fixture mock_v4 + LLM สคริปต์) ไม่ต้องมี AWS
python -m manager_agent "วันนี้มีอะไรด่วนบ้าง"                  # ถามจริง (ต้องมี AWS credentials ของ Bedrock us-east-1)
python -m manager_agent "ถ้าไม่ลดราคาเลยจะเป็นยังไง" --page review
```

env: `API_BASE_URL`, `DEMO_DATE`, `BEDROCK_REGION` (us-east-1), `BEDROCK_KB_ID`, `PRIMARY_MODEL`, `FALLBACK_MODEL`,
`AGENT_BUDGET_S` (25), `AGENT_MAX_TOOL_CALLS` (8) ดู `config.py`

## ไฟล์

- `handler.py` Lambda entry (`{"warmup": true}` = ปลุก container)
- `agent.py` วงรอบ tool calling + ลำดับ fallback
- `tools.py` tool ทั้งหมด + คำแปลรหัสเหตุผลของ Optimizer, `whatif.py` สถานการณ์จำลอง, `data.py` อ่าน API + cache ต่อคำถาม
- `guard.py` ตรวจคำตอบ + ตัด `<thinking>` ของ Nova, `prompts.py` system prompt ภาษาไทย, `llm.py` Bedrock
