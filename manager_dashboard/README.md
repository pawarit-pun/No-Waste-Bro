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
