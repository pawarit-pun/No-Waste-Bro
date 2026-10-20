"""Offline tests (no AWS, no network). Run: python tests/test_agent.py"""

import copy
import json
import os
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent import batch_key, clean_detail, run, write_steps  # noqa: E402
from api_client import ApiError  # noqa: E402
from config import TH_TZ, settings  # noqa: E402
from facts import build_facts, parse_dt  # noqa: E402
from knowledge_base import NullRetriever  # noqa: E402
from llm import build_user_prompt, feedback_prompt, parse_json  # noqa: E402
from mock_data import get_mock_decisions  # noqa: E402
from models import OptimizationDecision, TaskCreate  # noqa: E402
from steps import compute_priority, fallback_reasoning, required_steps, staff_instructions  # noqa: E402
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

# Real Nova Lite answer from the Playground, with known mistakes
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
    out["instruction_steps"][1]["detail"] = "ตรวจความพร้อมของครัว KITCHEN_DELI อุปกรณ์ และพนักงาน ถ้าไม่พร้อมให้แจ้งหัวหน้า"
    out["instruction_steps"][3]["detail"] = "ผลิตตามสูตร RCP-001 สเต็กเนื้อสันนอก พร้อมสลัด จำนวน 1 batch"
    out["instruction_steps"][4]["detail"] = ("บันทึกวัตถุดิบที่ใช้ 4 ชิ้น และผลผลิตที่ได้จริง (คาดว่าได้ 10 ชิ้น) "
                                             "หากพบสินค้าเสียหายหรือจำนวนไม่ตรง ให้หยุดและแจ้งหัวหน้า")
    return out


def fallback_answer(facts, specs) -> dict:
    return {"ai_reasoning": fallback_reasoning(facts),
            "instruction_steps": [{"title": s.title, "detail": s.fallback} for s in specs]}


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
    assert "ขั้นที่ 2 detail ต้องมีเงื่อนไข" in joined, errors  # dropped "if not ready, tell supervisor"
    assert "ขั้นที่ 5 มีคำ FACTS" in joined, errors  # "...ไม่ตรงกับ FACTS..."
    assert len(errors) == 4, errors  # the rest passes, incl. "16 ตุลาคม 2026" in ai_reasoning


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


def test_alternatives_compared_in_code():
    assert "→ ทางที่เลือกดีกว่า 868.5 บาท" in build_facts(BY_ID["1"]).alternatives_prompt()
    assert "→ ทางที่เลือกแย่กว่า 23.4 บาท (ไม่รวมค่าขนย้าย)" in build_facts(BY_ID["4"]).alternatives_prompt()


# Alternatives in the shape the real Optimizer sends (LOT-000001, run f84a00f5)
REAL_ALTERNATIVES = [
    {"note": "เรียก partner มารับเฉพาะส่วนนี้ 1 เที่ยว", "partner_id": "P-ADG-01", "action_type": "DISCARD",
     "disposal_method": "ANAEROBIC_DIGESTION", "expected_profit_impact": -7805.19},
    {"option": "MARKDOWN:ALL", "rejected_because": ["K0_EXPIRED"]},
    {"option": "DONATION:P-DON-01", "rejected_because": ["P4_MIN_DAYS -3d at pickup < 2d", "P5_EXPIRED_FOR_HUMAN_USE"]},
    {"option": "KITCHEN:RCP-006", "rejected_because": ["U3_KITCHEN_HOURS 2026-10-19 0.00h < 0.83h", "X9_SOMETHING_NEW"]},
    {"note": "ค่าอ้างอิงเท่านั้น: ต้นทุนสินค้าที่เสียไปถ้าทิ้งหมด", "feasible": False, "action_type": "DISCARD",
     "disposal_method": "COST_WRITE_OFF_REFERENCE", "expected_profit_impact": -5842.5},
]


def real_alternatives_decision() -> OptimizationDecision:
    d = BY_ID["4"].model_copy(deep=True)
    d.expected_profit_impact = -6295.68
    d.alternatives = REAL_ALTERNATIVES
    return d


def test_alternatives_split_feasible_rejected_reference():
    f = build_facts(real_alternatives_decision())
    assert f.alternatives == [
        "- ทางเลือกอื่น: ส่งย่อยแบบไม่ใช้ออกซิเจน, ผลกระทบกำไร -7805.19 บาท → ทางที่เลือกดีกว่า 1509.51 บาท"
        " (เรียก partner มารับเฉพาะส่วนนี้ 1 เที่ยว)"]
    assert f.rejected == [
        "- ตัดออก: ลดราคา เพราะหมดอายุแล้ว",
        "- ตัดออก: บริจาค P-DON-01 เพราะอายุคงเหลือไม่ถึงเกณฑ์ของผู้รับ, หมดอายุสำหรับคนแล้ว",
        "- ตัดออก: ส่งเข้าครัว RCP-006 เพราะชั่วโมงครัวไม่พอ, SOMETHING_NEW",  # unknown code kept as is
    ]
    assert f.references == [
        "- ค่าอ้างอิง (ไม่ใช่ทางเลือก ห้ามนำไปเปรียบเทียบ): ต้นทุนสินค้าที่เสียไปถ้าทิ้งหมด -5842.5 บาท"]


