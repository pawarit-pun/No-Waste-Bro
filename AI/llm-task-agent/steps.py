"""Task structure decided by code, not by the LLM.

- REQUIRED_STEPS: step titles, their order, and the data each step's detail must contain
- staff_instructions: one-line instruction built from a template
- fallback detail / reasoning: standard text used when the LLM output fails validation
- priority: prototype heuristic (not a real store policy)
"""

from dataclasses import dataclass, field
from datetime import datetime

from facts import ACTION_TH, Facts

STOP_TEXT = "ถ้าพบสินค้าเสียหาย จำนวนไม่ตรง หรือข้อมูลไม่ตรงกับระบบ ให้หยุดและแจ้งหัวหน้า"


@dataclass
class Must:
    """Data a step's detail must contain. kind 'num' = this number, 'text' = this text."""
    label: str
    value: str
    kind: str = "text"


@dataclass
class StepSpec:
    title: str
    fallback: str
    must: list[Must] = field(default_factory=list)


def _must(label: str, value: str | None, kind: str = "text") -> list[Must]:
    return [Must(label, value, kind)] if value else []


def _locate_step(f: Facts) -> StepSpec:
    where = f"ไปที่ {f.location} " if f.location else f"{f.location_or_check}ว่าเก็บไว้ที่ไหน แล้วไป"
    return StepSpec(
        "ยืนยันสินค้า lot จำนวน และตำแหน่ง",
        f"{where}หา{f.product_name} lot {f.lot_id} "
        f"ตรวจว่ามีอย่างน้อย {f.qty} {f.unit} และตรงกับระบบ",
        _must("lot", f.lot_id) + _must("ตำแหน่ง", f.location_or_check) + _must("จำนวน", f.qty, "num"),
    )


def _markdown_steps(f: Facts) -> list[StepSpec]:
    price = f"{f.new_price} บาท" if f.new_price else "ตามราคาในระบบ"
    return [
        StepSpec(
            "ตรวจสภาพสินค้าและสถานะระงับ",
            "ตรวจว่าสินค้าและบรรจุภัณฑ์ไม่เสียหาย และไม่มีป้ายระงับหรือเรียกคืน",
        ),
        StepSpec(
            "ติดป้ายราคาใหม่",
            f"ติดป้ายลด {f.discount_pct}% ราคาใหม่ {price} ที่สินค้า {f.qty} {f.unit} แล้ววางไว้หน้าชั้น",
            _must("จำนวน", f.qty, "num") + _must("ราคาใหม่", f.new_price, "num"),
        ),
        StepSpec(
            "เปลี่ยนราคาใน POS",
            f"เปลี่ยนราคาใน POS ของ lot {f.lot_id} เป็น {price} ตามขั้นตอนของร้าน",
            _must("ราคาใหม่", f.new_price, "num"),
        ),
        StepSpec(
            "บันทึกจำนวนที่ปรับราคาจริง และเงื่อนไขหยุด",
            f"บันทึกจำนวนที่ติดป้ายจริงในแอป {STOP_TEXT}",
        ),
    ]


def _kitchen_steps(f: Facts) -> list[StepSpec]:
    kitchen = f.kitchen or "ครัวที่ระบบกำหนด"
    expected = f" (คาดว่าได้ {f.expected_output} ชิ้น)" if f.expected_output else ""
    recipe = f"{f.recipe_id} {f.recipe_name}" if f.recipe_name else f"{f.recipe_id}"
    return [
        StepSpec(
            "ตรวจความพร้อมของครัว อุปกรณ์ และพนักงาน",
            f"ตรวจกับครัว {kitchen} ว่าอุปกรณ์ พื้นที่ และพนักงานพร้อมก่อนส่งวัตถุดิบ "
            "ถ้าไม่พร้อมให้แจ้งหัวหน้า",
            _must("ครัว", f.kitchen),
        ),
        StepSpec(
            "นำวัตถุดิบส่งเข้าครัว",
            f"นำ{f.product_name} {f.qty} {f.unit} (lot {f.lot_id}) ส่งเข้าครัว {kitchen}",
            _must("จำนวน", f.qty, "num"),
        ),
        StepSpec(
            "ผลิตตามสูตรที่อนุมัติ",
            f"ผลิตตามสูตร {recipe} จำนวน {f.batch} batch ตามสูตรที่อนุมัติ",
            _must("รหัสสูตร", f.recipe_id) + _must("จำนวน batch", f.batch, "num"),
        ),
        StepSpec(
            "บันทึกวัตถุดิบที่ใช้และผลผลิตจริง และเงื่อนไขหยุด",
            f"บันทึกวัตถุดิบที่ใช้จริงและผลผลิตที่ได้จริง{expected} {STOP_TEXT}",
        ),
    ]


