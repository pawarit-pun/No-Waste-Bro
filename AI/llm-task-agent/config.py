import os
from datetime import timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

TH_TZ = timezone(timedelta(hours=7))


def _env(name: str, default: str | None = None) -> str | None:
    """Read an environment variable, treating an empty value as unset."""
    value = os.getenv(name)
    return value if value not in (None, "") else default


class Settings:
    # Backend API (FastAPI on Lambda + API Gateway)
    API_BASE_URL: str = _env(
        "API_BASE_URL",
        "https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1",
    ).rstrip("/")
    HTTP_TIMEOUT: int = int(_env("HTTP_TIMEOUT", "30"))

    # Bedrock (Knowledge Base and models live in us-east-1)
    BEDROCK_REGION: str = _env("BEDROCK_REGION", "us-east-1")
    BEDROCK_KB_ID: str = _env("BEDROCK_KB_ID", "N0NJ2UIEIU")
    KB_RESULTS: int = int(_env("KB_RESULTS", "4"))

    # On-demand model IDs only: "us." / "global." inference profiles are blocked by SCP
    PRIMARY_MODEL: str = _env("PRIMARY_MODEL", "amazon.nova-lite-v1:0")
    FALLBACK_MODEL: str = _env("FALLBACK_MODEL", "qwen.qwen3-next-80b-a3b")
    MAX_TOKENS: int = 1500
    TEMPERATURE: float = 0.2
    TOP_P: float = 0.9

    # "Now" used for priority: AGENT_NOW (ISO) -> DEMO_DATE 08:00 -> real time
    AGENT_NOW: str | None = _env("AGENT_NOW")
    DEMO_DATE: str | None = _env("DEMO_DATE")

    # Audit report output (use /tmp/... on Lambda)
    OUTPUT_DIR: str = _env("OUTPUT_DIR", "output")


settings = Settings()
