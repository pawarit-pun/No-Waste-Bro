"""Task Agent: decision -> Facts -> SOP -> LLM -> Validate -> POST /tasks -> lots CHECKED -> report

Per decision: primary model -> primary fixes its errors once -> fallback model -> standard text.
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
MAX_RAW_TEXT = 4000  # raw answer kept in the report


def clean_detail(text: str) -> str:
    """Remove quotes the model copies from the prompt ('33.25')."""
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
                # Fallback model: fresh conversation + latest errors
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
            except Exception as e:  # Bedrock error or bad JSON = failed attempt
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
    """POST is all-or-nothing: one batch per kitchen + day, so a full kitchen fails only its own tasks."""
    if facts.action == "KITCHEN_REPURPOSE":
        day = facts.due_dt.date().isoformat() if facts.due_dt else "no-date"
        return f"KITCHEN:{facts.kitchen or 'UNKNOWN'}@{day}"
    return "GENERAL"


def post_batches(source, batches: dict[str, list[TaskCreate]], dry_run: bool) -> list[dict]:
    results = []
    for key, tasks in batches.items():
        result = {"batch": key, "count": len(tasks), "decision_ids": [t.decision_id for t in tasks]}
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
            # Decisions stay PENDING for a manager to retry
            results.append({**result, "status": f"FAILED_{e.status}", "error": e.body[:500]})
    return results


def update_lot_status(source, decisions: list, post_results: list[dict], dry_run: bool) -> dict:
    """Step 8: lots whose every decision in this run got a task -> CHECKED (one PATCH call).

    Lots with a failed batch or an unprocessed decision (--limit) stay PROCESSING.
    A failed PATCH is recorded, never raised.
    """
    created = {d_id for r in post_results if r["status"] in ("CREATED", "DRY_RUN") for d_id in r["decision_ids"]}
    failed = {d_id: r["status"] for r in post_results if r["status"].startswith("FAILED") for d_id in r["decision_ids"]}

    reasons: dict[str, set[str]] = defaultdict(set)
    for d in decisions:
        if d.lot_id and d.decision_id not in created:
            reasons[d.lot_id].add(failed.get(d.decision_id, "NOT_PROCESSED"))
    lots = {d.lot_id for d in decisions if d.lot_id}
    to_check = sorted(lots - set(reasons))
    pending = [{"lot_id": lot, "reasons": sorted(r)} for lot, r in sorted(reasons.items())]

    result = {"to_check": to_check, "pending_lots": pending}
    if dry_run:
        return {**result, "status": "DRY_RUN"}
    if not to_check:
        return {**result, "status": "SKIPPED"}
    try:
        response = source.set_lots_ai_status(to_check, "CHECKED")
        return {
            **result,
            "status": "UPDATED",
            "updated": [u.get("lot_id") for u in response.get("updated", [])],
            "not_found": response.get("not_found", []),
        }
    except Exception as e:  # incl. 404 when no lot exists
        status = f"FAILED_{e.status}" if isinstance(e, ApiError) else "FAILED"
        return {**result, "status": status, "error": str(e)[:500]}


def run(
    source,
    retriever,
    llm,
    dry_run: bool = True,
    run_id: str | None = None,
    limit: int | None = None,
) -> dict:
    now = resolve_now()
    used_run_id, all_decisions = source.pending_decisions(run_id)
    decisions = all_decisions[:limit] if limit else all_decisions

    tasks: list[TaskCreate] = []
    audit: list[dict] = []
    batches: dict[str, list[TaskCreate]] = defaultdict(list)

    for decision in decisions:
        facts = build_facts(decision)
        specs = required_steps(facts)
        try:
            sop, sop_error = retriever.retrieve(facts.action, facts.category), None
        except Exception as e:  # KB down: continue without SOP
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
    lot_status = update_lot_status(source, all_decisions, post_results, dry_run)

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
            "lots_checked": len(lot_status.get("updated", [])),
            "lots_pending": len(lot_status["pending_lots"]),
        },
        "post_results": post_results,
        "lot_status": lot_status,
        "audit": audit,
        "tasks": [t.model_dump(mode="json") for t in tasks],
    }
    report["report_path"] = save_report(report)
    return report


def save_report(report: dict) -> str:
    """JSON audit trail of every run."""
    os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
    stamp = datetime.now(TH_TZ).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(settings.OUTPUT_DIR, f"task_agent_{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path
