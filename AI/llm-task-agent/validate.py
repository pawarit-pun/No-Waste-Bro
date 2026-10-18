"""Check the LLM's answer before it reaches staff. Returns a list of errors (empty = pass)."""

import re

from facts import Facts
from steps import StepSpec

# Any number, including those inside codes and dates (used to build the allowed list)
NUM_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
# Standalone numbers only: skips digits inside codes (RCP-001, LOT-000009, E-01) and dates
# (2026-10-16), otherwise RCP-001 would count as "batch 1"
STRICT_NUM_RE = re.compile(r"(?<![A-Za-z0-9_\-.])\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9_\-])")
SOP_NAME_RE = re.compile(r"\b[A-Z][A-Z_]*_(?:SOP|POLICY)\b")
BUDDHIST_YEAR_RE = re.compile(r"\b25[6-9]\d\b")

MAX_DETAIL = 300  # same limit as the server's InstructionStep.detail
MAX_REASONING = 800


def _to_numbers(matches: list[str]) -> set[float]:
    return {float(n.replace(",", "")) for n in matches}


def numbers_in(text: str) -> set[float]:
    return _to_numbers(NUM_RE.findall(text or ""))


def standalone_numbers(text: str) -> set[float]:
    return _to_numbers(STRICT_NUM_RE.findall(text or ""))


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def allowed_numbers(facts: Facts, specs: list[StepSpec]) -> set[float]:
    """Numbers the LLM may use: those in FACTS, ALTERNATIVES and REQUIRED_STEPS titles."""
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
    if not isinstance(steps, list):
        return errors + ["instruction_steps ไม่ใช่ list"]
    if len(steps) != len(specs):
        errors.append(f"instruction_steps ต้องมี {len(specs)} ข้อ แต่ได้ {len(steps)} ข้อ")

    allowed = allowed_numbers(facts, specs)
    # When expected output equals the ingredient qty or batch count we cannot tell which one
    # a number refers to, so the "คาดว่า" rule is skipped (e.g. yogurt 24 -> 24)
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
        if SOP_NAME_RE.search(detail):
            errors.append(f"{label} มีชื่อเอกสาร SOP ในข้อความถึงพนักงาน ให้เขียนเป็นการกระทำแทน")

        detail_nums = standalone_numbers(detail)
        for must in spec.must:
            if must.kind == "num":
                if float(must.value) not in detail_nums:
                    errors.append(f"{label} detail ต้องมี{must.label} {must.value}")
            elif _norm(must.value) not in _norm(detail):
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
        extra = sorted(n for n in standalone_numbers(text) if n not in allowed)
        if extra:
            errors.append(f"{label} มีตัวเลขที่ไม่อยู่ใน FACTS: {', '.join(_fmt(n) for n in extra[:5])}")
    return errors
