"""Prompts, Bedrock Converse calls, and JSON parsing."""

import json
import re
import time

from config import settings
from facts import Facts
from steps import StepSpec

SYSTEM_PROMPT = """คุณคือ Task Agent ของร้านค้าปลีก หน้าที่คือเขียนรายละเอียดขั้นตอนทำงานภาษาไทยจาก decision ที่ระบบตัดสินใจแล้ว
กฎ:
1. ใช้ตัวเลขจาก FACTS และ ALTERNATIVES เท่านั้น ห้ามคำนวณใหม่ ห้ามแต่งตัวเลข ราคา เวลา หรือจำนวน
2. เนื้อหาขั้นตอนต้องสอดคล้องกับ SOP ที่ให้มา ห้ามแต่งขั้นตอนที่ SOP ไม่ได้กล่าวถึง
3. instruction_steps ต้องมี title ตาม REQUIRED_STEPS ทุกข้อ ตรงตัวอักษร เรียงตามลำดับ ห้ามเพิ่มหรือตัด
4. detail แต่ละขั้นเป็นประโยคคำสั่งที่พนักงานทำตามได้ 1-2 ประโยค ไม่เกิน 300 ตัวอักษร ขึ้นต้นด้วยคำกริยา บอกว่าทำอะไร ที่ไหน เท่าไร
   และต้องใส่ข้อความในเครื่องหมายคำพูดที่ REQUIRED_STEPS ระบุไว้ลงในประโยค (ไม่ต้องใส่เครื่องหมายคำพูด)
   ห้ามเขียนเป็นรายการ "ชื่อข้อมูล ค่า" และห้ามขึ้นต้นด้วย "ถ้า" หรือ "หาก" ให้บอกสิ่งที่ต้องทำก่อน แล้วค่อยตามด้วยเงื่อนไข
5. ขั้นสุดท้ายต้องมีเงื่อนไขหยุด: ถ้าพบสินค้าเสียหาย จำนวนไม่ตรง หรือข้อมูลไม่ตรงกับระบบ ให้หยุดและแจ้งหัวหน้า
6. ถ้า FACTS ระบุว่า "ไม่มีข้อมูล" ให้เขียนว่า "ตรวจสอบกับระบบ" ห้ามเดา
7. ห้ามเขียนชื่อเอกสาร SOP ใน detail ให้เขียนเป็นการกระทำแทน ชื่อเอกสารใส่ได้เฉพาะใน ai_reasoning
8. เขียนวันที่และเวลาตามรูปแบบใน FACTS ห้ามแปลงเป็น พ.ศ. หรือรูปแบบอื่น
9. ผลผลิตของครัวเป็นค่าที่คาด ต้องมีคำว่า "คาดว่า" ทุกครั้งที่พูดถึง
10. ai_reasoning สำหรับผู้จัดการ 2-3 ประโยค ไม่เกิน 800 ตัวอักษร อธิบายว่าทำไมเลือกทางนี้ โดยเทียบกับ ALTERNATIVES และอ้างตัวเลข
    ใช้คำว่า "ดีกว่า" หรือ "แย่กว่า" ตามที่ ALTERNATIVES ระบุหลังเครื่องหมาย → เท่านั้น ห้ามเปรียบเทียบตัวเลขเอง
    ถ้าทางที่เลือกแย่กว่า ให้บอกตามจริงพร้อมหมายเหตุของทางเลือกนั้น ห้ามแต่งเหตุผลที่ไม่มีในข้อมูล
    ถ้าไม่มีทางเลือกอื่น ให้อธิบายจาก risk_level และจำนวนวันที่เหลือก่อนหมดอายุ ห้ามอ้างนโยบายหรือผู้อนุมัติที่ไม่มีในข้อมูล
11. ห้ามใช้คำว่า FACTS, ALTERNATIVES หรือ REQUIRED_STEPS ในคำตอบ เพราะผู้อ่านไม่เห็นข้อมูลส่วนนี้
12. ตอบเป็น JSON เท่านั้น ไม่มีข้อความอื่น ตามรูปแบบ:
{"ai_reasoning": "...", "instruction_steps": [{"title": "...", "detail": "..."}]}"""


