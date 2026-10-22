"""ทดลองถาม agent จากเครื่อง (ต้องมี AWS credentials ที่เรียก Bedrock us-east-1 ได้) รันจากโฟลเดอร์ AI:

    python -m manager_agent "วันนี้มีอะไรด่วนบ้าง"
    python -m manager_agent "ทำไม LOT-000020 ถึงส่งเข้าครัว" --lot LOT-000020 --page inventory
    API_BASE_URL=http://localhost:8000/api/v1 python -m manager_agent "..."     # ใช้ server ในเครื่อง
"""
import argparse
import json

from .handler import lambda_handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--page")
    ap.add_argument("--lot")
    args = ap.parse_args()
    out = lambda_handler({"question": args.question, "context": {"page": args.page, "lot_id": args.lot}})
    print(out.get("answer") or out)
    print("\n---", json.dumps({k: out.get(k) for k in ("model_used", "latency_ms", "tool_calls", "warnings", "usage")},
                             ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
