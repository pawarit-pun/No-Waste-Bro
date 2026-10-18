"""Task Agent: decision -> Build Facts -> Retrieve SOP -> LLM -> Validate -> POST /tasks -> report

Attempts per decision:
  1. PRIMARY_MODEL
  2. PRIMARY_MODEL again, with its previous answer and the validator errors (one fix)
  3. FALLBACK_MODEL, fresh conversation plus the latest errors
  4. Standard text from templates, so every decision still reaches staff
"""

import json
import os
from collections import defaultdict
from datetime import datetime

from api_client import ApiError
from config import TH_TZ, settings
from facts import Facts, build_facts
from llm import build_user_prompt, feedback_prompt, parse_json
from models import InstructionStep, TaskCreate
from steps import StepSpec, fallback_reasoning, required_steps
from task_generator import build_task, fallback_steps, resolve_now
from validate import validate_output

TEMPLATE = "TEMPLATE"
MAX_RAW_TEXT = 4000  # raw model answer kept in the report for prompt tuning


def clean_detail(text: str) -> str:
    """The model sometimes copies the prompt's quotes around values ('33.25')."""
    return " ".join(text.replace("'", "").replace('"', "").split())


def write_steps(facts: Facts, specs: list[StepSpec], sop: list[dict], llm) -> dict:
    """Return {ai_reasoning, instruction_steps, model_used, attempts}."""
    attempts: list[dict] = []
    if llm is not None:
        user_prompt = build_user_prompt(facts, specs, sop)
        messages = [{"role": "user", "text": user_prompt}]
        plan = [settings.PRIMARY_MODEL, settings.PRIMARY_MODEL, settings.FALLBACK_MODEL]

        for n, model in enumerate(plan):
            if n == 2:
                # New model: start a fresh conversation but pass on the latest errors
                last_errors = attempts[-1]["errors"]
                text = user_prompt + ("\n\n" + feedback_prompt(last_errors, specs) if last_errors else "")
                messages = [{"role": "user", "text": text}]

            record = {"model": model, "errors": [], "text": ""}
            try:
                response = llm.chat(model, messages)
                record.update(
                    text=response["text"][:MAX_RAW_TEXT],
                    latency_ms=response.get("latency_ms"),
                    usage=response.get("usage", {}),
                )
                out = parse_json(response["text"])
                record["errors"] = validate_output(out, facts, specs)
            except Exception as e:  # Bedrock error or broken JSON counts as a failed attempt
                record["errors"] = [f"{type(e).__name__}: {e}"]
            attempts.append(record)

            if not record["errors"]:
                steps = [
                    InstructionStep(title=spec.title, detail=clean_detail(step["detail"]))
                    for spec, step in zip(specs, out["instruction_steps"])
                ]
                return {
                    "ai_reasoning": out["ai_reasoning"].strip(),
                    "instruction_steps": steps,
                    "model_used": model,
                    "attempts": attempts,
                }
            if n == 0 and record["text"]:
                messages = messages + [
                    {"role": "assistant", "text": record["text"]},
                    {"role": "user", "text": feedback_prompt(record["errors"], specs)},
                ]

    return {
        "ai_reasoning": fallback_reasoning(facts),
        "instruction_steps": fallback_steps(specs),
        "model_used": TEMPLATE,
        "attempts": attempts,
    }


def batch_key(facts: Facts) -> str:
    """POST /tasks is all-or-nothing, so kitchen tasks go in one batch per kitchen + day
    (a full kitchen then only fails its own tasks). Everything else goes in one batch."""
    if facts.action == "KITCHEN_REPURPOSE":
        day = facts.due_dt.date().isoformat() if facts.due_dt else "no-date"
        return f"KITCHEN:{facts.kitchen or 'UNKNOWN'}@{day}"
    return "GENERAL"


def post_batches(source, batches: dict[str, list[TaskCreate]], dry_run: bool) -> list[dict]:
    results = []
    for key, tasks in batches.items():
        result = {"batch": key, "count": len(tasks)}
        if dry_run:
            results.append({**result, "status": "DRY_RUN"})
            continue
        try:
            response = source.post_tasks(tasks)
            results.append({
                **result,
                "status": "CREATED",
                "created": response.get("created"),
                "assigned": [t.get("assigned_staff_id") for t in response.get("tasks", [])],
                "kitchen_bookings": response.get("kitchen_bookings", []),
            })
        except ApiError as e:
            # The decisions stay PENDING so a manager can see and retry them
            results.append({**result, "status": f"FAILED_{e.status}", "error": e.body[:500]})
    return results


def run(
    source,
    retriever,
    llm,
    dry_run: bool = True,
    run_id: str | None = None,
    limit: int | None = None,
) -> dict:
    now = resolve_now()
    used_run_id, decisions = source.pending_decisions(run_id)
    if limit:
        decisions = decisions[:limit]

    tasks: list[TaskCreate] = []
    audit: list[dict] = []
    batches: dict[str, list[TaskCreate]] = defaultdict(list)

    for decision in decisions:
        facts = build_facts(decision)
        specs = required_steps(facts)
        try:
            sop, sop_error = retriever.retrieve(facts.action, facts.category), None
        except Exception as e:  # Knowledge Base down: continue with standard steps
            sop, sop_error = [], f"{type(e).__name__}: {e}"

        written = write_steps(facts, specs, sop, llm)
        task = build_task(facts, now, written["ai_reasoning"], written["instruction_steps"])
        tasks.append(task)
        batches[batch_key(facts)].append(task)
        audit.append({
            "decision_id": facts.decision_id,
            "lot_id": facts.lot_id,
            "action": facts.action,
            "quantity": facts.qty,
            "priority": task.priority,
            "model_used": written["model_used"],
            "fallback_used": written["model_used"] == TEMPLATE,
            "attempts": written["attempts"],
            "sop_docs": [{"doc_id": c["doc_id"], "score": c["score"]} for c in sop],
            "sop_error": sop_error,
        })

    post_results = post_batches(source, batches, dry_run)

    report = {
        "run_id": used_run_id,
        "generated_at": datetime.now(TH_TZ).isoformat(),
        "priority_now": now.isoformat(),
        "dry_run": dry_run,
        "models": {"primary": settings.PRIMARY_MODEL, "fallback": settings.FALLBACK_MODEL},
        "kb_id": settings.BEDROCK_KB_ID,
        "summary": {
            "decisions": len(decisions),
            "tasks": len(tasks),
            "llm_ok": sum(1 for a in audit if not a["fallback_used"]),
            "template_fallback": sum(1 for a in audit if a["fallback_used"]),
            "llm_calls": sum(len(a["attempts"]) for a in audit),
        },
        "post_results": post_results,
        "audit": audit,
        "tasks": [t.model_dump(mode="json") for t in tasks],
    }
    report["report_path"] = save_report(report)
    return report


def save_report(report: dict) -> str:
    """Keep every run as a JSON audit trail."""
    os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
    stamp = datetime.now(TH_TZ).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(settings.OUTPUT_DIR, f"task_agent_{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path