def build_user_prompt(facts: Facts, specs: list[StepSpec], sop_chunks: list[dict]) -> str:
    if sop_chunks:
        sop = "\n".join(f"[{c['doc_id']}] {c['text']}" for c in sop_chunks)
    else:
        sop = "- ไม่พบ SOP ที่เกี่ยวข้อง ให้เขียนตามขั้นตอนมาตรฐานใน REQUIRED_STEPS"

    required = []
    for i, spec in enumerate(specs, 1):
        line = f"{i}. {spec.title}"
        if spec.must:
            # Value first: with "label value" the model wrote just "จำนวน 8"
            line += " — ประโยคต้องมี: " + ", ".join(f"\"{m.value}\" ({m.label})" for m in spec.must)
        required.append(line)

    if facts.chosen_is_worse:
        reasoning_rule = "\n\nai_reasoning ต้องจบด้วย \"ให้ผู้จัดการตรวจสอบก่อนอนุมัติ\" เพราะมีทางเลือกที่ดีกว่าทางที่เลือก"
    else:
        reasoning_rule = ""

    return (
        f"FACTS:\n{facts.to_prompt()}\n\n"
        f"ALTERNATIVES:\n{facts.alternatives_prompt()}\n\n"
        f"SOP (จาก Knowledge Base):\n{sop}\n\n"
        "REQUIRED_STEPS (ต้องใช้ title ตามนี้ ครบทุกข้อ เรียงตามลำดับ ห้ามเพิ่มหรือตัด):\n"
        + "\n".join(required)
        + reasoning_rule
        + "\n\nเขียน ai_reasoning และ instruction_steps สำหรับ decision นี้ เป็น JSON"
    )


def feedback_prompt(errors: list[str], specs: list[StepSpec]) -> str:
    """Validator errors + a passing example per failed step.

    Without examples the model fixed one error by breaking another.
    """
    failed = sorted({int(n) for e in errors for n in re.findall(r"ขั้นที่ (\d+)", e)})
    examples = [
        f"- ขั้นที่ {n} ({specs[n - 1].title}): {specs[n - 1].fallback}"
        for n in failed if 0 < n <= len(specs)
    ]
    text = "คำตอบก่อนหน้าไม่ผ่านการตรวจ:\n" + "\n".join(f"- {e}" for e in errors)
    if examples:
        text += "\n\nตัวอย่าง detail ที่ผ่านการตรวจ (เขียนใหม่ด้วยคำของคุณได้ แต่ต้องครบทุกส่วนแบบนี้):\n" + "\n".join(examples)
    return text + "\n\nแก้ให้ถูกต้องตามกฎทุกข้อ แล้วตอบ JSON ใหม่ทั้งหมด"


def parse_json(text: str) -> dict:
    """Strip <think> and ``` fences, parse the first { ... last }."""
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    cleaned = re.sub(r"```(?:json)?", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("ไม่พบ JSON ในคำตอบ")
    return json.loads(cleaned[start:end + 1])


class BedrockLLM:
    def __init__(self):
        import boto3  # lazy: offline runs need no AWS

        self.client = boto3.client("bedrock-runtime", region_name=settings.BEDROCK_REGION)

    def chat(self, model_id: str, messages: list[dict]) -> dict:
        """messages = [{"role": "user" | "assistant", "text": "..."}]"""
        started = time.time()
        response = self.client.converse(
            modelId=model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[
                {"role": m["role"], "content": [{"text": m["text"]}]} for m in messages
            ],
            inferenceConfig={
                "maxTokens": settings.MAX_TOKENS,
                "temperature": settings.TEMPERATURE,
                "topP": settings.TOP_P,
            },
        )
        blocks = response["output"]["message"]["content"]
        return {
            "text": "".join(b["text"] for b in blocks if "text" in b),
            "usage": response.get("usage", {}),
            "latency_ms": int((time.time() - started) * 1000),
        }
