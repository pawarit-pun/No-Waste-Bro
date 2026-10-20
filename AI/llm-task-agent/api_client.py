import httpx

from config import settings
from models import OptimizationDecision, TaskCreate


class ApiError(Exception):
    """Non-2xx response, e.g. 409 kitchen full / task already exists."""

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


class ApiSource:
    def __init__(self):
        self.client = httpx.Client(base_url=settings.API_BASE_URL, timeout=settings.HTTP_TIMEOUT)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self.client.request(method, path, **kwargs)
        if response.is_error:
            raise ApiError(response.status_code, response.text)
        return response.json()

    def pending_decisions(self, run_id: str | None = None) -> tuple[str | None, list[OptimizationDecision]]:
        """Pending decisions of run_id (default: latest run)."""
        params = {"status": "PENDING"}
        if run_id:
            params["run_id"] = run_id
        payload = self._request("GET", "/optimization-decisions", params=params)
        decisions = [OptimizationDecision.model_validate(d) for d in payload.get("decisions", [])]
        return payload.get("run_id"), decisions

    def post_tasks(self, tasks: list[TaskCreate]) -> dict:
        """All tasks in one call are created together or not at all."""
        body = {"tasks": [t.model_dump(mode="json") for t in tasks]}
        return self._request("POST", "/tasks", json=body)

    def set_lots_ai_status(self, lot_ids: list[str], ai_status: str) -> dict:
        """Unknown lot_ids come back in not_found; 404 only when none exist."""
        body = {"lot_ids": lot_ids, "ai_status": ai_status}
        return self._request("PATCH", "/inventory-lots/ai-status", json=body)
