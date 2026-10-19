"""Check the LLM's answer before it reaches staff. Empty error list = pass."""

import re

from facts import Facts
from steps import REVIEW_TEXT, StepSpec

# Any number, incl. inside codes and dates (for the allowed list)
NUM_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
# Standalone numbers only, so RCP-001 or 2026-10-16 are not read as "1" or "16"
STRICT_NUM_RE = re.compile(r"(?<![A-Za-z0-9_\-.])\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9_\-])")
SOP_NAME_RE = re.compile(r"\b[A-Z][A-Z_]*_(?:SOP|POLICY)\b")
BUDDHIST_YEAR_RE = re.compile(r"\b25[6-9]\d\b")
PROMPT_TERM_RE = re.compile(r"FACTS|ALTERNATIVES|REQUIRED_STEPS")
# "จำนวน 8" is a data list, not an instruction
LABEL_START_RE = re.compile(r"^\s*(?:จำนวน|รหัสสูตร|ครัว|เงื่อนไข|ตำแหน่ง|ผู้รับ|วันหมดอายุ|ราคาใหม่|lot)\s")
# Starting with a condition drops the action ("ถ้ายังไม่ได้รับอนุมัติ...")
CONDITION_START_RE = re.compile(r"^\s*(?:ถ้า|หาก)")
MIN_DETAIL = 20
# "ดีกว่า ... 224 บาท": the number must be a difference computed in code
COMPARE_RE = re.compile(r"(?:ดีกว่า|แย่กว่า)[^\d\-\n]{0,25}?(\d+(?:,\d{3})*(?:\.\d+)?)\s*บาท")

MAX_DETAIL = 300  # server limit
MAX_REASONING = 800


def _to_numbers(matches: list[str]) -> set[float]:
    return {float(n.replace(",", "")) for n in matches}


def numbers_in(text: str) -> set[float]:
    return _to_numbers(NUM_RE.findall(text or ""))


def standalone_numbers(text: str) -> set[float]:
    return _to_numbers(STRICT_NUM_RE.findall(text or ""))


def _norm(text: str) -> str:
    """Ignore spaces; "หาก" = "ถ้า"."""
    return re.sub(r"\s+", "", text or "").replace("หาก", "ถ้า")


def allowed_numbers(facts: Facts, specs: list[StepSpec]) -> set[float]:
    """Numbers in FACTS, ALTERNATIVES and step titles."""
    pool = "\n".join([facts.to_prompt(), facts.alternatives_prompt(), *(s.title for s in specs)])
    return numbers_in(pool)


def _fmt(n: float) -> str:
    return str(int(n)) if n.is_integer() else str(n)


