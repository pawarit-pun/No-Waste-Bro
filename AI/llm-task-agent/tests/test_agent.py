"""Offline tests for the Task Agent (no AWS, no network).

Run:  python tests/test_agent.py      (or: python -m pytest tests -q, if pytest is installed)
"""

import copy
import json
import os
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent import batch_key, run, write_steps  # noqa: E402
from api_client import ApiError  # noqa: E402
from config import TH_TZ, settings  # noqa: E402
from facts import build_facts, parse_dt  # noqa: E402
from knowledge_base import NullRetriever  # noqa: E402
from llm import build_user_prompt, parse_json  # noqa: E402
from mock_data import get_mock_decisions  # noqa: E402
from models import OptimizationDecision, TaskCreate  # noqa: E402
from steps import compute_priority, required_steps, staff_instructions  # noqa: E402
from validate import validate_output  # noqa: E402

PRIMARY, FALLBACK = settings.PRIMARY_MODEL, settings.FALLBACK_MODEL
NOW = datetime(2026, 10, 16, 8, 0, tzinfo=TH_TZ)
settings.AGENT_NOW = NOW.isoformat()
settings.OUTPUT_DIR = tempfile.mkdtemp(prefix="task_agent_test_")

DECISIONS = get_mock_decisions()
BY_ID = {d.decision_id[-1]: d for d in DECISIONS}  # "1".."5", see mock_data.py

# Kitchen case from the Playground test: lot with no shelf location
KITCHEN = OptimizationDecision.model_validate({
    "decision_id": "k", "action_type": "KITCHEN_REPURPOSE", "lot_id": "LOT-000005",
    "action_quantity": 4, "target_recipe_id": "RCP-001", "batch_count": 1,
    "due_by": "2026-10-16T17:00:00+07:00",
    "lot": {"lot_id": "LOT-000005", "current_quantity": 4, "location_aisle": None, "location_shelf": None},
    "product": {"name": "เนื้อวัวสันนอก สเต็ก 500g", "category": "MEAT", "unit_of_measure": "PIECE"},
    "recipe": {"recipe_id": "RCP-001", "name": "สเต็กเนื้อสันนอก พร้อมสลัด",
               "department_id": "KITCHEN_DELI", "output_quantity": 10},
})
F = build_facts(KITCHEN)
SPECS = required_steps(F)

# Real Nova Lite answer (Playground, with REQUIRED_STEPS) that still had 2 mistakes
NOVA_CASE2 = {
    "ai_reasoning": "ตาม REPURPOSING_SOP เราต้องยืนยันสินค้า lot จำนวน และตำแหน่ง ตรวจความพร้อมของครัว "
                    "โดยต้องเสร็จภายในวันที่ 16 ตุลาคม 2026 เวลา 17:00 น.",
    "instruction_steps": [
        {"title": "ยืนยันสินค้า lot จำนวน และตำแหน่ง",
         "detail": "ยืนยันเนื้อวัวสันนอก สเต็ก 500g (MEAT) จำนวน 4 ชิ้น จาก lot LOT-000005 ที่ตำแหน่งตรวจสอบกับระบบ"},
        {"title": "ตรวจความพร้อมของครัว อุปกรณ์ และพนักงาน",
         "detail": "ตรวจความพร้อมของครัว KITCHEN_DELI อุปกรณ์ และพนักงาน"},
        {"title": "นำวัตถุดิบส่งเข้าครัว",
         "detail": "นำเนื้อวัวสันนอก สเต็ก 500g (MEAT) จำนวน 4 ชิ้น ไปส่งครัว KITCHEN_DELI"},
        {"title": "ผลิตตามสูตรที่อนุมัติ",
         "detail": "ผลิตตามสูตร RCP-001 สเต็กเนื้อสันนอก พร้อมสลัด"},
        {"title": "บันทึกวัตถุดิบที่ใช้และผลผลิตจริง และเงื่อนไขหยุด",
         "detail": "บันทึกวัตถุดิบเนื้อวัวสันนอก สเต็ก 500g (MEAT) จำนวน 4 ชิ้น และผลผลิตจริง 10 ชิ้น "
                   "หากพบสินค้าเสียหาย จำนวนไม่ตรง หรือข้อมูลไม่ตรงกับ FACTS ให้หยุดและแจ้งหัวหน้า"},
    ],
}


def fixed_case2() -> dict:
    out = copy.deepcopy(NOVA_CASE2)
    out["instruction_steps"][3]["detail"] = "ผลิตตามสูตร RCP-001 สเต็กเนื้อสันนอก พร้อมสลัด จำนวน 1 batch"
    out["instruction_steps"][4]["detail"] = ("บันทึกวัตถุดิบที่ใช้ 4 ชิ้น และผลผลิตที่ได้จริง (คาดว่าได้ 10 ชิ้น) "
                                             "หากพบสินค้าเสียหายหรือจำนวนไม่ตรง ให้หยุดและแจ้งหัวหน้า")
    return out


