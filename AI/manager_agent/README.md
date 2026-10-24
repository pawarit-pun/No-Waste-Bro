# Manager Agent

ผู้ช่วย AI ของผู้จัดการบน web dashboard ตอบเป็นภาษาไทย **เปลี่ยนข้อมูลเองไม่ได้** (ไม่อนุมัติ ไม่สร้าง task ไม่เปลี่ยนราคา)
Phase 1 = แชท + what-if, Phase 2 = แจ้งเตือนจากเหตุการณ์ / ตรวจทุก 1 ชม. + ข้อเสนอที่ผู้จัดการกดยืนยัน,
Phase 3 = ดูแลรายวัน (เริ่ม pipeline รอบเช้าเอง + Morning brief + Evening summary)
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
| `get_daily_report` | `GET /daily-reports` | เมื่อเช้าแผนเป็นยังไง / วันนี้ทำไปเท่าไร |
| `propose_action` | `proposals.build` (ตรวจกับข้อมูลตอนนี้) | การ์ด "รัน pipeline / คืน lot / ปิดครัว" ให้ผู้จัดการกดยืนยัน |

ตัวเลขทุกตัวคำนวณใน tool (`whatif.compare` คืนส่วนต่างให้แล้ว) โมเดลแค่เล่าผล
Optimizer ของ agent คิดทุก lot ของรอบสแกนล่าสุด รวม lot ที่สร้าง task แล้ว (`data.AGENT_OPT_CFG`) จึงอาจต่างจาก decision
ที่บันทึกตอนรัน pipeline ถ้าเวลาหรือข้อมูลเปลี่ยน (tool แจ้งใน `note` และแนบ `saved_decisions`)

## Phase 2: เหตุการณ์ + ตรวจตามเวลา (`events.py`)

โหมดนี้ไม่มีคนเฝ้า โค้ดตัดสินว่าจะอ่านอะไรและเสนออะไร (ขั้นตอนตายตัวต่อเหตุการณ์) LLM เขียนข้อความแจ้งเตือนอย่างเดียว
(`notify.py`: Nova -> Qwen -> ข้อความสำเร็จรูป ผ่าน guard เดียวกับแชท) ผลส่งเข้า server ครั้งเดียวที่ `POST /agent/runs`

| event_type | มาจาก | แจ้งเตือน | ข้อเสนอ |
| --- | --- | --- | --- |
| `TASK_REJECTED` | server ตอนพนักงานปฏิเสธ task | ใคร ปฏิเสธงานอะไร เพราะอะไร | `BLOCK_KITCHEN` + วางแผนใหม่ (งานครัว + เหตุผลเรื่องครัว) / `RUN_PIPELINE` (lot กลับเป็น IDLE) |
| `KITCHEN_FULL` | server ตอนอนุมัติแล้วจองครัวไม่ได้ | ครัวไหน วันไหน ต้องใช้ / เหลือกี่ ชม. + what-if ถ้าไม่มีครัวนั้น | - |
| `PIPELINE_FAILED` | server ตอนรอบ pipeline เป็น FAILED | ขั้นที่ล้ม + สาเหตุ | `RELEASE_LOTS` (lot ค้าง) / `RUN_PIPELINE` |
| `WATCH` | EventBridge ทุก 1 ชม. 07:00-22:00 / ปุ่ม Run demo | task เลยกำหนด, plan ใกล้ / เลยเวลาอนุมัติ, lot ค้าง PROCESSING | `RELEASE_LOTS` (lot ค้าง) |

- `dedupe_key` ต่อเรื่อง (เช่น `OVERDUE:<task_id>`) เรื่องเดิมไม่แจ้งซ้ำ เรื่องเดียวกันเกิน 3 รายการรวมเป็นแจ้งเตือนเดียว
- 1 รอบให้ LLM เขียนได้ไม่เกิน 5 ข้อความ ที่เหลือใช้ข้อความสำเร็จรูป
- ข้อเสนอ (`proposals.py`) ตรวจล่วงหน้าแล้วว่าทำได้ server ตรวจอีกรอบตอนกดยืนยัน

## Phase 3: ดูแลรายวัน (`daily.py`)

| event_type | มาจาก | ทำอะไร |
| --- | --- | --- |
| `MORNING_RUN` | EventBridge 07:30 | มี lot IDLE + ไม่มีรอบรันอยู่ -> `POST /ai/pipeline-runs` เอง (write เดียวที่ agent ทำเอง: ผลคือ plan ในคิว review) `AUTO_MORNING_RUN=false` = แจ้ง + ข้อเสนอ `RUN_PIPELINE` |
| `PIPELINE_SUCCEEDED` | server ตอนรอบ pipeline สำเร็จ | **Morning brief** ของรอบนั้น |
| `MORNING_BRIEF` | ปุ่ม Run demo | Morning brief ของรอบล่าสุดที่สำเร็จ (ไม่เริ่ม pipeline ใหม่) |
| `EVENING_SUMMARY` | EventBridge 21:30 / ปุ่ม Run demo | **Evening summary** |

