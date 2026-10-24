"""ส่งเหตุการณ์ให้ Manager Agent แบบไม่รอผล (Phase 2)

ใช้จาก task_actions (task ถูกปฏิเสธ), tasks (จองครัวไม่ได้ตอนอนุมัติ), pipeline (รอบล้ม)
ส่งไม่สำเร็จ = แค่ไม่มีแจ้งเตือน งานหลักของ route นั้นต้องสำเร็จตามเดิม จึงไม่ raise อะไรเลย
"""
import json
import logging

from configs.config import db_env

log = logging.getLogger(__name__)
READ_TIMEOUT_S = 27
_client = None


def lambda_client():
    global _client
    if _client is None:
        import boto3  # มีใน Lambda runtime อยู่แล้ว
        from botocore.config import Config

        _client = boto3.client("lambda", config=Config(connect_timeout=3, read_timeout=READ_TIMEOUT_S,
                                                       retries={"total_max_attempts": 1}))
    return _client


def invoke_async(payload: dict) -> bool:
    if not db_env.agent_function_name:
        return False
    try:
        lambda_client().invoke(FunctionName=db_env.agent_function_name, InvocationType="Event",
                               Payload=json.dumps(payload, ensure_ascii=False, default=str).encode())
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("agent invoke failed: %s: %s", type(e).__name__, e)
        return False


def emit_event(event_type: str, payload: dict) -> bool:
    """event_type: TASK_REJECTED / KITCHEN_FULL / PIPELINE_FAILED (ดู AI/manager_agent/events.py)"""
    return invoke_async({"trigger": "EVENT", "event_type": event_type, "payload": payload})


def daily_now(kind: str) -> bool:
    """ทำรายงานประจำวันทันที (ปุ่มในหน้า Run demo): morning = Morning brief ของ pipeline รอบล่าสุดที่สำเร็จ
    (ไม่เริ่ม pipeline ใหม่), evening = Evening summary"""
    event_type = {"morning": "MORNING_BRIEF", "evening": "EVENING_SUMMARY"}[kind]
    return invoke_async({"trigger": "SCHEDULE", "event_type": event_type, "payload": {"manual": True}})


def watch_now() -> bool:
    """ตรวจงานค้างทันที (ปุ่มในหน้า Run demo / กระดิ่ง) force = ตรวจแม้อยู่นอกเวลาร้าน"""
    return invoke_async({"trigger": "SCHEDULE", "event_type": "WATCH", "payload": {"force": True}})
