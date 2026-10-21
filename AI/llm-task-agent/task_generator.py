from datetime import datetime

from config import TH_TZ, settings
from facts import Facts
from models import InstructionStep, TaskCreate
from steps import StepSpec, compute_priority, staff_instructions


def resolve_now(default: str | None = None) -> datetime:
    """AGENT_NOW -> default -> DEMO_DATE 08:00 -> real time."""
    if settings.AGENT_NOW:
        return datetime.fromisoformat(settings.AGENT_NOW).astimezone(TH_TZ)
    if default:
        return datetime.fromisoformat(default).astimezone(TH_TZ)
    if settings.DEMO_DATE:
        return datetime.fromisoformat(f"{settings.DEMO_DATE}T08:00:00+07:00")
    return datetime.now(TH_TZ)


def fallback_steps(specs: list[StepSpec]) -> list[InstructionStep]:
    """Standard step text when the LLM is off or fails."""
    return [InstructionStep(title=s.title, detail=s.fallback) for s in specs]


def build_task(
    facts: Facts,
    now: datetime,
    ai_reasoning: str,
    instruction_steps: list[InstructionStep],
    model_used: str | None = None,
) -> TaskCreate:
    """Code-owned fields + written (LLM or standard) fields."""
    return TaskCreate(
        decision_id=facts.decision_id,
        priority=compute_priority(facts, now),
        ai_reasoning=ai_reasoning,
        staff_instructions=staff_instructions(facts),
        instruction_steps=instruction_steps,
        model_used=model_used,
    )