def fallback_answer(facts, specs) -> dict:
    return {"ai_reasoning": "ok", "instruction_steps": [{"title": s.title, "detail": s.fallback} for s in specs]}


# ---------- Facts, steps, priority ----------

def test_mock_decisions_parse_null_context():
    d = BY_ID["5"]
    assert d.assessment == {} and d.recipe == {} and d.partner == {} and d.alternatives == []


def test_required_steps_per_action():
    titles = {k: [s.title for s in required_steps(build_facts(d))] for k, d in BY_ID.items()}
    assert titles["1"][3] == "เปลี่ยนราคาใน POS"
    assert titles["2"][1] == "ตรวจความพร้อมของครัว อุปกรณ์ และพนักงาน"
    assert titles["3"][2] == "ยืนยันนัดรับกับผู้รับบริจาค"
    assert titles["4"][1] == "ขออนุมัติหัวหน้างานก่อนทิ้ง" and titles["4"][2] == "แยกสินค้าและเตรียมรอรถรับ"
    assert titles["5"][2] == "แยกสินค้าออกจากชั้น" and titles["5"][3] == "กำจัดตามเส้นทางที่ร้านอนุมัติ"
    assert all(len(t) == 5 for t in titles.values())


def test_missing_location_says_check_system():
    f = build_facts(BY_ID["2"])
    assert "ตรวจสอบกับระบบ" in required_steps(f)[0].fallback
    assert "(ตำแหน่ง: ตรวจสอบกับระบบ)" in staff_instructions(f)
    assert "ตำแหน่ง: ไม่มีข้อมูล" in f.to_prompt()


def test_priority_rules():
    f = build_facts(BY_ID["1"])
    cases = [  # (due_by, days_to_expiry, action, expected)
        ("2026-10-16T11:00:00+07:00", 1, "MARKDOWN", 1),  # due in 3 h
        ("2026-10-16T18:00:00+07:00", 1, "MARKDOWN", 2),  # due in 10 h
        ("2026-10-17T20:00:00+07:00", 1, "MARKDOWN", 3),
        ("2026-10-17T20:00:00+07:00", 1, "DONATE", 2),
        (None, 2, "MARKDOWN", 4),
        (None, 0, "MARKDOWN", 1),  # expired / expires today
        (None, 5, "MARKDOWN", 5),
    ]
    for due, days, action, expected in cases:
        f.due_dt, f.days_to_expiry, f.action = parse_dt(due), days, action
        assert compute_priority(f, NOW) == expected, (due, days, action)


# ---------- Validator ----------

def test_validator_catches_real_mistakes():
    errors = validate_output(NOVA_CASE2, F, SPECS)
    joined = "\n".join(errors)
    assert "ขั้นที่ 4 detail ต้องมีจำนวน batch 1" in joined, errors  # RCP-001 must not count as batch 1
    assert "ขั้นที่ 5 พูดถึงผลผลิต 10 ชิ้น" in joined, errors
    assert len(errors) == 2, errors  # the rest passes, incl. "16 ตุลาคม 2026" in ai_reasoning


def test_validator_accepts_fixed_output():
    assert validate_output(fixed_case2(), F, SPECS) == []


def test_validator_flags_buddhist_year_and_sop_names():
    out = fixed_case2()
    out["instruction_steps"][1]["detail"] = "ตรวจครัว KITCHEN_DELI ตาม KITCHEN_CAPACITY_SOP ภายใน 16 ต.ค. 2569"
    joined = "\n".join(validate_output(out, F, SPECS))
    assert "ชื่อเอกสาร SOP" in joined and "พ.ศ." in joined, joined


def test_validator_flags_wrong_title_and_invented_number():
    f = build_facts(BY_ID["5"])
    specs = required_steps(f)
    out = fallback_answer(f, specs)
    out["ai_reasoning"] = "ต้องทิ้ง 3 ชิ้น ใช้เวลา 15 นาที"
    out["instruction_steps"][4]["title"] = "บันทึกผลหลังส่งมอบจริง และเงื่อนไขหยุด"
    joined = "\n".join(validate_output(out, f, specs))
    assert "ขั้นที่ 5 title" in joined and "15" in joined, joined


def test_validator_flags_detail_over_300():
    out = fixed_case2()
    out["instruction_steps"][0]["detail"] += " ก" * 200
    assert any("ยาวเกิน 300" in e for e in validate_output(out, F, SPECS))


