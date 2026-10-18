"""Bedrock Converse calls, prompts, and JSON parsing of the model's answer."""

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
4. detail แต่ละขั้นสั้น 1-2 ประโยค ไม่เกิน 300 ตัวอักษร บอกว่าทำอะไร ที่ไหน เท่าไร และต้องมีข้อมูลที่ REQUIRED_STEPS ระบุว่า "ต้องมี"
5. ขั้นสุดท้ายต้องมีเงื่อนไขหยุด: ถ้าพบสินค้าเสียหาย จำนวนไม่ตรง หรือข้อมูลไม่ตรงกับระบบ ให้หยุดและแจ้งหัวหน้า
6. ถ้า FACTS ระบุว่า "ไม่มีข้อมูล" ให้เขียนว่า "ตรวจสอบกับระบบ" ห้ามเดา
7. ห้ามเขียนชื่อเอกสาร SOP ใน detail ให้เขียนเป็นการกระทำแทน ชื่อเอกสารใส่ได้เฉพาะใน ai_reasoning
8. เขียนวันที่และเวลาตามรูปแบบใน FACTS ห้ามแปลงเป็น พ.ศ. หรือรูปแบบอื่น
9. ผลผลิตของครัวเป็นค่าที่คาด ต้องมีคำว่า "คาดว่า" ทุกครั้งที่พูดถึง
10. ai_reasoning สำหรับผู้จัดการ 2-3 ประโยค ไม่เกิน 800 ตัวอักษร อธิบายว่าทำไมเลือกทางนี้ โดยเทียบกับ ALTERNATIVES และอ้างตัวเลข
11. ตอบเป็น JSON เท่านั้น ไม่มีข้อความอื่น ตามรูปแบบ:
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
            line += " — detail ต้องมี: " + ", ".join(f"{m.label} {m.value}" for m in spec.must)
        required.append(line)

    return (
        f"FACTS:\n{facts.to_prompt()}\n\n"
        f"ALTERNATIVES:\n{facts.alternatives_prompt()}\n\n"
        f"SOP (จาก Knowledge Base):\n{sop}\n\n"
        "REQUIRED_STEPS (ต้องใช้ title ตามนี้ ครบทุกข้อ เรียงตามลำดับ ห้ามเพิ่มหรือตัด):\n"
        + "\n".join(required)
        + "\n\nเขียน ai_reasoning และ instruction_steps สำหรับ decision นี้ เป็น JSON"
    )


def feedback_prompt(errors: list[str]) -> str:
    """Follow-up message listing validator errors so the model can fix its answer."""
    return (
        "คำตอบก่อนหน้าไม่ผ่านการตรวจ:\n"
        + "\n".join(f"- {e}" for e in errors)
        + "\nแก้ให้ถูกต้องตามกฎทุกข้อ แล้วตอบ JSON ใหม่ทั้งหมด"
    )


def parse_json(text: str) -> dict:
    """Strip <think>...</think> and ``` fences, then parse from the first { to the last }."""
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    cleaned = re.sub(r"```(?:json)?", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("ไม่พบ JSON ในคำตอบ")
    return json.loads(cleaned[start:end + 1])


class BedrockLLM:
    def __init__(self):
        import boto3  # imported here so offline runs work without AWS access

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