def _donate_steps(f: Facts) -> list[StepSpec]:
    partner = f.partner_label or "ผู้รับที่ระบบกำหนด"
    return [
        StepSpec(
            "ตรวจสภาพสินค้าและวันหมดอายุก่อนบริจาค",
            f"ตรวจวันหมดอายุ {f.expiry or 'ตามระบบ'} และสภาพสินค้าว่าไม่เสียหาย "
            "ไม่มีป้ายระงับหรือเรียกคืน",
            _must("วันหมดอายุ", f.expiry),
        ),
        StepSpec(
            "ยืนยันนัดรับกับผู้รับบริจาค",
            f"ยืนยันนัดรับกับ {partner} ก่อนเตรียมของ ถ้ายังไม่ได้รับการยืนยันให้หยุดและแจ้งหัวหน้า",
            _must("ผู้รับ", f.partner_name or f.partner_id),
        ),
        StepSpec(
            "ส่งมอบให้ผู้รับตามเวลานัด",
            f"ส่งมอบ{f.product_name} {f.qty} {f.unit} ให้ {partner} ภายใน {f.due or 'เวลานัด'}",
            _must("จำนวน", f.qty, "num"),
        ),
        StepSpec(
            "บันทึกผลหลังส่งมอบจริง และเงื่อนไขหยุด",
            f"บันทึกจำนวนที่ส่งมอบจริงหลังส่งเสร็จเท่านั้น {STOP_TEXT}",
        ),
    ]


def _discard_steps(f: Facts) -> list[StepSpec]:
    item = f"{f.product_name} {f.qty} {f.unit} (lot {f.lot_id})"
    if f.has_partner:
        middle = [
            StepSpec(
                "แยกสินค้าและเตรียมรอรถรับ",
                f"แยก{item} ออกจากชั้น ใส่ภาชนะแยกและวางรอรถรับ",
                _must("จำนวน", f.qty, "num"),
            ),
            StepSpec(
                "ส่งมอบให้ผู้รับตามเวลานัด",
                f"ส่งมอบให้ {f.partner_label} เมื่อรถมารับ {f.due or 'ตามเวลานัด'}",
                _must("ผู้รับ", f.partner_name or f.partner_id),
            ),
        ]
    else:
        middle = [
            StepSpec(
                "แยกสินค้าออกจากชั้น",
                f"แยก{item} ออกจากชั้น ใส่ภาชนะแยก",
                _must("จำนวน", f.qty, "num"),
            ),
            StepSpec(
                "กำจัดตามเส้นทางที่ร้านอนุมัติ",
                "นำไปจุดทิ้งที่ร้านกำหนดตามเส้นทางที่หัวหน้าอนุมัติเท่านั้น",
            ),
        ]
    return [
        StepSpec(
            "ขออนุมัติหัวหน้างานก่อนทิ้ง",
            "ขออนุมัติจากหัวหน้างานก่อนแยกสินค้าออกไปทิ้ง ถ้ายังไม่ได้รับอนุมัติห้ามดำเนินการต่อ",
        ),
        *middle,
        StepSpec(
            "บันทึกผลหลังดำเนินการจริง และเงื่อนไขหยุด",
            f"บันทึกจำนวนที่ทิ้งจริงหลังดำเนินการเสร็จเท่านั้น ห้ามบันทึกล่วงหน้า {STOP_TEXT}",
        ),
    ]


_STEPS_BY_ACTION = {
    "MARKDOWN": _markdown_steps,
    "KITCHEN_REPURPOSE": _kitchen_steps,
    "DONATE": _donate_steps,
    "DISCARD": _discard_steps,
}


