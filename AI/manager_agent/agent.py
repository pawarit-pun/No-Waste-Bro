"""วงรอบของ Manager Agent: โมเดลขอเรียก tool -> รัน tool -> ส่งผลกลับ -> ... -> คำตอบ -> guard

ลำดับเมื่อคำตอบไม่ผ่าน guard หรือโมเดลล้ม:
  1. PRIMARY_MODEL (Nova Lite) แก้คำตอบ 1 ครั้ง (เรียก tool เพิ่มได้)
  2. FALLBACK_MODEL (Qwen3) ทำต่อจากผล tool ที่มีแล้ว (เรียก tool เพิ่มได้) + แก้ได้ 1 ครั้ง
  3. ข้อความสำเร็จรูป + การ์ดข้อมูลจาก tool (ไม่มีตัวเลขที่ตรวจไม่ได้หลุดไปถึงผู้จัดการ)
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from . import guard, prompts
from .config import settings
from .data import DataSource
from .tools import TOOLS, tool_config

MIN_CALL_BUDGET_S = 4.0     # เวลาที่เหลือน้อยกว่านี้ไม่เรียกโมเดลอีก (กันเกิน 29 วินาทีของ API Gateway)


class BudgetExceeded(RuntimeError):
    pass


def sanitize_history(history: Any, max_turns: int) -> list[dict]:
    """[{role, text}] จากหน้าเว็บ -> messages ของ Converse ที่ role สลับกัน เริ่มด้วย user จบด้วย assistant"""
    msgs: list[dict] = []
    for h in history or []:
        if not isinstance(h, dict):
            continue
        role, text = h.get("role"), str(h.get("text") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        text = text[: settings.MAX_QUESTION_CHARS * 2]
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"][0]["text"] += "\n" + text
        else:
            msgs.append({"role": role, "content": [{"text": text}]})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if msgs and msgs[-1]["role"] != "assistant":
        msgs.pop()
    return msgs[-max_turns * 2:]


class ManagerAgent:
    def __init__(self, llm, ds: Optional[DataSource] = None, *, clock=time.monotonic):
        self.llm, self.ds, self._clock = llm, ds or DataSource(), clock

    # ------------------------------------------------------------ tool
    def _run_tool(self, name: str, args: Any) -> tuple[dict, bool]:
        started = self._clock()
        key = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"
        if key in self._tool_cache:                       # โมเดลเรียกซ้ำด้วยอาร์กิวเมนต์เดิม -> ผลเดิม
            result, ok = self._tool_cache[key]
        else:
            tool = TOOLS.get(name)
            try:
                if tool is None:
                    raise ValueError(f"ไม่มี tool ชื่อ {name}")
                result, artifact = tool.fn(self.ds, tool.coerce(args))
                ok = True
                if artifact:
                    self.artifacts.append(artifact)
            except ValueError as e:                        # อาร์กิวเมนต์ผิด / ไม่พบข้อมูล -> บอกโมเดลให้แก้
                result, ok = {"error": str(e)}, False
            except Exception as e:  # noqa: BLE001         server ล่ม / optimizer ล้ม -> โมเดลบอกผู้จัดการได้
                result, ok = {"error": f"ดึงข้อมูลไม่สำเร็จ ({type(e).__name__})"}, False
                self.warnings.append(f"{name}: {type(e).__name__}: {str(e)[:200]}")
            self._tool_cache[key] = (result, ok)
        self.tool_calls.append({"name": name, "args": args, "ms": int((self._clock() - started) * 1000), "ok": ok})
        if ok:
            self.evidence.append(json.dumps(result, ensure_ascii=False, default=str))
        return result, ok

    # ------------------------------------------------------------ model
    def _remaining(self) -> float:
        return settings.BUDGET_S - (self._clock() - self._started)

    def _converse(self, model: str, messages: list) -> dict:
        if self._remaining() < MIN_CALL_BUDGET_S:
            raise BudgetExceeded("หมดเวลา")
        r = self.llm.converse(model, self._system, messages, self._tools, self._remaining())
        for k in ("inputTokens", "outputTokens"):
            self.usage[k] = self.usage.get(k, 0) + int((r.get("usage") or {}).get(k, 0))
        return r

    def _loop(self, model: str, messages: list) -> str:
        """เรียกโมเดลจนได้ข้อความตอบ (แก้ messages ในที่)"""
        while True:
            r = self._converse(model, messages)
            content = [b for b in r["content"] if "text" in b or "toolUse" in b] or [{"text": ""}]
            messages.append({"role": "assistant", "content": content})
            uses = [b["toolUse"] for b in content if "toolUse" in b]
            if r.get("stop_reason") != "tool_use" or not uses:
                return guard.strip_thinking("".join(b.get("text", "") for b in content))
            results = []
            for u in uses:
                if len(self.tool_calls) >= settings.MAX_TOOL_CALLS:
                    result, ok = {"error": "เรียก tool ครบจำนวนที่กำหนดแล้ว"}, False
                else:
                    result, ok = self._run_tool(u["name"], u.get("input"))
                results.append({"toolResult": {"toolUseId": u["toolUseId"], "content": [{"json": result}],
                                               "status": "success" if ok else "error"}})
            if len(self.tool_calls) >= settings.MAX_TOOL_CALLS:
                results.append({"text": prompts.FINAL_NOW})
            messages.append({"role": "user", "content": results})

    def _attempt(self, model: str, messages: list) -> Optional[str]:
        """คำตอบที่ผ่าน guard หรือ None (ลองแก้ 1 ครั้ง)"""
        answer = self._loop(model, messages)
        for i in range(2):
            problems = guard.check(answer, "\n".join(self.evidence)) if answer else ["คำตอบว่าง"]
            if not problems:
                return answer
            self.warnings.append(f"{model} guard: " + "; ".join(problems[:5]))
            if i == 1:
                return None
            messages.append({"role": "user", "content": [{"text": prompts.REVISE.format(
                problems="\n".join(f"- {p}" for p in problems[:8]))}]})
            answer = self._loop(model, messages)
        return None

    # ------------------------------------------------------------ public
    def ask(self, question: str, history: Any = None, context: Optional[dict] = None) -> dict:
        self._started = self._clock()
        self.tool_calls, self.artifacts, self.warnings, self.usage = [], [], [], {}
        self._tool_cache: dict = {}
        question = (question or "").strip()[: settings.MAX_QUESTION_CHARS]
        context = {k: v for k, v in (context or {}).items() if k in ("page", "lot_id") and v}
        if context.get("lot_id"):
            context["lot_id"] = str(context["lot_id"]).upper()[:20]

        try:
            today, now = self.ds.reference_date().isoformat(), self.ds.now().strftime("%H:%M")
        except Exception as e:  # noqa: BLE001  server ไม่ตอบ: ยังให้โมเดลตอบว่าดึงข้อมูลไม่ได้
            self.warnings.append(f"reference_date: {type(e).__name__}")
            today, now = settings.DEMO_DATE or "ไม่ทราบ", "ไม่ทราบ"
        self._system = prompts.system_prompt(today, now, context)
        self._tools = tool_config()
        hist = sanitize_history(history, settings.HISTORY_TURNS)
        # หลักฐานที่คำตอบอ้างได้ = ข้อเท็จจริงใน system prompt + คำถาม + บทสนทนาก่อนหน้า + ผลของ tool
        self.evidence = [today, now, context.get("lot_id") or "", question] + [m["content"][0]["text"] for m in hist]
        base = hist + [{"role": "user", "content": [{"text": question}]}]

        answer, model_used = None, None
        transcript = list(base)
        for model in (settings.PRIMARY_MODEL, settings.FALLBACK_MODEL):
            if model_used is None and model:
                # โมเดลสำรองเริ่มจากผล tool ที่มีแล้ว (ตัดคำตอบที่ไม่ผ่านของโมเดลก่อนหน้าออก)
                messages = list(base) if model == settings.PRIMARY_MODEL else _until_last_tool_result(transcript, len(base))
                try:
                    answer = self._attempt(model, messages)
                except BudgetExceeded:
                    self.warnings.append(f"{model}: หมดเวลา")
                    break
                except Exception as e:  # noqa: BLE001  throttling / model error -> ลองตัวถัดไป
                    self.warnings.append(f"{model}: {type(e).__name__}: {str(e)[:200]}")
                    answer = None
                transcript = messages
                if answer:
                    model_used = model
        if not answer:
            answer = prompts.TEMPLATE_WITH_CARDS if self.artifacts else prompts.TEMPLATE_EMPTY
            model_used = "TEMPLATE"
        return {"answer": answer, "model_used": model_used, "tool_calls": self.tool_calls,
                "artifacts": _dedupe(self.artifacts), "warnings": self.warnings, "usage": self.usage,
                "latency_ms": int((self._clock() - self._started) * 1000)}


def _until_last_tool_result(messages: list, base_len: int) -> list:
    """transcript ของโมเดลก่อนหน้า -> ตัดถึงผลของ tool ล่าสุด (ตัดคำตอบ/คำสั่งแก้ท้าย) ไม่เคยเรียก tool = เริ่มจากคำถามเดิม"""
    for i in range(len(messages) - 1, base_len - 1, -1):
        m = messages[i]
        if m["role"] == "user" and any("toolResult" in b for b in m["content"]):
            return [*messages[:i], {"role": "user", "content": [b for b in m["content"] if "toolResult" in b]}]
    return list(messages[:base_len])


def _dedupe(artifacts: list) -> list:
    """การ์ดซ้ำ (type + lot) เก็บอันล่าสุด สูงสุด 4 ใบ"""
    seen, out = set(), []
    for a in reversed(artifacts):
        key = (a.get("type"), a.get("lot_id"), json.dumps(a.get("scenario"), ensure_ascii=False))
        if key not in seen:
            seen.add(key)
            out.append(a)
    return list(reversed(out))[-4:]