def test_reference_value_never_triggers_escalation():
    # -5842.5 is "better" than the chosen -6295.68, but it is not an option staff could take
    f = build_facts(real_alternatives_decision())
    assert not f.chosen_is_worse and f.comparison_diffs == {1509.51}
    specs = required_steps(f)
    assert validate_output(fallback_answer(f, specs), f, specs) == []


def test_negative_days_written_as_expired():
    f = build_facts(real_alternatives_decision())
    for days, text in ((-2, "หมดอายุไปแล้ว 2 วัน"), (0, "หมดอายุวันนี้"), (3, "เหลืออายุ 3 วัน")):
        f.days_to_expiry = days
        assert f"({text})" in f.to_prompt() and text in fallback_reasoning(f)


def test_negative_numbers_are_checked_but_codes_are_not():
    from validate import standalone_numbers
    assert standalone_numbers("ผลกระทบ -5842.5 บาท สูตร RCP-001 วันที่ 2026-10-16 lot LOT-000009") == {5842.5}
    out = fixed_case2()
    out["ai_reasoning"] = "ทางนี้มีผลกระทบกำไร -999 บาท"  # invented negative number
    assert any("999" in e for e in validate_output(out, F, SPECS))


def test_validator_flags_reference_value():
    # Real Nova output: compared the chosen action with the reference value
    f = build_facts(real_alternatives_decision())
    specs = required_steps(f)
    out = fallback_answer(f, specs)
    out["ai_reasoning"] = "ทางที่เลือกดีกว่าต้นทุนสินค้าที่เสียไปถ้าทิ้งหมด -5842.5 บาท"
    assert any("ค่าอ้างอิง" in e for e in validate_output(out, f, specs))


def test_validator_requires_safety_gates():
    for key, step_index in (("2", 1), ("3", 2), ("4", 1)):  # kitchen readiness, donate pickup, discard approval
        f = build_facts(BY_ID[key])
        specs = required_steps(f)
        out = fallback_answer(f, specs)
        out["instruction_steps"][step_index]["detail"] = specs[step_index].fallback.split(" ถ้า")[0]
        errors = validate_output(out, f, specs)
        assert any("ต้องมีเงื่อนไข" in e for e in errors), (key, errors)


def test_validator_accepts_same_meaning_wording():
    f = build_facts(BY_ID["2"])  # kitchen, no location
    specs = required_steps(f)
    out = fallback_answer(f, specs)
    # Real Nova / Qwen wording that was rejected before
    out["instruction_steps"][0]["detail"] = "ยืนยันว่า lot ของสินค้าคือ LOT-900002 และตรวจสอบตำแหน่งกับระบบ จำนวนคงเหลือใน lot คือ 8 ชิ้น"
    out["instruction_steps"][1]["detail"] = "ตรวจสอบความพร้อมของ DEPT-BAKERY อุปกรณ์ และพนักงาน หากไม่พร้อมให้แจ้งหัวหน้า"
    assert validate_output(out, f, specs) == []


def test_validator_flags_label_lists():
    out = fixed_case2()
    out["instruction_steps"][2]["detail"] = "จำนวน 4"  # real Nova output after the first prompt change
    out["instruction_steps"][3]["detail"] = "รหัสสูตร RCP-001, จำนวน batch 1"
    joined = "\n".join(validate_output(out, F, SPECS))
    assert "ขั้นที่ 3 detail ต้องเป็นประโยคคำสั่ง" in joined and "ขั้นที่ 4 detail ต้องเป็นประโยคคำสั่ง" in joined, joined


def test_validator_requires_review_when_chosen_is_worse():
    f = build_facts(BY_ID["4"])
    specs = required_steps(f)
    out = fallback_answer(f, specs)
    out["ai_reasoning"] = "เลือกทิ้งเพราะมีการยืนยันจากผู้มีอำนาจ"  # real Nova output: invented reason
    assert any("ให้ผู้จัดการตรวจสอบก่อนอนุมัติ" in e for e in validate_output(out, f, specs))
    assert not build_facts(BY_ID["1"]).chosen_is_worse


