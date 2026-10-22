"""Lambda ของ Manager Agent (image เดียวกับ pipeline worker, ImageConfig.Command = manager_agent.handler.lambda_handler)

server เรียกแบบ RequestResponse:
  {"question": "...", "history": [{"role": "user" | "assistant", "text": "..."}], "context": {"page", "lot_id"}}
  {"warmup": true}                     ปลุก container ตอนผู้จัดการเปิดแผงแชท (โหลด optimizer / boto3 ไว้ก่อน)
ตอบ:
  {"answer", "model_used", "tool_calls", "artifacts", "warnings", "usage", "latency_ms"}
  {"error": "...", "status": 400}      คำขอผิดรูปแบบ
"""
from __future__ import annotations

import json
import logging

from .agent import ManagerAgent
from .config import settings
from .data import DataSource
from .llm import BedrockLLM, SopRetriever

log = logging.getLogger()
log.setLevel(logging.INFO)

_llm = None
_sop = None


def _clients():
    global _llm, _sop
    if _llm is None:
        _llm = BedrockLLM()
    if _sop is None:
        try:
            _sop = SopRetriever()
        except Exception:  # noqa: BLE001  ไม่มี KB = search_sop ตอบว่าใช้ไม่ได้ ส่วนอื่นทำงานต่อ
            _sop = False
    return _llm, _sop or None


def lambda_handler(event, context=None):
    if isinstance(event, str):
        event = json.loads(event)
    event = event or {}
    if event.get("warmup"):
        _clients()
        return {"warmup": True}
    question = str(event.get("question") or "").strip()
    if not question:
        return {"error": "question ว่าง", "status": 400}
    if len(question) > settings.MAX_QUESTION_CHARS:
        return {"error": f"question ยาวเกิน {settings.MAX_QUESTION_CHARS} ตัวอักษร", "status": 400}
    llm, sop = _clients()
    ds = DataSource()                         # 1 คำถาม = cache ใหม่ (ข้อมูลล่าสุดเสมอ)
    ds.sop_retriever = sop
    result = ManagerAgent(llm, ds).ask(question, event.get("history"), event.get("context"))
    log.info(json.dumps({"q": question[:200], "model": result["model_used"], "latency_ms": result["latency_ms"],
                         "tools": [(t["name"], t["ok"], t["ms"]) for t in result["tool_calls"]],
                         "warnings": result["warnings"][:5], "usage": result["usage"]}, ensure_ascii=False))
    return result
