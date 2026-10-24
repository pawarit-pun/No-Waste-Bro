# Manager Dashboard

React + TypeScript + Tailwind CSS v4 (Vite)

```bash
cd manager_dashboard
npm install
npm run dev      # http://localhost:5173
```

ค่า environment อยู่ใน `.env` (คัดลอกจาก `.env.example`)

| ตัวแปร | ค่า |
| --- | --- |
| `VITE_API_BASE_URL` | URL ของ FastAPI บน AWS (`.../api/v1`) |

## Deploy (S3 + CloudFront)

เว็บเป็น static site (`npm run build` → `dist/`) เก็บใน S3 bucket แบบ private และเปิดผ่าน CloudFront (HTTPS)
resource อยู่ใน SAM stack เดียวกับ API (`server/template.yaml`: `DashboardBucket`, `DashboardOAC`, `DashboardDistribution`, `DashboardBucketPolicy`)

```bash
# 1. สร้าง / อัปเดต bucket + CloudFront (คำสั่ง deploy เดิมของ server, ครั้งแรก CloudFront ใช้เวลาประมาณ 5-10 นาที)
cd server && ./scripts/build_lambda.sh && sam deploy --parameter-overrides \
  SupabaseServiceRoleKey="$(grep '^SUPABASE_SERVICE_ROLE_KEY=' .env | cut -d= -f2-)" \
  WorkerImageUri="$(cat ../AI/pipeline/.last_image_uri)"

# 2. build + อัปโหลดเว็บ + ล้าง cache (ทำทุกครั้งที่แก้ dashboard)
cd .. && ./manager_dashboard/scripts/deploy_dashboard.sh
```

- URL ของเว็บ = output `DashboardUrl` (`sam list stack-outputs`)
- ค่า `VITE_*` ใน `.env` ถูกฝังตอน build: แก้ `.env` แล้วต้องรันสคริปต์ใหม่
- `assets/*` cache 1 ปี (ชื่อไฟล์มี hash), `index.html` เป็น `no-cache` จึงเห็นเวอร์ชันใหม่ทันทีหลัง deploy
- refresh หน้าอื่นได้ (`/review`, `/kitchen`): CloudFront ส่ง `index.html` แทน 403 / 404 ให้ React Router
- `sam delete` จะลบ stack ไม่ผ่านถ้า bucket ยังมีไฟล์: `aws s3 rm s3://<DashboardBucketName> --recursive` ก่อน
- ยังไม่ได้ทำ (prototype): CORS ของ API ยังเป็น `*` (หลัง demo ตั้ง `CorsOrigins=https://<cloudfront-domain>,http://localhost:5173`),
  WAF กรอง IP (ต้องสร้างใน us-east-1) และ custom domain (ต้องมี certificate ใน ACM us-east-1)

## ผู้ช่วย AI (แชท)

ปุ่ม **ผู้ช่วย AI** มุมขวาบนเปิดแผงแชทได้จากทุกหน้า (ปิดด้วย Esc) แผงชิดขวาไม่บังเนื้อหา drawer ของหน้าอื่นเปิดข้างแผงได้
ปุ่ม **ถาม AI** ในตาราง Inventory และใน drawer ของ Review queue เปิดแผงแล้วถามเรื่อง lot นั้นทันที

- เรียก `POST /agent/ask` (รอได้ 35 วินาที) และ `POST /agent/warmup` ตอนเปิดแผงครั้งแรก
- ส่ง `context.page` (หน้าที่เปิดอยู่) และ `context.lot_id` (lot ที่กำลังคุยถึง) ไปด้วย
- บทสนทนาเก็บใน sessionStorage ล่าสุด 10 รอบ (ปิดแท็บแล้วหาย) ปุ่มถังขยะล้างบทสนทนา
- การ์ดใต้คำตอบ (`artifacts`) แสดงตัวเลขจาก tool โดยตรง: what-if, เหตุผลของแผนต่อ lot, รายการ lot / task

