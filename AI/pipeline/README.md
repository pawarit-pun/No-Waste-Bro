# AI Pipeline (main pipeline)

ต่อ AI ทั้ง 3 ส่วนให้รันตามลำดับด้วยคำสั่งเดียว ใช้โค้ดเดิมของแต่ละทีม ไม่ได้ก๊อปโค้ด

```
POST /api/v1/ai/pipeline-runs  (server ตอบ 202 ทันที)
        │ invoke แบบไม่รอผล
        ▼
PipelineWorkerFunction (Lambda, container image จากโฟลเดอร์นี้)
  1. SCAN      risk_forecaster/run_scan.py --source api              → run_id, lot HIGH / CRITICAL
  2. OPTIMIZE  food_waste_optimizer/run_optimize.py --run-id <run_id> → decision
  3. TASKS     llm-task-agent/main.py --source api --run-id <run_id> --post → task (mobile app เด้งผ่าน Realtime)
        │ ทุกขั้น PATCH /ai/pipeline-runs/{id}
        ▼
ตาราง pipeline_runs: QUEUED → RUNNING → SUCCEEDED / FAILED
```

- `run_id` ที่ Risk Scanner สร้างคือตัวร้อยทั้ง 3 ขั้น (assessment, decision, task ใช้ค่าเดียวกัน)
- แต่ละขั้นรันเป็น process แยก (ชื่อ module ของ 3 โปรเจกต์ชนกัน เช่น `models.py` กับ `models/`) แล้ว worker อ่านผลจากไฟล์ที่สคริปต์เขียนไว้ใน `OUTPUT_DIR`
- จบก่อนครบได้ = `SUCCEEDED` + `message`: ไม่มี lot IDLE, ไม่มี lot HIGH / CRITICAL, Optimizer ได้ 0 decision
- ทุกขั้นใช้ `API_BASE_URL` และเวลาเดียวกัน: ถ้าตั้ง `DEMO_DATE` worker ส่ง `DEMO_TIME` (Optimizer) และ `AGENT_NOW` (LLM) เป็นเวลาจริงตอนเริ่มรอบ

## ไฟล์

| ไฟล์ | หน้าที่ |
| --- | --- |
| `worker.py` | ตัวคุมลำดับ: `lambda_handler` (บน AWS) และ `python worker.py` (debug ในเครื่อง) |
| `Dockerfile` | image ของ Lambda (Python 3.12, arm64) + เทรน Forecaster ตอน build |
| `requirements.txt` | library ของทั้ง 3 ส่วน (ล็อกเวอร์ชัน) |
| `build_worker.sh` | build + push image ขึ้น ECR แล้วบันทึก `ImageUri` ลง `.last_image_uri` |
| `../.dockerignore` | ไม่เอา `.venv`, `output`, `.env`, `*.pkl`, `tests` เข้า image |

## Deploy (ครั้งแรก และทุกครั้งที่โค้ด AI เปลี่ยน)

ต้องมี: Docker Desktop ที่เปิดอยู่, `aws configure`, SAM CLI

```bash
# รันจากโฟลเดอร์ No-Waste-Bro: && หยุดทันทีถ้าขั้นไหนพัง (build ไม่ผ่าน = ไม่ deploy)
# 1) build + push image (ราว 5-10 นาทีครั้งแรก รวมเทรน Forecaster)
# 2) deploy server + worker ใน stack เดียวกัน (no-waste-bro-api)
./AI/pipeline/build_worker.sh && cd server && ./scripts/build_lambda.sh && sam deploy --parameter-overrides \
  SupabaseServiceRoleKey="$(grep '^SUPABASE_SERVICE_ROLE_KEY=' .env | cut -d= -f2-)" \
  WorkerImageUri="$(cat ../AI/pipeline/.last_image_uri)" \
  DemoDate=2026-10-16
```