def required_steps(f: Facts) -> list[StepSpec]:
    """Every action starts by locating the lot; unknown actions go to a supervisor."""
    build = _STEPS_BY_ACTION.get(f.action)
    if build is None:
        return [
            _locate_step(f),
            StepSpec(
                "แจ้งหัวหน้าเพื่อตรวจสอบงาน",
                f"งานประเภท {f.action} ยังไม่มีขั้นตอนมาตรฐาน ให้หยุดและแจ้งหัวหน้าก่อนดำเนินการ",
            ),
        ]
    return [_locate_step(f), *build(f)]


def staff_instructions(f: Facts) -> str:
    """One sentence shown on the staff app, built from data only (no LLM)."""
    where = f"ที่ {f.location}" if f.location else f"(ตำแหน่ง: {f.location_or_check})"
    item = f"{f.product_name} {f.qty} {f.unit} (lot {f.lot_id}) {where}"
    due = f" ภายใน {f.due}" if f.due else ""
    if f.action == "MARKDOWN":
        price = f" ราคาใหม่ {f.new_price} บาท" if f.new_price else ""
        return f"ติดป้ายลด {f.discount_pct}% {item}{price} และเปลี่ยนราคาใน POS{due}"
    if f.action == "KITCHEN_REPURPOSE":
        recipe = f"{f.recipe_id} {f.recipe_name}" if f.recipe_name else f"{f.recipe_id}"
        expected = f" (คาดว่าได้ {f.expected_output} ชิ้น)" if f.expected_output else ""
        return (f"ส่ง{item} เข้าครัว {f.kitchen or 'ที่ระบบกำหนด'} ทำสูตร {recipe} "
                f"{f.batch} batch{expected}{due}")
    if f.action == "DONATE":
        partner = f.partner_label or "ผู้รับที่ระบบกำหนด"
        return f"เตรียม{item} ส่งมอบให้ {partner}{due} ยืนยันนัดรับก่อนเตรียมของ"
    if f.action == "DISCARD":
        if f.has_partner:
            return f"แยก{item} รอรถ {f.partner_label} มารับ{due} ต้องได้รับอนุมัติหัวหน้าก่อน"
        return f"แยก{item} ทิ้งตามเส้นทางที่ร้านอนุมัติ{due} ต้องได้รับอนุมัติหัวหน้าก่อน"
    return f"ตรวจสอบ{item} และแจ้งหัวหน้าก่อนดำเนินการ"


def fallback_reasoning(f: Facts) -> str:
    """Standard ai_reasoning used when no LLM answer passes validation."""
    parts = [
        f"Optimizer เลือก{ACTION_TH.get(f.action, f.action)} {f.qty} {f.unit} "
        f"ของ{f.product_name} (lot {f.lot_id})"
    ]
    if f.risk_level:
        parts.append(f"ความเสี่ยง {f.risk_level} (score {f.risk_score}) เหลืออายุ {f.days_to_expiry} วัน")
    if f.expected_profit:
        parts.append(f"ผลกระทบกำไรที่คาด {f.expected_profit} บาท")
    text = " ".join(parts)
    if f.alternatives:
        text += " เทียบกับ" + f.alternatives[0].replace("- ทางเลือกอื่น:", "")
    return text + " (ข้อความมาตรฐาน: AI เขียนเหตุผลไม่ผ่านการตรวจ)"


def compute_priority(f: Facts, now: datetime) -> int:
    """Prototype heuristic, 1 = most urgent ... 5. Not a real store policy.

    1 = expired / expires today, or due within 4 hours
    2 = due within 12 hours, or 1 day left for kitchen / donate / discard
    3 = 1 day left (markdown)
    4 = 2 days left
    5 = everything else
    """
    hours = (f.due_dt - now).total_seconds() / 3600 if f.due_dt else None
    days = f.days_to_expiry
    if (days is not None and days <= 0) or (hours is not None and hours <= 4):
        return 1
    if hours is not None and hours <= 12:
        return 2
    if days == 1:
        return 2 if f.action in ("KITCHEN_REPURPOSE", "DONATE", "DISCARD") else 3
    if days == 2:
        return 4
    return 5
