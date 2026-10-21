"""
route ที่ใช้
  GET   /ai/optimize-runs          อ่าน: รอบสแกนที่พร้อมตัดสินใจ (ไม่ระบุ run_id = ใช้ suggested_run_id)
  GET   /ai/optimize-inputs        อ่าน: lot เสี่ยง + shelf + recipe_demand + สินค้า + สูตร + ครัว + partner + สต็อกวัตถุดิบ
  GET   /products                  อ่าน: flag allow_animal_feed / composting / anaerobic_digestion / landfill
  GET   /optimization-decisions    อ่าน: decision ที่มีแล้วของรอบนี้ (กันบันทึกซ้ำ)
  POST  /optimization-decisions    เขียน: บันทึก decision ลงตาราง optimization_decisions
  PATCH /inventory-lots/ai-status  เขียน: lot ที่ไม่ต้องทำอะไร -> IDLE
  POST  /ai/optimize               (route ใหม่ของ server) ให้ server รัน Optimizer เอง
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

DEFAULT_API_BASE = "https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1"


class ApiError(RuntimeError):
    def __init__(self, status: int, body: Any, url: str):
        super().__init__(f"HTTP {status} {url}: {body}")
        self.status, self.body, self.url = status, body, url


class ApiClient:
    """transport(method, url, body_bytes | None, headers, timeout) -> (status, text) ใช้แทนเครือข่ายตอนทดสอบ"""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 120.0, transport: Optional[Callable] = None):
        self.base_url = (base_url or os.getenv("API_BASE_URL") or DEFAULT_API_BASE).rstrip("/") + "/"
        self.timeout = timeout
        self._transport = transport or self._urllib

    @staticmethod
    def _urllib(method, url, body, headers, timeout):
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def request(self, method: str, route: str, params: Optional[dict] = None, body: Optional[dict] = None) -> Any:
        url = self.base_url + route.lstrip("/")
        params = {k: v for k, v in (params or {}).items() if v is not None}
        if params:
            url += "?" + urllib.parse.urlencode({k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()})
        data = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        status, text = self._transport(method, url, data, headers, self.timeout)
        try:
            payload = json.loads(text) if text else None
        except ValueError:
            payload = text
        if status >= 400:
            raise ApiError(status, payload, url)
        return payload

    def get_optimize_runs(self) -> dict:
        return self.request("GET", "ai/optimize-runs")

    def get_optimize_inputs(self, run_id: Optional[str] = None, days_ahead: int = 1) -> dict:
        return self.request("GET", "ai/optimize-inputs", {"run_id": run_id, "days_ahead": days_ahead})

    def get_products(self) -> list:
        return self.request("GET", "products")

    def get_decisions(self, run_id: Optional[str] = None, status: Optional[str] = None) -> dict:
        return self.request("GET", "optimization-decisions", {"run_id": run_id, "status": status})

    def post_decisions(self, payload: dict) -> dict:
        return self.request("POST", "optimization-decisions", body=payload)

    def set_lot_status(self, lot_ids: list, ai_status: str) -> dict:
        return self.request("PATCH", "inventory-lots/ai-status", body={"lot_ids": list(lot_ids), "ai_status": ai_status})

    def run_optimize(self, run_id: Optional[str] = None, days_ahead: int = 1, dry_run: bool = True) -> dict:
        return self.request("POST", "ai/optimize", {"run_id": run_id, "days_ahead": days_ahead, "dry_run": dry_run})


def pick_run(client: ApiClient, run_id: Optional[str] = None) -> tuple[Optional[str], Optional[dict]]:
    """run_id ที่ระบุ > suggested_run_id ของ GET /ai/optimize-runs (รอบล่าสุดที่สแกนวันเดียวกับ DEMO_DATE และยังมี lot
    HIGH / CRITICAL รอตัดสินใจ) > None (= รอบสแกนล่าสุด) -> (run_id, ข้อมูลรอบทั้งหมด หรือ None)"""
    if run_id:
        return run_id, None
    try:
        runs = client.get_optimize_runs()
    except ApiError as e:
        if e.status == 404:          # server รุ่นเก่ายังไม่มี route นี้
            return None, None
        raise
    return runs.get("suggested_run_id"), runs


def load_from_api(client: ApiClient, run_id: Optional[str] = None, days_ahead: int = 1) -> tuple[dict, list, set]:
    """อ่านข้อมูลจริงทั้งหมดที่ Optimizer ต้องใช้ -> (optimize_inputs, products, assessment_id ที่มี decision แล้ว)"""
    run_id, _ = pick_run(client, run_id)
    inputs = client.get_optimize_inputs(run_id, days_ahead)
    products = client.get_products()
    decided = set()
    if inputs.get("run_id"):
        existing = client.get_decisions(inputs["run_id"])
        if str(existing.get("run_id")) == str(inputs["run_id"]):
            decided = {str(d["assessment_id"]) for d in existing.get("decisions") or []}
    return inputs, products, decided