"""Run the Task Agent locally. Nothing is POSTed without --post.

  python main.py --source mock --no-llm --no-kb     # fully offline
  python main.py --source mock                      # sample data + real KB and LLM
  python main.py --source api                       # real decisions, preview
  python main.py --source api --post                # real decisions, send plans to the review queue
"""

import argparse
import json

from agent import run
from config import settings


class MockSource:
    """Decisions from mock_data.py (read only)."""

    def pending_decisions(self, run_id=None):
        from mock_data import get_mock_decisions

        return "mock-run", get_mock_decisions()

    def post_pending_tasks(self, tasks):
        raise RuntimeError("MockSource cannot send plans; use --source api")

    def set_lots_ai_status(self, lot_ids, ai_status):
        raise RuntimeError("MockSource cannot update lots; use --source api")


def print_report(report: dict) -> None:
    print(json.dumps(report["summary"], ensure_ascii=False))
    for audit, task in zip(report["audit"], report["tasks"]):
        tries = " -> ".join(
            f"{a['model'].split('.')[-1]}:{'OK' if not a['errors'] else len(a['errors'])}"
            for a in audit["attempts"]
        ) or "-"
        sop = [d["doc_id"] for d in audit["sop_docs"]]
        print(f"\n[{audit['action']}] {audit['lot_id']} qty={audit['quantity']} P{audit['priority']} "
              f"model={audit['model_used']} tries={tries} sop={sop}")
        if audit["sop_error"]:
            print("  ! KB:", audit["sop_error"])
        print("  staff:", task["staff_instructions"])
        print("  reasoning:", task["ai_reasoning"])
        for i, step in enumerate(task["instruction_steps"], 1):
            print(f"  {i}. {step['title']}: {step['detail']}")
        for attempt in audit["attempts"]:
            for error in attempt["errors"]:
                print(f"     ! {attempt['model']}: {error}")
    print("\nPOST /pending-tasks (waiting for manager approval):", json.dumps(
        [{k: v for k, v in r.items() if k != "decision_ids"} for r in report["post_results"]], ensure_ascii=False))
    lots = report["lot_status"]
    print(f"LOTS -> CHECKED ({lots['status']}): {lots['to_check']}")
    for lot in lots["pending_lots"]:
        print(f"  stays PROCESSING: {lot['lot_id']} {lot['reasons']}")
    if lots.get("not_found"):
        print("  not_found:", lots["not_found"])
    if lots.get("error"):
        print("  ! PATCH:", lots["error"])
    print("report:", report["report_path"])


def main():
    parser = argparse.ArgumentParser(description="No-Waste-Bro LLM Task Agent")
    parser.add_argument("--source", choices=["api", "mock"], default="api")
    parser.add_argument("--post", action="store_true", help="really POST /pending-tasks (default: preview only)")
    parser.add_argument("--no-llm", action="store_true", help="skip the LLM, use standard text")
    parser.add_argument("--no-kb", action="store_true", help="skip the Knowledge Base")
    parser.add_argument("--run-id", help="decision run to use (default: latest)")
    parser.add_argument("--limit", type=int, help="process only the first N decisions")
    parser.add_argument("--now", help="time used for priority, e.g. 2026-10-19T08:00:00+07:00")
    args = parser.parse_args()

    if args.now:
        settings.AGENT_NOW = args.now
    if args.post and args.source != "api":
        parser.error("--post only works with --source api")

    if args.source == "api":
        from api_client import ApiSource
        source = ApiSource()
    else:
        source = MockSource()

    if args.no_kb:
        from knowledge_base import NullRetriever
        retriever = NullRetriever()
    else:
        from knowledge_base import KBRetriever
        retriever = KBRetriever()

    if args.no_llm:
        llm = None
    else:
        from llm import BedrockLLM
        llm = BedrockLLM()

    report = run(source, retriever, llm, dry_run=not args.post, run_id=args.run_id, limit=args.limit)
    print_report(report)


if __name__ == "__main__":
    main()