def test_validator_flags_condition_first_and_needless_review():
    f = build_facts(BY_ID["4"])
    specs = required_steps(f)
    out = fallback_answer(f, specs)
    out["instruction_steps"][1]["detail"] = "ถ้ายังไม่ได้รับอนุมัติห้ามดำเนินการต่อ"  # real Nova output
    assert any("ห้ามขึ้นต้นด้วย" in e for e in validate_output(out, f, specs))

    f = build_facts(BY_ID["1"])  # chosen action is the best one
    specs = required_steps(f)
    out = fallback_answer(f, specs)
    out["ai_reasoning"] += " ให้ผู้จัดการตรวจสอบก่อนอนุมัติ"
    assert any("ห้ามมี" in e for e in validate_output(out, f, specs))


def test_feedback_includes_example_for_failed_steps():
    errors = validate_output(NOVA_CASE2, F, SPECS)
    text = feedback_prompt(errors, SPECS)
    assert f"- ขั้นที่ 4 ({SPECS[3].title}): {SPECS[3].fallback}" in text
    assert "ขั้นที่ 1 (" not in text  # steps that passed get no example


def test_clean_detail_strips_quotes():
    assert clean_detail("ติดป้ายราคาใหม่เป็น '33.25' บาท  สำหรับ \"30\" ชิ้น") == "ติดป้ายราคาใหม่เป็น 33.25 บาท สำหรับ 30 ชิ้น"


def test_validator_checks_comparison_in_reasoning():
    # Real Nova outputs
    f = build_facts(BY_ID["2"])  # chosen is 224 baht better
    specs = required_steps(f)
    out = fallback_answer(f, specs)
    out["ai_reasoning"] = "เลือกทางนี้เพราะผลกระทบกำไรที่คาดจากทางนี้ดีกว่าทางเลือกอื่น 96 บาท"
    assert any("ส่วนต่างที่ถูกคือ 224" in e for e in validate_output(out, f, specs))
    out["ai_reasoning"] = "เลือกทางนี้เพราะดีกว่าทางลดราคา 40% อยู่ 224 บาท"
    assert validate_output(out, f, specs) == []

    f = build_facts(BY_ID["4"])  # chosen is 23.4 baht worse
    specs = required_steps(f)
    out = fallback_answer(f, specs)
    out["ai_reasoning"] = "ทางที่เลือกมีผลกระทบกำไร -290.4 บาท แต่ดีกว่าทิ้งเองที่ -267 บาท ให้ผู้จัดการตรวจสอบก่อนอนุมัติ"
    assert any("แย่กว่า" in e for e in validate_output(out, f, specs))


def test_validator_flags_prompt_terms():
    out = fixed_case2()
    out["ai_reasoning"] = "เลือกทางนี้ตามตัวเลขใน FACTS และ ALTERNATIVES"
    assert any("FACTS / ALTERNATIVES" in e for e in validate_output(out, F, SPECS))


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
    assert "ไม่พบ SOP" in prompt and "หมดอายุ: ไม่มีข้อมูล, " in prompt
    assert "4. ผลิตตามสูตรที่อนุมัติ — ประโยคต้องมี: \"RCP-001\" (รหัสสูตร), \"1\" (จำนวน batch)" in prompt


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

ALL_LOTS = sorted(d.lot_id for d in DECISIONS)  # LOT-900001 .. LOT-900005
KITCHEN_LOT = BY_ID["2"].lot_id


class FakeSource:
    """Fake API. By default rejects the kitchen batch with 409 and PATCHes every lot it is given."""

    def __init__(self, decisions=None, kitchen_full=True, patch=None):
        self.decisions = decisions or DECISIONS
        self.kitchen_full = kitchen_full
        self.patch = patch  # None = success, dict = response, Exception = raised
        self.posted: list[list[TaskCreate]] = []
        self.patched: list[tuple[list[str], str]] = []

    def pending_decisions(self, run_id=None):
        return "run-1", self.decisions

    def post_tasks(self, tasks):
        if self.kitchen_full and any(t.decision_id == BY_ID["2"].decision_id for t in tasks):
            raise ApiError(409, "Kitchen 'DEPT-BAKERY' does not have 0.75 hours available")
        self.posted.append(tasks)
        return {"created": len(tasks), "tasks": [{"assigned_staff_id": "STF-001"}] * len(tasks)}

    def set_lots_ai_status(self, lot_ids, ai_status):
        self.patched.append((lot_ids, ai_status))
        if isinstance(self.patch, Exception):
            raise self.patch
        if self.patch is not None:
            return self.patch
        return {"message": "ok", "updated": [{"lot_id": i, "ai_status": ai_status} for i in lot_ids],
                "not_found": []}


