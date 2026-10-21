from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query

from schemas.decision import DecisionBatchCreate
from schemas.enums import DecisionStatus
from schemas.responses import DecisionCreateResponse, DecisionListResponse
from services.decisions import create_decisions, list_decisions

router = APIRouter(prefix="/optimization-decisions", tags=["Optimization Decisions"])


@router.post(
    "",
    status_code=201,
    response_model=DecisionCreateResponse,
    summary="บันทึกผลของ Optimizer",
    description="""
**ขั้นที่ 5 ของ AI Pipeline** Optimizer ส่งการตัดสินใจของแต่ละ lot มาเก็บไว้ก่อนส่งต่อให้ LLM
**ตัวเลขทั้งหมดของ task (ส่วนลด จำนวน สูตร batch partner due_by) กำหนดที่ขั้นนี้** LLM แก้ไม่ได้

### field ที่ต้องมีตาม `action_type`

| `action_type` | ต้องมี | ต้องว่าง |
| --- | --- | --- |
| `MARKDOWN` (ลดราคา) | `discount_pct` | `batch_count` |
| `KITCHEN_REPURPOSE` (ส่งเข้าครัว) | `target_recipe_id`, `batch_count`, `due_by` | `discount_pct`, `new_recommended_price` |
| `DONATE` (บริจาค) | `target_partner_id` (ประเภท DONATION / FOOD_BANK / CHARITY / COMMUNITY / TEMPLE) | `discount_pct`, `new_recommended_price`, `batch_count` |
| `ANIMAL_FEED` (ส่งทำอาหารสัตว์) | `target_partner_id` (ประเภท ANIMAL_FEED) | `discount_pct`, `new_recommended_price`, `batch_count` |
| `COMPOST` (ส่งทำปุ๋ยหมัก) | `target_partner_id` (ประเภท COMPOSTING) | `discount_pct`, `new_recommended_price`, `batch_count` |
| `ANAEROBIC_DIGESTION` (ส่งโรงก๊าซชีวภาพ) | `target_partner_id` (ประเภท ANAEROBIC_DIGESTION) | `discount_pct`, `new_recommended_price`, `batch_count` |
| `LANDFILL` (ส่งฝังกลบ) | `target_partner_id` (ประเภท LANDFILL) | `discount_pct`, `new_recommended_price`, `batch_count` |
| `DISCARD` (ทิ้งเองในร้าน) | – | `discount_pct`, `new_recommended_price`, `batch_count` |

### server ตรวจกับข้อมูลจริงก่อนบันทึก
- `assessment_id` ต้องมีอยู่จริง (server เติม `run_id` และ `lot_id` ให้จาก assessment)
- สินค้าต้องอนุญาต action นั้น (`allow_markdown` / `allow_kitchen_repurposing` / `allow_donation` /
  `allow_animal_feed` / `allow_composting` / `allow_anaerobic_digestion` / `allow_landfill`)
- ผลรวม `action_quantity` ของ lot เดียวกันในคำขอต้องไม่เกิน `current_quantity`
- **MARKDOWN:** ไม่ส่ง `new_recommended_price` = server คำนวณให้ ราคาใหม่ต้องไม่ต่ำกว่า `min_allowed_price`
- **KITCHEN_REPURPOSE:** สูตรต้อง active และสินค้าของ lot ต้องเป็นวัตถุดิบของสูตรนั้น
- **DONATE / ANIMAL_FEED / COMPOST / ANAEROBIC_DIGESTION / LANDFILL:** partner ต้อง active, **ประเภทตรงกับ action**,
  รับ category ของสินค้า และ lot ต้องเหลืออายุ ≥ `min_days_before_expiry` (ถ้าเป็น null ไม่เช็ค)

1 assessment มีได้หลาย decision (เช่น ลดราคาบางส่วน + ส่งครัวบางส่วน)
**ยังไม่จองครัวในขั้นนี้** จะจองตอน `POST /tasks`
""",
    responses={
        400: {"description": "DB ปฏิเสธการบันทึก"},
        422: {"description": "ข้อมูลไม่ครบตาม `action_type` หรือไม่ผ่านการตรวจกับข้อมูลจริง ข้อความบอกว่ารายการไหน ผิดเพราะอะไร"},
    },
)
def create_optimization_decisions(payload: DecisionBatchCreate):
    return create_decisions(payload.decisions, payload.optimizer_version)


@router.get(
    "",
    response_model=DecisionListResponse,
    summary="ดึงผลของ Optimizer ให้ LLM",
    description="""
**ขั้นที่ 6 ของ AI Pipeline** LLM ดึง decision ที่ยังไม่มี task ไปเขียนคำสั่งงาน (`staff_instructions`) และเหตุผล (`ai_reasoning`)

แต่ละ decision มี context ที่ใช้เขียนคำสั่งงานแนบมาด้วย:

| ส่วน | มีอะไร |
| --- | --- |
| `assessment` | ระดับความเสี่ยง, คาดว่าจะเหลือกี่หน่วย, เหลือกี่วัน |
| `lot` | จำนวนคงเหลือ, ราคาปัจจุบัน, วันหมดอายุ, **ตำแหน่งชั้นวาง** |
| `product` | ชื่อสินค้า, ประเภท, หน่วยนับ |
| `recipe` | ชื่อเมนู, ครัวที่ทำ, ได้กี่ชิ้น (เฉพาะ KITCHEN_REPURPOSE) |
| `partner` | ชื่อ partner, ประเภท, วัน/เวลารับของ, ผู้ติดต่อ (งานที่มี `target_partner_id`) |

- ไม่ส่ง `run_id` = รอบล่าสุดที่มี decision
- `status=PENDING` = เฉพาะที่ยังไม่มี task (ใช้ค่านี้ตอนส่งให้ LLM)
""",
)
def get_optimization_decisions(
    run_id: Optional[UUID] = Query(None, description="รอบสแกน ไม่ส่ง = รอบล่าสุดที่มี decision"),
    status: Optional[DecisionStatus] = Query(None, description="PENDING = ยังไม่มี task, TASK_CREATED = มี task แล้ว, ไม่ส่ง = ทั้งหมด"),
):
    return list_decisions(str(run_id) if run_id else None, status)
