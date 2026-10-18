import httpx

from config import settings
from models import OptimizationDecision


async def get_pending_decisions() -> list[OptimizationDecision]:
    """Fetch pending optimization decisions from the backend API."""

    url = f"{settings.API_BASE_URL}/optimization-decisions"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            url,
            params={"status": "PENDING"},
        )
        response.raise_for_status()
        payload = response.json()
        print("API Response:", payload)

    decisions = payload.get("decisions", [])

    return [
        OptimizationDecision.model_validate(decision)
        for decision in decisions
    ]
