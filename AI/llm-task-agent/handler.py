"""AWS Lambda entry point (handler.lambda_handler).

event, all optional: {"run_id": "...", "dry_run": false, "limit": 5}
Set OUTPUT_DIR=/tmp/task_agent (only /tmp is writable).
"""

from agent import run
from api_client import ApiSource
from knowledge_base import KBRetriever
from llm import BedrockLLM


def lambda_handler(event, context):
    event = event or {}
    report = run(
        source=ApiSource(),
        retriever=KBRetriever(),
        llm=BedrockLLM(),
        dry_run=bool(event.get("dry_run", False)),
        run_id=event.get("run_id"),
        limit=event.get("limit"),
    )
    # Audit trail in CloudWatch Logs
    print({"summary": report["summary"], "post_results": report["post_results"], "audit": report["audit"]})
    return {"run_id": report["run_id"], "summary": report["summary"], "post_results": report["post_results"]}
