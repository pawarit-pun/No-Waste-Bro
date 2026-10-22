"""เรียก Manager Agent (Lambda แยก, container image เดียวกับ AI pipeline worker) แบบรอผล

API Gateway ตัดที่ ~29 วินาที: agent ตั้งงบเวลาไว้ 25 วินาที ฝั่งนี้รอได้ 27 วินาที
"""
import json

from fastapi import HTTPException

from configs.config import db_env
from schemas.agent import AgentAskRequest

READ_TIMEOUT_S = 27
_client = None


def _lambda():
    global _client
    if _client is None:
        import boto3  # มีใน Lambda runtime อยู่แล้ว
        from botocore.config import Config

        _client = boto3.client("lambda", config=Config(connect_timeout=3, read_timeout=READ_TIMEOUT_S,
                                                       retries={"total_max_attempts": 1}))
    return _client


def _require_function() -> str:
    if not db_env.agent_function_name:
        raise HTTPException(503, "Manager Agent is not configured (AGENT_FUNCTION_NAME is empty; "
                                 "run on AWS or set it in .env)")
    return db_env.agent_function_name


def ask(body: AgentAskRequest) -> dict:
    name = _require_function()
    try:
        r = _lambda().invoke(FunctionName=name, InvocationType="RequestResponse",
                             Payload=json.dumps(body.model_dump(mode="json"), ensure_ascii=False).encode())
    except Exception as e:  # noqa: BLE001
        if "timeout" in type(e).__name__.lower():
            raise HTTPException(504, "Manager Agent took too long to answer, please ask again") from e
        raise HTTPException(502, f"Could not call the Manager Agent: {type(e).__name__}: {e}") from e
    raw = r["Payload"].read()
    payload = json.loads(raw) if raw else None
    if r.get("FunctionError") or not isinstance(payload, dict):
        msg = payload.get("errorMessage") if isinstance(payload, dict) else str(payload)[:300]
        raise HTTPException(502, f"Manager Agent failed: {msg}")
    if payload.get("error"):
        raise HTTPException(int(payload.get("status") or 400), payload["error"])
    return payload


def warm_up() -> bool:
    """ปลุก container (ไม่รอผล) ตอนผู้จัดการเปิดแผงแชท ลด cold start ของคำถามแรก"""
    if not db_env.agent_function_name:
        return False
    try:
        _lambda().invoke(FunctionName=db_env.agent_function_name, InvocationType="Event",
                         Payload=b'{"warmup": true}')
        return True
    except Exception:  # noqa: BLE001  ปลุกไม่ได้ไม่ใช่ error ของผู้ใช้
        return False