- ตัวเลขทั้งหมดคำนวณในโค้ด: decision ต่อวิธี (หน่วย, kg จาก `net_content` กติกาเดียวกับ Optimizer), ขายต่อ / รีไซเคิล / ฝังกลบ kg,
  กำไรที่คาด + เทียบ baseline (Optimizer dry-run ของรอบสแกนเดียวกัน), ชั่วโมงครัว, task ที่ทำจริง (`actual_quantity_handled`)
- ความผิดปกติ: lot ค้าง, ฝังกลบ/ทิ้ง > 1.5 เท่าของค่าเฉลี่ย 7 รายงานก่อน, plan ครัวที่รอเกินชั่วโมงที่เหลือ, แผนแย่กว่า baseline,
  plan ต้องอนุมัติภายใน 60 นาที / ปิดวันแล้วยังมีงานเลยกำหนด, plan ที่ไม่ได้ตัดสิน, งานที่ถูกปฏิเสธ
- รายงานบันทึกใน `daily_reports` (1 แถวต่อวันต่อ kind ทับเมื่อรันซ้ำ) + แจ้งเตือนในกระดิ่ง แชทอ่านได้ด้วย tool `get_daily_report`

## Phase 4: Auto-approve (`autoapprove.py`)

ผู้จัดการเปิดที่หน้า Review queue (`PUT /agent/policies/auto-approve`) ค่าเริ่มต้นปิด เปิดแล้ว ก่อน `PIPELINE_SUCCEEDED` (ก่อน Morning brief)
และทุกรอบ `WATCH` (07:00-22:30 หรือปุ่มตรวจ) agent เลือก plan ที่ผ่าน **ทุกข้อ** แล้วเรียก `POST /agent/auto-approve`:

| รหัส | กติกา (ค่าเริ่มต้น) |
| --- | --- |
| `AA_ACTION` | วิธีอยู่ใน `actions` (MARKDOWN) เลือกได้แค่ MARKDOWN / DONATE / ANIMAL_FEED / COMPOST / ANAEROBIC_DIGESTION ไม่มีงานครัว ฝังกลบ ทิ้ง |
| `AA_DISCOUNT` / `AA_PRICE` | ลดไม่เกิน 30% และไม่ต่ำกว่า `min_allowed_price` |
| `AA_VALUE` | `action_quantity × current_selling_price` ไม่เกิน 2,000 บาท |
| `AA_NOT_BEST` | ไม่มีทางเลือกที่ทำได้ใน `alternatives` ที่กำไรคาดสูงกว่า |
| `AA_TEMPLATE` / `AA_EXPIRED` / `AA_DEADLINE` | ข้อความจาก LLM, lot ยังไม่หมดอายุ, เหลือเวลาก่อน `review_deadline` ≥ 30 นาที |
| `AA_UNDONE` | ผู้จัดการเคยย้อนการอนุมัติ plan นี้ = ไม่อนุมัติอีก |
| `AA_LOT` / `AA_LIMIT` | ทุก plan ที่รอของ lot ต้องผ่าน (อนุมัติทั้ง lot) และไม่เกิน 30 plan ต่อวัน (lot ที่ deadline ใกล้ก่อน) |

- โค้ดตัดสินทั้งหมด LLM ไม่มีส่วน server ตรวจซ้ำทุกข้อแล้วใช้ `approve()` เดิม (`reviewed_by` = ผู้จัดการเจ้าของกติกา, `approved_by_agent`)
- แจ้งเตือน "AI อนุมัติเอง N plan" + ลิงก์ไปแท็บ Approved ที่ย้อนได้ภายใน 15 นาที (task ยังไม่เริ่ม), Morning brief นับ `auto_approved`
- บน fixture 2026-10-16: lot ที่มีแต่ MARKDOWN 5 lot ผ่าน 4 (LOT-000020 มูลค่า 3,395 บาท เกินเพดาน) lot ที่มีงานครัว/ฝังกลบด้วยรอผู้จัดการ

## รัน

```bash
cd AI
python manager_agent/check_models.py                          # โมเดลเรียก tool ได้ไหม (22 ต.ค. ได้ TOOL_USE_OK ทั้งสองตัว)
python -m unittest manager_agent.tests.test_agent manager_agent.tests.test_events manager_agent.tests.test_daily manager_agent.tests.test_autoapprove -v   # เทสต์ offline ไม่ต้องมี AWS
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
- `events.py` เหตุการณ์ + ตรวจตามเวลา, `notify.py` เขียนข้อความแจ้งเตือน, `proposals.py` ข้อเสนอ 3 แบบ
- `daily.py` รอบเช้า + Morning brief + Evening summary
- `autoapprove.py` กติกา Auto-approve (เหมือน `server/services/auto_approve.py`)
