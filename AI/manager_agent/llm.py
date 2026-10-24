"""Bedrock Converse (tool calling) + Knowledge Base retrieve สำหรับ search_sop"""
from __future__ import annotations

from .config import settings

# Knowledge Base ติดป้าย action_type เป็น MARKDOWN / KITCHEN_REPURPOSE / DONATE / DISCARD / ALL (เหมือน llm-task-agent)
KB_ACTION = {"ANIMAL_FEED": "DISCARD", "COMPOST": "DISCARD", "ANAEROBIC_DIGESTION": "DISCARD", "LANDFILL": "DISCARD"}
MAX_CHUNK_CHARS = 1200


class BedrockLLM:
    def __init__(self, region: str | None = None):
        import boto3                                   # lazy: เทสต์ offline ไม่ต้องมี AWS
        from botocore.config import Config

        self.client = boto3.client("bedrock-runtime", region_name=region or settings.BEDROCK_REGION,
                                   config=Config(connect_timeout=3, read_timeout=20, retries={"max_attempts": 1}))

    def converse(self, model_id: str, system: str, messages: list, tools: dict, timeout_s: float) -> dict:
        kwargs = {"toolConfig": tools} if tools else {}      # tools=None: เขียนข้อความอย่างเดียว (แจ้งเตือน)
        r = self.client.converse(modelId=model_id, system=[{"text": system}], messages=messages, **kwargs,
                                 inferenceConfig={"maxTokens": settings.MAX_TOKENS, "temperature": settings.TEMPERATURE})
        return {"content": r["output"]["message"]["content"], "stop_reason": r.get("stopReason"),
                "usage": r.get("usage") or {}}


class SopRetriever:
    def __init__(self):
        import boto3

        self.client = boto3.client("bedrock-agent-runtime", region_name=settings.BEDROCK_REGION)

    def __call__(self, query: str, action_type: str | None = None) -> list[dict]:
        flt = None
        if action_type:
            kb_action = KB_ACTION.get(action_type, action_type)
            flt = {"orAll": [{"equals": {"key": "action_type", "value": kb_action}},
                             {"equals": {"key": "action_type", "value": "ALL"}}]}
        vec = {"numberOfResults": settings.KB_RESULTS}
        if flt:
            vec["filter"] = flt
        r = self.client.retrieve(knowledgeBaseId=settings.BEDROCK_KB_ID, retrievalQuery={"text": query},
                                 retrievalConfiguration={"vectorSearchConfiguration": vec})
        return [{"doc_id": (x.get("metadata") or {}).get("doc_id", "UNKNOWN"), "score": round(float(x.get("score", 0)), 4),
                 "text": " ".join(x["content"]["text"].split())[:MAX_CHUNK_CHARS]}
                for x in r.get("retrievalResults", [])]