ไฟล์: `src/components/agent/` (`AgentProvider` state + เรียก API, `AgentPanel`, `AgentMessage`, `WhatIfCard`,
`LotExplainCard`, `AskAgentButton`), `src/lib/agent.ts`, `src/types/agent.ts`

หน้า Agent log เปลี่ยนชื่อเป็น **Pipeline runs** (`/pipeline-runs`, ลิงก์เดิม `/agent-log` redirect ให้)

### แจ้งเตือนและข้อเสนอ (Phase 2)

- **กระดิ่ง** ใน header: แจ้งเตือนจากผู้ช่วย AI (task ถูกปฏิเสธ, ครัวเต็มตอนอนุมัติ, pipeline ล้ม, ตรวจทุก 1 ชม.) อัปเดตแบบ realtime
  จากตาราง `agent_notifications` / `agent_proposals` และโหลดใหม่ทุก 60 วินาที มีปุ่ม "ตรวจตอนนี้" และ "อ่านทั้งหมด"
- **การ์ดข้อเสนอ** (ในกระดิ่งและในแชท): ปุ่ม "ยืนยัน" = `POST /agent/proposals/{id}/execute` ด้วย `staff_id` ของผู้จัดการที่เลือกไว้
  server ทำตามหลังตรวจกับข้อมูลล่าสุด ("ไม่ทำ" = `/dismiss`)
- **หน้า Run demo**: การ์ด "Manager Agent check" ปุ่ม Check now (`POST /agent/watch`) + แจ้งเตือนล่าสุด 5 รายการ

ไฟล์: `src/components/agent/NotificationBell.tsx`, `ProposalCard.tsx`, `AgentWatchCard.tsx`, `useNotifications.ts`

## หน้า Kitchen (`/kitchen`, กลุ่ม MONITOR)

ข้อมูลจาก `GET /kitchen-overview?days_ahead=1` (อ่านอย่างเดียว) โหลดใหม่เมื่อ task / plan / pipeline เปลี่ยน และทุก 60 วินาที

- การ์ดครัวแต่ละแห่ง: ชั่วโมงวันนี้ (จองแล้ว / ว่าง) + แถบลายทาง = plan ที่รออนุมัติ (ยังไม่ได้จอง) แดงเมื่อเกินชั่วโมงที่เหลือ,
  แถบของพรุ่งนี้, จำนวนงาน To do / Cooking / Done / Waiting approval, ปุ่มถาม AI "ถ้าครัวนี้ปิดวันนี้"
- Kitchen jobs: วันนี้ / พรุ่งนี้ กรองตามครัว (เมนู, lot วัตถุดิบ, batch, ชั่วโมง, พนักงาน, สถานะ)
- Menu demand: ความต้องการเมนูของรอบพยากรณ์ล่าสุด (ทำไม AI ส่งวัตถุดิบเข้าครัว และทำได้ไม่เกิน "Make more")

ไฟล์: `src/pages/kitchen/`, `src/types/kitchen.ts`

## หน้า Overview (Phase 3)

- การ์ดตัวเลขสด: lot เสี่ยง, plan รออนุมัติ, task ค้าง / เลยกำหนด, ชั่วโมงครัววันนี้
- **Morning brief** ของวันนี้ (agent เริ่ม pipeline เอง 07:30 แล้วเขียนเมื่อรอบสำเร็จ): ข้อความสรุป, ความผิดปกติ, แผนต่อวิธี (หน่วย / kg / กำไรที่คาด),
  แถบ kg ขายต่อ / รีไซเคิล / ฝังกลบ, ส่วนต่างจาก baseline
- **Evening summary** (21:30): งานที่ทำจริง, kg ที่จัดการจริงแยกทาง
- ประวัติ 7 วันจาก `GET /daily-reports` (DEMO_DATE ตรึงวัน = แถวเดียว) อัปเดตแบบ realtime จากตาราง `daily_reports`
- หน้า Run demo การ์ด Manager Agent: ปุ่ม Morning brief now / Evening summary now (`POST /agent/daily/{morning|evening}`)

ไฟล์: `src/pages/overview/`, `src/types/daily.ts`

## AI auto-approve (Phase 4, หน้า Review queue)

