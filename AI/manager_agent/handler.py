"""Lambda ของ Manager Agent (image เดียวกับ pipeline worker, ImageConfig.Command = manager_agent.handler.lambda_handler)

แชท (server เรียกแบบ RequestResponse จาก POST /agent/ask):
  {"question": "...", "history": [{"role": "user" | "assistant", "text": "..."}], "context": {"page", "lot_id"}}
  -> {"answer", "model_used", "tool_calls", "artifacts", "warnings", "usage", "latency_ms"}
  {"warmup": true}                     ปลุก container ตอนผู้จัดการเปิดแผงแชท (โหลด optimizer / boto3 ไว้ก่อน)
  {"error": "...", "status": 400}      คำขอผิดรูปแบบ

Phase 2 (ไม่รอผล): ผลส่งเข้า server เองผ่าน POST /agent/runs (ดู events.py)
  {"trigger": "EVENT", "event_type": "TASK_REJECTED" | "KITCHEN_FULL" | "PIPELINE_FAILED", "payload": {...}}  จาก server
  {"trigger": "SCHEDULE", "event_type": "WATCH", "payload": {"force": false}}   EventBridge ทุก 1 ชม. / ปุ่มตรวจตอนนี้ (force)
Phase 3 (daily.py): event_type MORNING_RUN (07:30) / PIPELINE_SUCCEEDED / MORNING_BRIEF / EVENING_SUMMARY (21:30)
"""
from __future__ import annotations

import json
import logging

from . import events
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
    if event.get("trigger") in ("EVENT", "SCHEDULE"):
        llm, _ = _clients()
        ds = DataSource()
        result = events.handle(event, ds, llm, events.Sink(ds.client))
        log.info(json.dumps({"trigger": event.get("trigger"), "event_type": event.get("event_type"),
                             "result": {k: result.get(k) for k in ("summary", "error", "warnings")}},
                            ensure_ascii=False, default=str))
        return result
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