def test_fallback_text_always_valid():
    for d in [*DECISIONS, KITCHEN]:
        f = build_facts(d)
        specs = required_steps(f)
        errors = validate_output(fallback_answer(f, specs), f, specs)
        assert errors == [], (f.lot_id, f.action, errors)


# ---------- LLM helpers ----------

def test_parse_json_strips_fences_and_think():
    assert parse_json("<think>คิดก่อน</think>\n```json\n{\"a\": 1}\n```") == {"a": 1}


def test_prompt_without_kb():
    prompt = build_user_prompt(F, SPECS, NullRetriever().retrieve(F.action, F.category))
    assert "ไม่พบ SOP" in prompt and "จำนวน batch 1" in prompt and "หมดอายุ: ไม่มีข้อมูล, " in prompt


class FakeLLM:
    """Returns answers in order; an Exception is raised like a Bedrock error."""

    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def chat(self, model, messages):
        self.calls.append((model, len(messages)))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        text = r if isinstance(r, str) else "```json\n" + json.dumps(r, ensure_ascii=False) + "\n```"
        return {"text": text, "usage": {}, "latency_ms": 1}


def test_retry_first_try_ok():
    r = write_steps(F, SPECS, [], FakeLLM([fixed_case2()]))
    assert r["model_used"] == PRIMARY and len(r["attempts"]) == 1


def test_retry_with_feedback_then_ok():
    llm = FakeLLM([NOVA_CASE2, fixed_case2()])
    r = write_steps(F, SPECS, [], llm)
    assert r["model_used"] == PRIMARY and len(r["attempts"]) == 2
    assert llm.calls[1][1] == 3  # prompt + previous answer + feedback


def test_retry_fallback_model_ok():
    llm = FakeLLM([NOVA_CASE2, NOVA_CASE2, fixed_case2()])
    r = write_steps(F, SPECS, [], llm)
    assert r["model_used"] == FALLBACK and llm.calls[2] == (FALLBACK, 1)


def test_retry_all_fail_then_template():
    llm = FakeLLM([RuntimeError("AccessDenied"), NOVA_CASE2, "not json"])
    r = write_steps(F, SPECS, [], llm)
    assert [c[0] for c in llm.calls] == [PRIMARY, PRIMARY, FALLBACK]
    assert llm.calls[1][1] == 1  # first call raised, so the retry is a fresh prompt
    assert r["model_used"] == "TEMPLATE"
    assert [s.title for s in r["instruction_steps"]] == [s.title for s in SPECS]


# ---------- Run: batching, POST, report ----------

class FakeSource:
    """Rejects the kitchen batch with 409, accepts everything else."""

    def __init__(self):
        self.posted: list[list[TaskCreate]] = []

    def pending_decisions(self, run_id=None):
        return "run-1", DECISIONS

    def post_tasks(self, tasks):
        if any(t.decision_id == BY_ID["2"].decision_id for t in tasks):
            raise ApiError(409, "Kitchen 'DEPT-BAKERY' does not have 0.75 hours available")
        self.posted.append(tasks)
        return {"created": len(tasks), "tasks": [{"assigned_staff_id": "STF-001"}] * len(tasks)}


def test_batch_key_splits_kitchen_by_department_and_day():
    assert batch_key(build_facts(BY_ID["2"])) == "KITCHEN:DEPT-BAKERY@2026-10-16"
    assert batch_key(build_facts(BY_ID["1"])) == "GENERAL"


def test_run_posts_batches_and_writes_report():
    source = FakeSource()
    report = run(source, NullRetriever(), None, dry_run=False)
    results = {r["batch"]: r for r in report["post_results"]}
    assert results["GENERAL"]["status"] == "CREATED" and results["GENERAL"]["count"] == 4
    assert results["KITCHEN:DEPT-BAKERY@2026-10-16"]["status"] == "FAILED_409"
    assert report["summary"] == {"decisions": 5, "tasks": 5, "llm_ok": 0,
                                 "template_fallback": 5, "llm_calls": 0}
    assert os.path.exists(report["report_path"])


def test_run_dry_run_posts_nothing():
    source = FakeSource()
    report = run(source, NullRetriever(), None, dry_run=True)
    assert source.posted == [] and {r["status"] for r in report["post_results"]} == {"DRY_RUN"}


def test_run_continues_when_kb_fails():
    class BrokenKB:
        def retrieve(self, action, category=None):
            raise RuntimeError("KB down")

    report = run(FakeSource(), BrokenKB(), None, dry_run=True, limit=1)
    assert report["summary"]["tasks"] == 1 and "KB down" in report["audit"][0]["sop_error"]


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_")]
    for name, fn in tests:
        fn()
        print("PASS", name)
    print(f"{len(tests)} tests passed")