- แถบ **AI auto-approve** ใต้หัวข้อ: Turn on / off, Settings (วิธีที่อนุมัติเองได้, เพดานส่วนลด / มูลค่า, เวลาก่อน deadline, จำนวนต่อวัน, เวลาย้อน)
  และจำนวนที่ AI อนุมัติวันนี้ คนที่กดบันทึกเป็นเจ้าของกติกา
- แท็บ Approved: ป้าย **Approved by AI** + เหตุผลตามกติกา ใน drawer มีปุ่ม **Undo AI approval** นับถอยหลัง (ย้อนได้ถ้า staff ยังไม่เริ่มงาน)
- plan ที่ถูกย้อนกลับมา Waiting มีข้อความว่า AI จะไม่อนุมัติอีก, กระดิ่งมีลิงก์ไปแท็บ Approved, Morning brief บอกจำนวนที่ AI อนุมัติวันนี้

ไฟล์: `src/pages/review/AutoApprovePanel.tsx`, `ReviewTable.tsx`, `ReviewDrawer.tsx`, `src/lib/agent.ts`, `src/types/agent.ts`

## หน้า Task log (`/task-log`, กลุ่ม AUDIT)

- task ที่อนุมัติแล้ว (ผู้จัดการหรือ AI auto-approve) ทุกสถานะ จาก `GET /task-log`: วันนี้ หรือ 7 วันล่าสุด + งานที่ยังไม่จบทั้งหมด
- การ์ดนับ Pending / In progress / Completed / Rejected / Overdue (กดเพื่อกรอง) + กรองวิธี และพนักงาน
- ตาราง: lot, งาน, พนักงาน, ผู้อนุมัติ (หรือป้าย Approved by AI), สถานะ, กำหนดเสร็จ, อัปเดตล่าสุด (เช่น "Done 11:05 · 8/10")
- กดแถว → drawer: timeline อนุมัติ → ส่งให้พนักงาน → เริ่ม → เสร็จ / ปฏิเสธ (เหตุผล, จำนวนจริง, เวลาที่ใช้), คำสั่งงาน, กำไรที่คาด
- realtime จาก `ai_recommended_tasks` + `task_events` (ต้องรัน `server/scripts/task_events.sql` ถึงจะมีเวลารับงาน / ปฏิเสธ)
- drawer ของ plan ที่อนุมัติแล้วใน Review queue แสดงสถานะ task + ลิงก์ "Open in Task log", การ์ด Open staff tasks ใน Overview ลิงก์มาที่หน้านี้

ไฟล์: `src/pages/task-log/`, `src/types/taskLog.ts`, `src/components/ui/TaskStatusBadge.tsx`

## หน้า Pickups (`/pickups`, กลุ่ม MONITOR)

- ตารางรอบรับของของ partner 7 วัน (วันนี้ + 6 วัน) จาก `GET /pickup-schedule`: แถว = partner (ประเภท, วัน/เวลารับ, ผู้ติดต่อ), คอลัมน์ = วัน
  ช่องสีเทา = วันที่ partner ไม่มา, ช่องรอบรับแสดง kg เทียบความจุ (สีตามประเภท = อนุมัติแล้ว, เหลือง = รออนุมัติ) และงานที่พร้อมแล้ว
- การ์ด: รอบถัดไปที่มีของ, รอบวันนี้, kg ที่ออกจากร้านวันนี้แยกตามทาง, รอบที่มีปัญหา (เกินความจุ / ต่ำกว่าขั้นต่ำ / ถึงเวลาแล้วงานยังไม่เสร็จ)
- กดช่อง → drawer: รายการของที่ต้องส่ง (lot, จำนวน, kg, ตำแหน่ง, สถานะ task, พนักงาน), ค่าใช้จ่ายโดยประมาณ, เบอร์ partner, ลิงก์ Task log / Review queue
- realtime จาก `ai_recommended_tasks` + `pending_tasks` และโหลดใหม่ทุก 60 วินาที

ไฟล์: `src/pages/pickups/`, `src/types/pickups.ts`
