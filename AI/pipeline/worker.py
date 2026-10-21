"""AI pipeline worker: Risk Scanner -> Optimizer -> LLM Task Agent ต่อกันตามลำดับ

บน AWS: Lambda (container image) ที่ server สั่งแบบไม่รอผลจาก POST /api/v1/ai/pipeline-runs
ในเครื่อง (debug): python worker.py [--stop-after SCAN|OPTIMIZE|TASKS] [--pipeline-run-id <id>]

แต่ละขั้นเรียกสคริปต์เดิมของทีม AI เป็น process แยก (ไม่ import ข้ามโปรเจกต์ เพราะชื่อ module ชนกัน)
แล้วอ่านผลจากไฟล์ที่สคริปต์เขียนไว้ใน OUTPUT_DIR ของขั้นนั้น

  SCAN      risk_forecaster/run_scan.py --source api          -> run_id, จำนวน lot HIGH / CRITICAL
  OPTIMIZE  food_waste_optimizer/run_optimize.py --run-id ID  -> จำนวน decision ที่บันทึก
  TASKS     llm-task-agent/main.py --source api --run-id ID --post -> จำนวน task, batch ที่ POST ไม่ผ่าน

จบก่อนครบได้เมื่อไม่มีอะไรต้องทำต่อ (ไม่มี lot IDLE / ไม่มี lot เสี่ยง / 0 decision) = SUCCEEDED + message
สถานะทุกขั้นส่งกลับ server ด้วย PATCH /ai/pipeline-runs/{id}
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BKK = timezone(timedelta(hours=7))
AI_DIR = Path(os.getenv("AI_DIR") or Path(__file__).resolve().parent.parent)
API_BASE_URL = (os.getenv("API_BASE_URL")
                or "https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1").rstrip("/")
STEPS = ("SCAN", "OPTIMIZE", "TASKS")
AT_RISK_LEVELS = ("HIGH", "CRITICAL")   # = FORWARD_LEVELS ใน risk_forecaster/common/config.py
LOG_TAIL_CHARS = 3000

# โฟลเดอร์ + คำสั่ง + เวลาสูงสุด (วินาที) ของแต่ละขั้น รวมกันต้องน้อยกว่า timeout ของ Lambda (900)
# PYTHON_SCAN / PYTHON_OPTIMIZE / PYTHON_TASKS: ใช้ python ของ venv แต่ละโฟลเดอร์ตอนรันในเครื่อง
STAGE = {
    "SCAN": {"dir": "risk_forecaster", "timeout": 240,
             "args": lambda run_id: ["run_scan.py", "--source", "api"]},
    "OPTIMIZE": {"dir": "food_waste_optimizer", "timeout": 150,
                 "args": lambda run_id: ["run_optimize.py", "--run-id", run_id]},
    "TASKS": {"dir": "llm-task-agent", "timeout": 450,
              "args": lambda run_id: ["main.py", "--source", "api", "--run-id", run_id, "--post"]},
}
OPTIMIZE_EXIT = {1: "server ตอบ error หรือต่อ server ไม่ได้", 2: "แผนไม่ผ่านการตรวจกฎ (ไม่ได้บันทึกอะไร)",
                 3: "ไม่มีรอบสแกนที่พร้อมตัดสินใจ (วันที่สแกนไม่ตรงกับ DEMO_DATE ของ server?)"}


class PipelineError(Exception):
    """ขั้นไหนพัง: ข้อความนี้ไปอยู่ใน pipeline_runs.error"""


class Reporter:
    """ส่งสถานะกลับ server (ไม่มี pipeline_run_id = รันในเครื่องเฉย ๆ พิมพ์อย่างเดียว)"""

    def __init__(self, pipeline_run_id):
        self.pipeline_run_id = pipeline_run_id
        self.steps = {}

    def patch(self, **fields):
        fields = {k: v for k, v in fields.items() if v is not None}
        print("[pipeline]", json.dumps({k: v for k, v in fields.items() if k != "steps"}, ensure_ascii=False))
        if not self.pipeline_run_id:
            return
        req = urllib.request.Request(
            f"{API_BASE_URL}/ai/pipeline-runs/{self.pipeline_run_id}",
            data=json.dumps(fields, ensure_ascii=False).encode(), method="PATCH",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                res.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:500]
            if e.code in (404, 409):   # ไม่มีรอบนี้ / จบไปแล้ว: หยุด ไม่ทำงานซ้ำซ้อน
                raise PipelineError(f"server ปฏิเสธการอัปเดตสถานะ ({e.code}): {body}")
            print(f"[pipeline] warn: PATCH status {e.code}: {body}", file=sys.stderr)
        except OSError as e:
            print(f"[pipeline] warn: PATCH failed: {e}", file=sys.stderr)

    def step(self, name, **info):
        self.steps[name] = {**self.steps.get(name, {}), **info}
        self.patch(current_step=name, steps=self.steps)


def stage_env(out_dir: Path) -> dict:
    """env เดียวกันทุกขั้น: API เดียวกัน + เวลาเดียวกัน (DEMO_DATE + เวลาจริงตอนเริ่ม)"""
    env = dict(os.environ, API_BASE_URL=API_BASE_URL, OUTPUT_DIR=str(out_dir), PYTHONUNBUFFERED="1")
    demo_date = os.getenv("DEMO_DATE")
    if demo_date:
        now = datetime.now(BKK)
        env.setdefault("DEMO_TIME", now.strftime("%H:%M"))                                   # Optimizer
        env.setdefault("AGENT_NOW", f"{demo_date}T{now:%H:%M:%S}+07:00")                    # LLM priority
    return env


def run_stage(name: str, run_id, work_dir: Path, reporter: Reporter) -> tuple[int, Path, str]:
    spec = STAGE[name]
    out_dir = work_dir / name.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    python = os.getenv(f"PYTHON_{name}") or sys.executable
    cmd = [python, *spec["args"](run_id)]
    reporter.step(name, status="RUNNING", started_at=datetime.now(BKK).isoformat())
    print(f"\n[pipeline] ===== {name}: {' '.join(cmd[1:])} (cwd={spec['dir']})", flush=True)

    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=AI_DIR / spec["dir"], env=stage_env(out_dir),
                              capture_output=True, text=True, timeout=spec["timeout"])
        code, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        code = -1
        output = ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) \
            + f"\n[pipeline] timeout หลัง {spec['timeout']} วินาที"
    print(output, flush=True)   # log เต็มอยู่ใน CloudWatch
    reporter.steps[name].update(exit_code=code, seconds=round(time.monotonic() - started, 1),
                                log_tail=output[-LOG_TAIL_CHARS:])
    return code, out_dir, output


def _only_subdir(out_dir: Path):
    dirs = sorted(p for p in out_dir.iterdir() if p.is_dir())
    return dirs[-1] if dirs else None


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def step_scan(work_dir, reporter) -> dict:
    code, out_dir, output = run_stage("SCAN", None, work_dir, reporter)
    if code != 0:
        raise PipelineError(f"SCAN ล้ม (exit {code}) ถ้าพังระหว่างประเมิน run_scan.py คืนล็อตเป็น IDLE ให้เอง ดู steps.SCAN.log_tail")
    result_dir = _only_subdir(out_dir)
    if "ไม่มีล็อต IDLE ให้สแกน" in output or result_dir is None:
        return {"done": True, "message": "ไม่มี lot IDLE ให้สแกน"}
    response = _read_json(result_dir / "risk_assessments_response.json")
    if not response or not response.get("run_id"):
        raise PipelineError("SCAN ไม่ได้ run_id (ไม่ได้ POST /risk-assessments)")
    with open(result_dir / "summary.csv", encoding="utf-8") as f:
        levels = [row["risk_level"] for row in csv.DictReader(f)]
    at_risk = sum(level in AT_RISK_LEVELS for level in levels)
    summary = {"run_id": response["run_id"], "lots": len(levels), "at_risk_lots": at_risk,
               "levels": {lv: levels.count(lv) for lv in sorted(set(levels))}}
    reporter.steps["SCAN"].update(status="OK", summary=summary)
    reporter.patch(run_id=summary["run_id"], at_risk_lots=at_risk, steps=reporter.steps)
    if at_risk == 0:
        return {**summary, "done": True, "message": f"สแกน {len(levels)} lot ไม่มี lot HIGH / CRITICAL"}
    return summary


def step_optimize(run_id, work_dir, reporter) -> dict:
    code, out_dir, _ = run_stage("OPTIMIZE", run_id, work_dir, reporter)
    if code != 0:
        raise PipelineError(f"OPTIMIZE ล้ม (exit {code}): {OPTIMIZE_EXIT.get(code, 'ดู steps.OPTIMIZE.log_tail')}")
    result_dir = _only_subdir(out_dir)
    saved = _read_json(result_dir / "decisions_response.json") if result_dir else None
    request = _read_json(result_dir / "decisions_request.json") if result_dir else None
    created = (saved or {}).get("created", len((saved or {}).get("decisions", [])))
    actions = {}
    for d in (request or {}).get("decisions", []):
        actions[d["action_type"]] = actions.get(d["action_type"], 0) + 1
    summary = {"decisions_created": created, "actions": actions}
    reporter.steps["OPTIMIZE"].update(status="OK", summary=summary)
    reporter.patch(decisions_created=created, steps=reporter.steps)
    if created == 0:
        return {**summary, "done": True, "message": "Optimizer ไม่ได้สร้าง decision (ขายราคาปกติได้หมด หรือตัดสินใจไปแล้ว)"}
    return summary


def step_tasks(run_id, work_dir, reporter) -> dict:
    code, out_dir, _ = run_stage("TASKS", run_id, work_dir, reporter)
    if code != 0:
        raise PipelineError(f"TASKS ล้ม (exit {code}) ดู steps.TASKS.log_tail")
    reports = sorted(out_dir.glob("task_agent_*.json"))
    if not reports:
        raise PipelineError("TASKS ไม่มี report (task_agent_*.json)")
    report = _read_json(reports[-1])
    posts = report.get("post_results", [])
    created = sum(p.get("created") or 0 for p in posts if p.get("status") == "CREATED")
    failed = [p for p in posts if str(p.get("status", "")).startswith("FAILED")]
    summary = {**report.get("summary", {}), "tasks_created": created, "failed_batches": len(failed),
               "post_results": [{k: p.get(k) for k in ("batch", "count", "status", "created", "error")} for p in posts]}
    reporter.steps["TASKS"].update(status="FAILED" if failed else "OK", summary=summary)
    reporter.patch(tasks_created=created, failed_batches=len(failed), steps=reporter.steps)
    if failed:
        raise PipelineError("POST /tasks ไม่ผ่าน " + ", ".join(f"{p['batch']} ({p['status']})" for p in failed)
                            + " decision ของ batch นี้ยังเป็น PENDING")
    if report.get("summary", {}).get("decisions", 0) == 0:
        return {**summary, "done": True, "message": "ไม่มี decision ที่รอสร้าง task"}
    return summary


def run_pipeline(stop_after: str = "TASKS", pipeline_run_id=None) -> dict:
    if stop_after not in STEPS:
        raise ValueError(f"stop_after must be one of {STEPS}")
    reporter = Reporter(pipeline_run_id)
    work_dir = Path(os.getenv("WORK_DIR") or AI_DIR / "pipeline" / "output") \
        / (pipeline_run_id or datetime.now(BKK).strftime("%Y%m%d_%H%M%S"))
    work_dir.mkdir(parents=True, exist_ok=True)
    result = {"pipeline_run_id": pipeline_run_id, "stop_after": stop_after, "work_dir": str(work_dir)}

    try:
        reporter.patch(status="RUNNING", current_step="SCAN")
        scan = step_scan(work_dir, reporter)
        result["scan"] = scan
        message = scan.get("message")
        if not scan.get("done") and stop_after != "SCAN":
            opt = step_optimize(scan["run_id"], work_dir, reporter)
            result["optimize"] = opt
            message = opt.get("message")
            if not opt.get("done") and stop_after == "TASKS":
                tasks = step_tasks(scan["run_id"], work_dir, reporter)
                result["tasks"] = tasks
                message = tasks.get("message") or (f"สร้าง task {tasks['tasks_created']} งาน "
                                                   f"จาก {opt['decisions_created']} decision")
        message = message or f"หยุดหลังขั้น {stop_after} ตามที่สั่ง"
        reporter.patch(status="SUCCEEDED", message=message, steps=reporter.steps)
        result.update(status="SUCCEEDED", message=message)
    except Exception as e:
        error = str(e) if isinstance(e, PipelineError) else f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}"
        print(f"[pipeline] FAILED: {error}", file=sys.stderr)
        result.update(status="FAILED", error=error)
        try:
            reporter.patch(status="FAILED", error=error, steps=reporter.steps)
        except PipelineError as patch_error:
            print(f"[pipeline] {patch_error}", file=sys.stderr)
    return result


def lambda_handler(event, context):
    """event จาก server: {"pipeline_run_id": "...", "stop_after": "TASKS"}"""
    event = event or {}
    result = run_pipeline(event.get("stop_after", "TASKS"), event.get("pipeline_run_id"))
    print(json.dumps(result, ensure_ascii=False, default=str))
    return result


def main():
    ap = argparse.ArgumentParser(description="No-Waste-Bro AI pipeline (debug ในเครื่อง)")
    ap.add_argument("--stop-after", choices=STEPS, default="TASKS")
    ap.add_argument("--pipeline-run-id", default=None,
                    help="รอบที่สร้างจาก POST /ai/pipeline-runs (ไม่ใส่ = ไม่อัปเดตสถานะใน server)")
    args = ap.parse_args()
    result = run_pipeline(args.stop_after, args.pipeline_run_id)
    print("\n" + json.dumps({k: v for k, v in result.items()}, ensure_ascii=False, indent=1, default=str))
    sys.exit(0 if result["status"] == "SUCCEEDED" else 1)


if __name__ == "__main__":
    main()
