"""ค่าตั้งต้นของ Manager Agent (อ่านจาก env ของ Lambda ทั้งหมด ค่าว่าง = ใช้ค่าเริ่มต้น)"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


AI_DIR = Path(_env("AI_DIR", str(Path(__file__).resolve().parent.parent)))
OPTIMIZER_DIR = Path(_env("OPTIMIZER_DIR", str(AI_DIR / "food_waste_optimizer")))
if str(OPTIMIZER_DIR) not in sys.path:          # ai_engine.optimizer (ใช้ตอน what-if / อธิบาย decision)
    sys.path.insert(0, str(OPTIMIZER_DIR))


class Settings:
    API_BASE_URL: str = _env("API_BASE_URL", "https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1").rstrip("/")
    HTTP_TIMEOUT_S: float = float(_env("AGENT_HTTP_TIMEOUT_S", "8"))
    DEMO_DATE: str | None = _env("DEMO_DATE")

    # Bedrock อยู่ us-east-1 ใช้ได้เฉพาะ on-demand model ID (SCP บล็อก profile "us." / "global.")
    # check_models.py (22 ต.ค.) ทั้งสองตัวได้ TOOL_USE_OK
    BEDROCK_REGION: str = _env("BEDROCK_REGION", "us-east-1")
    BEDROCK_KB_ID: str = _env("BEDROCK_KB_ID", "N0NJ2UIEIU")
    PRIMARY_MODEL: str = _env("PRIMARY_MODEL", "amazon.nova-lite-v1:0")
    FALLBACK_MODEL: str = _env("FALLBACK_MODEL", "qwen.qwen3-next-80b-a3b")
    MAX_TOKENS: int = int(_env("AGENT_MAX_TOKENS", "1200"))
    TEMPERATURE: float = 0.0

    # วงรอบ agent: API Gateway ตัดที่ 29 วินาที -> agent ต้องตอบภายใน BUDGET_S
    MAX_TOOL_CALLS: int = int(_env("AGENT_MAX_TOOL_CALLS", "8"))
    BUDGET_S: float = float(_env("AGENT_BUDGET_S", "25"))
    HISTORY_TURNS: int = 10
    MAX_QUESTION_CHARS: int = 1000
    KB_RESULTS: int = 4


settings = Settings()
