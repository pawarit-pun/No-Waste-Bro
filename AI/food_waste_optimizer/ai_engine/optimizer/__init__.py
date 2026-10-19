"""Food-waste Optimizer — ทางเข้าสำหรับทีมอื่น

    from ai_engine.optimizer import run_optimizer, optimize_and_post, OptimizerConfig, ApiClient

    result = run_optimizer(optimize_inputs_json, products_catalog=products_json)   # คำนวณอย่างเดียว
    result["payload"]       # body ของ POST /api/v1/optimization-decisions
    result["allocations"]   # weight_kg / share_pct / เงิน ต่อส่วนของ lot (ไม่เขียนลงตาราง ส่งให้ส่วนอื่นใช้)
    optimize_and_post(dry_run=False)                                                # อ่าน -> คำนวณ -> บันทึกผ่าน server
"""
from ai_engine.optimizer.config import ACTION_BY_METHOD, OptimizerConfig, simulated_now
from ai_engine.optimizer.io import DEFAULT_API_BASE, ApiClient, ApiError, load_from_api, pick_run
from ai_engine.optimizer.pipeline import (PlanValidationError, attach_decision_ids, lots_to_release,
                                          optimize_and_post, run_optimizer)

__all__ = ["run_optimizer", "optimize_and_post", "attach_decision_ids", "lots_to_release", "OptimizerConfig",
           "simulated_now", "ApiClient", "ApiError", "load_from_api", "pick_run", "DEFAULT_API_BASE", "PlanValidationError",
           "ACTION_BY_METHOD"]