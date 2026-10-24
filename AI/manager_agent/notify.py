"""เขียนข้อความแจ้งเตือนผู้จัดการจากข้อเท็จจริงที่โค้ดเตรียมไว้ (LLM เขียนประโยคอย่างเดียว ไม่เลือก tool ไม่คิดเลข)

ลำดับ: PRIMARY_MODEL -> FALLBACK_MODEL -> ข้อความสำเร็จรูป ทุกคำตอบผ่าน guard ตัวเดียวกับแชท
"""
from __future__ import annotations

import json

from . import guard
from .config import settings

SYSTEM = """คุณเขียนข้อความแจ้งเตือนสั้นๆ ภาษาไทยให้ผู้จัดการร้าน Hypermarket จากข้อเท็จจริงใน FACTS
กฎ:
1. 1-3 ประโยค ไม่เกิน 300 ตัวอักษร บอกว่าเกิดอะไร กระทบ lot ไหน และผู้จัดการควรทำอะไรต่อ
2. ใช้ตัวเลข วันที่ เวลา ชื่อ และรหัส lot จาก FACTS เท่านั้น ห้ามคำนวณหรือแต่งเพิ่ม
3. ถ้า FACTS มี proposal ให้จบด้วยการบอกว่ากด "ยืนยัน" บนการ์ดได้ ถ้าไม่มี ห้ามเสนอว่าระบบจะทำให้
4. ห้ามใช้คำว่า FACTS หรือชื่อฟิลด์ภาษาอังกฤษ ตอบเฉพาะข้อความแจ้งเตือน ไม่มีหัวข้อ ไม่มีเครื่องหมายคำพูดครอบ"""

MAX_CHARS = 400


def compose(llm, facts: dict, fallback: str) -> dict:
    """-> {"message", "model_used", "warnings", "usage"}"""
    evidence = json.dumps(facts, ensure_ascii=False, default=str)
    prompt = "FACTS:\n" + evidence + "\n\nเขียนข้อความแจ้งเตือน"
    warnings: list[str] = []
    usage: dict = {}
    for model in (settings.PRIMARY_MODEL, settings.FALLBACK_MODEL):
        if not model or llm is None:
            continue
        try:
            r = llm.converse(model, SYSTEM, [{"role": "user", "content": [{"text": prompt}]}], None, 15)
        except Exception as e:  # noqa: BLE001  โมเดลล้ม -> ตัวถัดไป
            warnings.append(f"{model}: {type(e).__name__}: {str(e)[:150]}")
            continue
        for k in ("inputTokens", "outputTokens"):
            usage[k] = usage.get(k, 0) + int((r.get("usage") or {}).get(k, 0))
        text = guard.strip_thinking("".join(b.get("text", "") for b in r["content"])).strip().strip('"“”')
        problems = guard.check(text, evidence) if text else ["คำตอบว่าง"]
        if len(text) > MAX_CHARS:
            problems.append(f"ยาวเกิน {MAX_CHARS} ตัวอักษร")
        if not problems:
            return {"message": text, "model_used": model, "warnings": warnings, "usage": usage}
        warnings.append(f"{model} guard: " + "; ".join(problems[:4]))
    return {"message": fallback, "model_used": "TEMPLATE", "warnings": warnings, "usage": usage}
