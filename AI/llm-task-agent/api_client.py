import httpx

from config import settings
from models import OptimizationDecision, TaskCreate


class ApiError(Exception):
    """Non-2xx response from the backend (e.g. 409 kitchen full / task already exists)."""

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


class ApiSource:
    """Reads decisions from and writes tasks to the backend API."""

    def __init__(self):
        self.client = httpx.Client(base_url=settings.API_BASE_URL, timeout=settings.HTTP_TIMEOUT)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self.client.request(method, path, **kwargs)
        if response.is_error:
            raise ApiError(response.status_code, response.text)
        return response.json()

    def pending_decisions(self, run_id: str | None = None) -> tuple[str | None, list[OptimizationDecision]]:
        """GET /optimization-decisions?status=PENDING (latest run when run_id is None)."""
        params = {"status": "PENDING"}
        if run_id:
            params["run_id"] = run_id
        payload = self._request("GET", "/optimization-decisions", params=params)
        decisions = [OptimizationDecision.model_validate(d) for d in payload.get("decisions", [])]
        return payload.get("run_id"), decisions

    def post_tasks(self, tasks: list[TaskCreate]) -> dict:
        """POST /tasks. All tasks in one call are created together or not at all."""
        body = {"tasks": [t.model_dump(mode="json") for t in tasks]}
        return self._request("POST", "/tasks", json=body)
