"""Food-waste Optimizer — ทางเข้าสำหรับทีมอื่น

    from ai_engine.optimizer import run_optimizer, optimize_and_post, run_full_pipeline, OptimizerConfig

    result = run_optimizer(optimize_inputs_json, demand=None)   # -> {"plan", "payload", "violations", ...}
    optimize_and_post(dry_run=False)                            # ดึงข้อมูล -> optimize -> POST /optimization-decisions
"""
from ai_engine.optimizer.config import ACTION_BY_METHOD, OptimizerConfig
from ai_engine.optimizer.io import ApiClient, ApiError, DEFAULT_API_BASE
from ai_engine.optimizer.pipeline import (PlanValidationError, optimize_and_post, run_full_pipeline,
                                          run_optimizer)

__all__ = ["run_optimizer", "optimize_and_post", "run_full_pipeline", "OptimizerConfig", "ApiClient",
           "ApiError", "DEFAULT_API_BASE", "PlanValidationError", "ACTION_BY_METHOD"]