def validate_output(out: dict, facts: Facts, specs: list[StepSpec]) -> list[str]:
    errors: list[str] = []
    if not isinstance(out, dict):
        return ["คำตอบไม่ใช่ JSON object"]

    reasoning = out.get("ai_reasoning")
    steps = out.get("instruction_steps")
    if not isinstance(reasoning, str) or not reasoning.strip():
        errors.append("ai_reasoning ว่างหรือไม่ใช่ข้อความ")
        reasoning = ""
    elif len(reasoning) > MAX_REASONING:
        errors.append(f"ai_reasoning ยาวเกิน {MAX_REASONING} ตัวอักษร")
    has_review = _norm(REVIEW_TEXT) in _norm(reasoning)
    if reasoning and facts.chosen_is_worse and not has_review:
        errors.append(f"ai_reasoning ต้องมี \"{REVIEW_TEXT}\" เพราะมีทางเลือกที่ดีกว่าทางที่เลือก")
    if not facts.chosen_is_worse and has_review:
        errors.append(f"ai_reasoning ห้ามมี \"{REVIEW_TEXT}\" เพราะทางที่เลือกไม่ได้แย่กว่าทางเลือกอื่น")
    if reasoning and facts.chosen_is_worse and "แย่กว่า" not in reasoning:
        errors.append("ai_reasoning ต้องบอกว่าทางที่เลือก \"แย่กว่า\" ทางเลือกอื่นตามข้อมูล ห้ามบอกว่าดีกว่า")
    wrong_diffs = sorted(
        float(n.replace(",", "")) for n in COMPARE_RE.findall(reasoning)
        if float(n.replace(",", "")) not in facts.comparison_diffs
    )
    if wrong_diffs:
        shown = ", ".join(_fmt(n) for n in wrong_diffs)
        expected = ", ".join(_fmt(n) for n in sorted(facts.comparison_diffs)) or "ไม่มี"
        errors.append(f"ai_reasoning ส่วนต่างหลังคำว่า ดีกว่า/แย่กว่า ไม่ถูกต้อง ({shown}) ส่วนต่างที่ถูกคือ {expected} บาท")
    if not isinstance(steps, list):
        return errors + ["instruction_steps ไม่ใช่ list"]
    if len(steps) != len(specs):
        errors.append(f"instruction_steps ต้องมี {len(specs)} ข้อ แต่ได้ {len(steps)} ข้อ")

    allowed = allowed_numbers(facts, specs)
    # Skip the "คาดว่า" rule when expected output equals qty or batch (ambiguous number)
    check_expected = bool(facts.expected_output) and facts.expected_output not in (facts.qty, facts.batch)
    texts_to_check = [("ai_reasoning", reasoning)]

    for i, (spec, step) in enumerate(zip(specs, steps)):
        label = f"ขั้นที่ {i + 1}"
        step = step if isinstance(step, dict) else {}
        title, detail = step.get("title", ""), step.get("detail", "")

        if _norm(title) != _norm(spec.title):
            errors.append(f"{label} title ต้องเป็น \"{spec.title}\" แต่ได้ \"{title}\"")
        if not isinstance(detail, str) or not detail.strip():
            errors.append(f"{label} detail ว่าง")
            continue
        if len(detail.strip()) > MAX_DETAIL:
            errors.append(f"{label} detail ยาวเกิน {MAX_DETAIL} ตัวอักษร")
        if len(detail.strip()) < MIN_DETAIL or LABEL_START_RE.match(detail):
            errors.append(f"{label} detail ต้องเป็นประโยคคำสั่งที่ขึ้นต้นด้วยคำกริยา ไม่ใช่รายการข้อมูล")
        elif CONDITION_START_RE.match(detail):
            errors.append(f"{label} detail ห้ามขึ้นต้นด้วย \"ถ้า\" หรือ \"หาก\" ให้บอกสิ่งที่ต้องทำก่อน แล้วค่อยตามด้วยเงื่อนไข")
        if SOP_NAME_RE.search(detail):
            errors.append(f"{label} มีชื่อเอกสาร SOP ในข้อความถึงพนักงาน ให้เขียนเป็นการกระทำแทน")

        detail_nums = standalone_numbers(detail)
        for must in spec.must:
            if must.kind == "num":
                if float(must.value) not in detail_nums:
                    errors.append(f"{label} detail ต้องมี{must.label} {must.value}")
            elif _norm(must.value) not in _norm(detail) and not (
                must.pattern and re.search(must.pattern, _norm(detail))
            ):
                errors.append(f"{label} detail ต้องมี{must.label} \"{must.value}\"")

        if check_expected and float(facts.expected_output) in detail_nums and "คาด" not in detail:
            errors.append(
                f"{label} พูดถึงผลผลิต {facts.expected_output} ชิ้น ต้องระบุว่าเป็นค่าที่คาด (ใช้คำว่า \"คาดว่า\")"
            )
        texts_to_check.append((label, detail))

    if steps and len(steps) == len(specs):
        last = steps[-1].get("detail", "") if isinstance(steps[-1], dict) else ""
        if "หยุด" not in last or "แจ้งหัวหน้า" not in last:
            errors.append("ขั้นสุดท้ายต้องมีเงื่อนไขหยุด (หยุดและแจ้งหัวหน้า)")

    for label, text in texts_to_check:
        if BUDDHIST_YEAR_RE.search(text):
            errors.append(f"{label} แปลงปีเป็น พ.ศ. ให้ใช้รูปแบบวันที่ตาม FACTS")
        if PROMPT_TERM_RE.search(text):
            errors.append(f"{label} มีคำ FACTS / ALTERNATIVES / REQUIRED_STEPS ซึ่งผู้อ่านไม่เห็น ให้เขียนเป็นข้อมูลจริงแทน")
        extra = sorted(n for n in standalone_numbers(text) if n not in allowed)
        if extra:
            errors.append(f"{label} มีตัวเลขที่ไม่อยู่ใน FACTS: {', '.join(_fmt(n) for n in extra[:5])}")
    return errors
