"""อ่านข้อมูลร้านผ่าน API ของ server (อ่านอย่างเดียว) + รัน Optimizer แบบ dry-run สำหรับอธิบาย / what-if

1 คำถาม = 1 DataSource: ผลของแต่ละ route ถูก cache ไว้ในคำถามนั้น (tool หลายตัวใช้ข้อมูลชุดเดียวกัน ตัวเลขตรงกัน)
ไม่มี route ไหนในไฟล์นี้เขียนข้อมูล
"""
from __future__ import annotations

import copy
from datetime import date, datetime
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from . import config  # noqa: F401  (ใส่ OPTIMIZER_DIR ใน sys.path)
from .config import settings

from ai_engine.optimizer import ApiClient, OptimizerConfig, run_optimizer, simulated_now  # noqa: E402

BKK = ZoneInfo("Asia/Bangkok")

# Optimizer ของ agent: คิดทุก lot ที่ Risk Scanner ส่งมา (รวม lot ที่สร้าง task ไปแล้ว = CHECKED) ไม่บันทึกอะไร
# allow_stale_scan: อธิบายรอบสแกนล่าสุดได้แม้ไม่ใช่วันนี้ (ผลลัพธ์แจ้งเตือนใน warnings)
AGENT_OPT_CFG = OptimizerConfig(process_ai_statuses=("PROCESSING", "CHECKED", "IDLE"), allow_stale_scan=True,
                                release_no_action_lots=False, solver_time_limit_s=8.0)


class DataSource:
    def __init__(self, client: Optional[ApiClient] = None, clock: Optional[Callable[[], datetime]] = None):
        self.client = client or ApiClient(settings.API_BASE_URL, timeout=settings.HTTP_TIMEOUT_S)
        self._clock = clock or (lambda: datetime.now(BKK))
        self._cache: dict[str, Any] = {}
        self._plans: dict[str, dict] = {}

    def _get(self, key: str, route: str, params: Optional[dict] = None):
        if key not in self._cache:
            self._cache[key] = self.client.request("GET", route, params)
        return self._cache[key]

    # ---------------- route ของ server
    def inventory(self) -> dict:
        return self._get("inventory", "inventory-lots")

    def tasks(self, statuses: tuple = ("PENDING", "IN_PROGRESS")) -> list:
        qs = "&".join(f"status={s}" for s in statuses)          # route รับ status ซ้ำหลายค่า
        return self._get(f"tasks:{qs}", f"tasks?{qs}")

    def reviews(self) -> dict:
        return self._get("reviews", "pending-tasks")              # ค่าเริ่มต้นของ route = WAITING

    def optimize_runs(self) -> dict:
        return self._get("optimize_runs", "ai/optimize-runs")

    def optimize_inputs(self) -> dict:
        if "optimize_inputs" not in self._cache:
            run_id = (self.optimize_runs() or {}).get("suggested_run_id")
            self._cache["optimize_inputs"] = self.client.get_optimize_inputs(run_id, 1)
        return self._cache["optimize_inputs"]

    def products(self) -> list:
        return self._get("products", "products")

    def decisions(self, run_id: Optional[str]) -> dict:
        return self._get(f"decisions:{run_id}", "optimization-decisions", {"run_id": run_id})

    def pipeline_runs(self, limit: int = 1) -> list:
        return self._get(f"pipeline_runs:{limit}", "ai/pipeline-runs", {"limit": limit})

    # ---------------- เวลา
    def reference_date(self) -> date:
        inv = self.inventory()
        if inv and inv.get("reference_date"):
            return date.fromisoformat(str(inv["reference_date"])[:10])
        if settings.DEMO_DATE:
            return date.fromisoformat(settings.DEMO_DATE)
        return self._clock().date()

    def now(self) -> datetime:
        """วันของระบบ (DEMO_DATE) + เวลานาฬิกาไทยตอนนี้ กติกาเดียวกับ server/core/dates.py: now_bkk()"""
        return simulated_now(self.reference_date(), self._clock())

    # ---------------- Optimizer (dry-run)
    def plan(self, key: str = "base", inputs: Optional[dict] = None) -> dict:
        """ผล run_optimizer ของข้อมูลจริง (key="base") หรือของ inputs ที่ถูกแก้ (what-if) ไม่บันทึกอะไร"""
        if key not in self._plans:
            data = copy.deepcopy(inputs if inputs is not None else self.optimize_inputs())
            self._plans[key] = run_optimizer(data, products_catalog=self.products(), now=self.now(),
                                             cfg=AGENT_OPT_CFG, strict=False)
        return self._plans[key]
