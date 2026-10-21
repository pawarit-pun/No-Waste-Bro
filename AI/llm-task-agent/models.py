from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class OptimizationDecision(BaseModel):
    """One item of GET /optimization-decisions (decision + context)."""

    decision_id: str
    action_type: str  # MARKDOWN | KITCHEN_REPURPOSE | DONATE | ANIMAL_FEED | COMPOST | ANAEROBIC_DIGESTION | LANDFILL | DISCARD

    # Identifiers
    run_id: Optional[str] = None
    assessment_id: Optional[str] = None
    lot_id: Optional[str] = None

    # Recommended action (fields not used by an action come back as null)
    action_quantity: float
    discount_pct: Optional[float] = None
    new_recommended_price: Optional[float] = None
    target_recipe_id: Optional[str] = None
    batch_count: Optional[int] = None
    target_partner_id: Optional[str] = None

    # Decision information
    due_by: Optional[str] = None
    expected_profit_impact: Optional[float] = None
    decision_score: Optional[float] = None
    status: Optional[str] = None
    task_id: Optional[str] = None
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    optimizer_version: Optional[str] = None
    created_at: Optional[str] = None

    # Context for the LLM (null from the server becomes {})
    assessment: dict[str, Any] = Field(default_factory=dict)
    lot: dict[str, Any] = Field(default_factory=dict)
    product: dict[str, Any] = Field(default_factory=dict)
    recipe: dict[str, Any] = Field(default_factory=dict)
    partner: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "assessment", "lot", "product", "recipe", "partner", "alternatives",
        mode="before",
    )
    @classmethod
    def _none_to_empty(cls, value, info):
        if value is None:
            return [] if info.field_name == "alternatives" else {}
        return value


# Limits match the server's TaskCreate
class InstructionStep(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    detail: str = Field(min_length=1, max_length=300)


class TaskCreate(BaseModel):
    """One plan for POST /pending-tasks (waits for a manager to approve before it becomes a staff task)."""
    decision_id: str
    priority: int = Field(ge=1, le=5)
    ai_reasoning: str
    staff_instructions: str
    instruction_steps: list[InstructionStep] = Field(min_length=1, max_length=8)
    model_used: Optional[str] = Field(None, max_length=120)  # model that wrote the text, or "TEMPLATE"


class TaskBatchCreate(BaseModel):
    tasks: list[TaskCreate] = Field(min_length=1)