def extra_decision(n: int, lot_id: str) -> OptimizationDecision:
    """A second MARKDOWN decision for an existing lot (goes in the GENERAL batch)."""
    d = BY_ID["1"].model_copy(deep=True)
    d.decision_id = f"00000000-0000-0000-0000-{n:012d}"
    d.lot_id = lot_id
    d.lot = {**d.lot, "lot_id": lot_id}
    return d


def test_batch_key_splits_kitchen_by_department_and_day():
    assert batch_key(build_facts(BY_ID["2"])) == "KITCHEN:DEPT-BAKERY@2026-10-16"
    assert batch_key(build_facts(BY_ID["1"])) == "GENERAL"


def test_run_posts_batches_and_writes_report():
    source = FakeSource()
    report = run(source, NullRetriever(), None, dry_run=False)
    results = {r["batch"]: r for r in report["post_results"]}
    assert results["GENERAL"]["status"] == "CREATED" and results["GENERAL"]["count"] == 4
    assert results["KITCHEN:DEPT-BAKERY@2026-10-16"]["status"] == "FAILED_409"
    assert report["summary"] == {"decisions": 5, "tasks": 5, "llm_ok": 0, "template_fallback": 5,
                                 "llm_calls": 0, "lots_checked": 4, "lots_pending": 1}
    assert os.path.exists(report["report_path"])


# ---------- Step 8: lots -> CHECKED ----------

def test_lots_all_batches_ok_one_patch_unique_lots():
    decisions = [*DECISIONS, extra_decision(6, BY_ID["1"].lot_id)]  # LOT-900001 has 2 decisions
    source = FakeSource(decisions, kitchen_full=False)
    lots = run(source, NullRetriever(), None, dry_run=False)["lot_status"]
    assert source.patched == [(ALL_LOTS, "CHECKED")]  # one call, each lot once, sorted
    assert lots["status"] == "UPDATED" and lots["updated"] == ALL_LOTS and lots["pending_lots"] == []


def test_lots_failed_kitchen_batch_stays_processing():
    # The kitchen lot also has a MARKDOWN decision that succeeds: still not CHECKED
    decisions = [*DECISIONS, extra_decision(6, KITCHEN_LOT)]
    source = FakeSource(decisions, kitchen_full=True)
    lots = run(source, NullRetriever(), None, dry_run=False)["lot_status"]
    assert KITCHEN_LOT not in source.patched[0][0]
    assert source.patched[0][0] == [lot for lot in ALL_LOTS if lot != KITCHEN_LOT]
    assert lots["pending_lots"] == [{"lot_id": KITCHEN_LOT, "reasons": ["FAILED_409"]}]


def test_lots_dry_run_does_not_patch():
    source = FakeSource(kitchen_full=False)
    lots = run(source, NullRetriever(), None, dry_run=True)["lot_status"]
    assert source.patched == []
    assert lots["status"] == "DRY_RUN" and lots["to_check"] == ALL_LOTS  # preview of what would be CHECKED


def test_lots_limit_leaves_unprocessed_lots_processing():
    source = FakeSource(kitchen_full=False)
    lots = run(source, NullRetriever(), None, dry_run=False, limit=2)["lot_status"]
    assert source.patched[0][0] == ALL_LOTS[:2]
    assert {p["lot_id"] for p in lots["pending_lots"]} == set(ALL_LOTS[2:])
    assert all(p["reasons"] == ["NOT_PROCESSED"] for p in lots["pending_lots"])


def test_lots_not_found_recorded():
    response = {"message": "ok", "updated": [{"lot_id": lot, "ai_status": "CHECKED"} for lot in ALL_LOTS[1:]],
                "not_found": [ALL_LOTS[0]]}
    report = run(FakeSource(kitchen_full=False, patch=response), NullRetriever(), None, dry_run=False)
    assert report["lot_status"]["not_found"] == [ALL_LOTS[0]]
    assert report["summary"]["lots_checked"] == 4


def test_lots_patch_error_does_not_fail_run():
    for error, status in ((ApiError(404, "None of the lot_ids were found"), "FAILED_404"),
                          (RuntimeError("connection reset"), "FAILED")):
        source = FakeSource(kitchen_full=False, patch=error)
        report = run(source, NullRetriever(), None, dry_run=False)
        lots = report["lot_status"]
        assert lots["status"] == status and lots["error"], lots
        assert {r["status"] for r in report["post_results"]} == {"CREATED"}  # tasks still created
        assert os.path.exists(report["report_path"])


def test_lots_no_patch_when_nothing_succeeded():
    source = FakeSource([BY_ID["2"]], kitchen_full=True)  # only the kitchen decision, and it fails
    lots = run(source, NullRetriever(), None, dry_run=False)["lot_status"]
    assert source.patched == [] and lots["status"] == "SKIPPED"


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