- โค้ด AI ไม่เปลี่ยน แก้แค่ server: ข้าม `build_worker.sh` ได้ (ใช้ image เดิมจาก `.last_image_uri`)
- SAM ต้องรู้ ECR repository ของ worker: ตั้งไว้ใน `server/samconfig.toml` (`image_repositories`) แล้ว ไม่ต้องใส่ `--image-repositories` เอง
- build ล้มเพราะ `Read timed out` ตอน `pip install` = เน็ตไป PyPI ช้า รันซ้ำได้เลย (ขั้นก่อนหน้าใช้ cache)

- **ทุก `sam deploy` ต้องส่ง `WorkerImageUri`** (ไม่มีค่าเริ่มต้น) ใช้ค่าจาก `.last_image_uri` ถ้าโค้ด AI ไม่ได้เปลี่ยน
- `DemoDate` ใช้ร่วมกันทั้ง server และ worker ต้องตรงกับวันที่ของข้อมูล demo ไม่งั้น Optimizer จะไม่รับรอบสแกน (exit 3)
- worker: memory 3008 MB, timeout 900 วินาที, ไม่ retry อัตโนมัติ, สิทธิ์ Bedrock (Nova Lite, Qwen3, Knowledge Base `N0NJ2UIEIU`)

## ใช้งาน

```bash
B=https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1
curl -X POST $B/ai/pipeline-runs -H "Content-Type: application/json" -d '{"stop_after": "TASKS"}'
curl $B/ai/pipeline-runs/<pipeline_run_id>      # ดูสถานะ (หรือ Swagger: /docs → AI Pipeline)
```

| `stop_after` | ทำถึง |
| --- | --- |
| `SCAN` | สแกนอย่างเดียว (บันทึกผลสแกน) |
| `OPTIMIZE` | สแกน + บันทึก decision (ยังไม่สร้าง task) |
| `TASKS` (ค่าเริ่มต้น) | ครบ 3 ขั้น สร้าง task ให้ staff |

⚠ ทุกโหมดเขียนข้อมูลจริง (สถานะ lot, ผลสแกน, decision, task, จองชั่วโมงครัว) ซ้อม demo แล้วล้างด้วย
`python -m scripts.demo reset` ในโฟลเดอร์ server หรือ `select demo_reset();`

## Debug

| อยากรู้ | ดูที่ |
| --- | --- |
| พังขั้นไหน เพราะอะไร | `GET /ai/pipeline-runs/{id}` → `error`, `steps.<ขั้น>.log_tail`, `exit_code` |
| log เต็ม | CloudWatch Logs `/aws/lambda/<PipelineWorkerName>` (`sam list stack-outputs`) หรือ `sam logs -n PipelineWorkerFunction --tail` |
| รันในเครื่องทีละขั้น | ด้านล่าง |

รันในเครื่อง (ใช้ venv ของแต่ละโฟลเดอร์ ยิง API บน AWS):

```bash
cd AI/pipeline
export PYTHON_SCAN=../risk_forecaster/.venv/bin/python
export PYTHON_OPTIMIZE=../food_waste_optimizer/.venv/bin/python
export PYTHON_TASKS=../llm-task-agent/.venv313/bin/python
export DEMO_DATE=2026-10-16
python3 worker.py --stop-after OPTIMIZE        # ไม่อัปเดต pipeline_runs (ไม่ได้ส่ง --pipeline-run-id)
```

ผลของแต่ละขั้นอยู่ที่ `AI/pipeline/output/<เวลา>/{scan,optimize,tasks}/`

| exit code ของ OPTIMIZE | ความหมาย |
| --- | --- |
| 1 | server error / ต่อ server ไม่ได้ |
| 2 | แผนไม่ผ่านการตรวจกฎ (ไม่ได้บันทึก) |
| 3 | ไม่มีรอบสแกนที่พร้อม: วันที่สแกนไม่ตรงกับ `DEMO_DATE` ของ server |

TASKS ที่บาง batch POST ไม่ผ่าน (เช่น ครัวเต็ม 409) = `FAILED` แต่ task ของ batch อื่นถูกสร้างแล้ว
และ decision ของ batch ที่พังยังเป็น `PENDING` ให้ผู้จัดการดู
