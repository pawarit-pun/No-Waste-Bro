from typing import Any, Optional

from pydantic import BaseModel, Field


class DecisionContext(BaseModel):
    assessment: dict[str, Any] = Field(default_factory=dict)
    lot: dict[str, Any] = Field(default_factory=dict)
    product: dict[str, Any] = Field(default_factory=dict)
    recipe: dict[str, Any] = Field(default_factory=dict)
    partner: dict[str, Any] = Field(default_factory=dict)


class OptimizationDecision(BaseModel):
    decision_id: str
    action_type: str

    # Identifiers
    run_id: Optional[str] = None
    assessment_id: Optional[str] = None
    lot_id: Optional[str] = None

    # Recommended action
    action_quantity: float = 0
    discount_pct: float = 0
    new_recommended_price: Optional[float] = None
    target_recipe_id: Optional[str] = None
    batch_count: int = 0
    target_partner_id: Optional[str] = None

    # Decision information
    due_by: Optional[str] = None
    expected_profit_impact: Optional[float] = None
    decision_score: Optional[float] = None
    status: Optional[str] = None
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    optimizer_version: Optional[str] = None
    created_at: Optional[str] = None

    # Context used by the LLM
    assessment: dict[str, Any] = Field(default_factory=dict)
    lot: dict[str, Any] = Field(default_factory=dict)
    product: dict[str, Any] = Field(default_factory=dict)
    recipe: dict[str, Any] = Field(default_factory=dict)
    partner: dict[str, Any] = Field(default_factory=dict)


class TaskCreate(BaseModel):
    decision_id: str
    priority: int = Field(ge=1, le=5)
    ai_reasoning: str
    staff_instructions: str


class TaskBatchCreate(BaseModel):
    tasks: list[TaskCreate] = Field(min_length=1)
