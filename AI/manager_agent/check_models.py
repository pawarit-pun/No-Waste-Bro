"""ตรวจว่าโมเดลบน Bedrock เรียก tool ผ่าน Converse API ได้จริงในบัญชีนี้ (SCP ของ sandbox อาจบล็อกบางโมเดล)

รัน (CloudShell หรือเครื่องที่ aws configure แล้ว) จากโฟลเดอร์ AI:
    python manager_agent/check_models.py
    python manager_agent/check_models.py --region us-east-1 --models amazon.nova-lite-v1:0 qwen.qwen3-next-80b-a3b

ผลต่อโมเดล:
    TOOL_USE_OK     ขอเรียก tool ถูกตัว + อาร์กิวเมนต์ถูก แล้วตอบต่อจากผลของ tool ได้ -> ใช้คุมวงรอบ agent ได้
    TEXT_ONLY       ตอบได้แต่ไม่ขอเรียก tool (หรือ Converse ไม่รับ toolConfig) -> ใช้เป็นตัวเขียนคำตอบสำรองเท่านั้น
    ERROR           เรียกโมเดลไม่ได้ (สิทธิ์ / SCP / region) ดูข้อความ
"""
import argparse
import json
import sys
import time

TOOL = {
    "toolSpec": {
        "name": "get_lot",
        "description": "ดูข้อมูล lot สินค้า 1 lot จากรหัส lot",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {"lot_id": {"type": "string", "description": "รหัส lot เช่น LOT-000020"}},
            "required": ["lot_id"],
        }},
    }
}
FAKE_RESULT = {"lot_id": "LOT-000020", "product": "กล้วยหอม 1kg", "current_quantity": 205, "expiration_date": "2026-10-20"}
QUESTION = "LOT-000020 เหลือกี่แพ็ก หมดอายุวันไหน"


def check(client, model_id: str) -> dict:
    started = time.time()
    messages = [{"role": "user", "content": [{"text": QUESTION}]}]
    try:
        r1 = client.converse(modelId=model_id, messages=messages,
                             system=[{"text": "ตอบภาษาไทย ใช้ tool เพื่อหาข้อมูล lot"}],
                             toolConfig={"tools": [TOOL]}, inferenceConfig={"maxTokens": 400, "temperature": 0})
    except Exception as e:  # noqa: BLE001 รายงานทุก error ให้ผู้ใช้เห็น
        return {"model": model_id, "result": "ERROR", "detail": f"{type(e).__name__}: {e}"[:400]}
    blocks = r1["output"]["message"]["content"]
    uses = [b["toolUse"] for b in blocks if "toolUse" in b]
    if r1.get("stopReason") != "tool_use" or not uses:
        text = "".join(b.get("text", "") for b in blocks)
        return {"model": model_id, "result": "TEXT_ONLY", "stop_reason": r1.get("stopReason"), "text": text[:200]}
    use = uses[0]
    args_ok = use.get("name") == "get_lot" and str(use.get("input", {}).get("lot_id", "")).upper() == "LOT-000020"
    messages += [r1["output"]["message"],
                 {"role": "user", "content": [{"toolResult": {"toolUseId": use["toolUseId"],
                                                               "content": [{"json": FAKE_RESULT}], "status": "success"}}]}]
    try:
        r2 = client.converse(modelId=model_id, messages=messages, toolConfig={"tools": [TOOL]},
                             inferenceConfig={"maxTokens": 400, "temperature": 0})
    except Exception as e:  # noqa: BLE001
        return {"model": model_id, "result": "ERROR", "detail": f"หลังส่ง toolResult: {type(e).__name__}: {e}"[:400]}
    text = "".join(b.get("text", "") for b in r2["output"]["message"]["content"])
    grounded = "205" in text
    return {"model": model_id, "result": "TOOL_USE_OK" if args_ok and grounded else "TOOL_USE_PARTIAL",
            "tool_args": use.get("input"), "answer": text[:200], "uses_tool_result": grounded,
            "seconds": round(time.time() - started, 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--models", nargs="+", default=["amazon.nova-lite-v1:0", "qwen.qwen3-next-80b-a3b"])
    args = ap.parse_args()
    import boto3

    client = boto3.client("bedrock-runtime", region_name=args.region)
    results = [check(client, m) for m in args.models]
    print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0 if results and results[0]["result"] == "TOOL_USE_OK" else 1


if __name__ == "__main__":
    sys.exit(main())
