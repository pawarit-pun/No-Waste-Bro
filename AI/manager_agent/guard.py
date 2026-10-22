"""ตรวจคำตอบก่อนส่งให้ผู้จัดการ: ตัวเลข วันที่ เวลา และรหัส lot ต้องมาจากผลของ tool (หรือคำถาม) เท่านั้น

กติกา
  - ตัวเลขที่มี 2 หลักขึ้นไป หรือมีทศนิยม ต้องตรงกับตัวเลขในหลักฐาน หลังปัดเท่าจำนวนทศนิยมที่ตอบ (ไม่สนเครื่องหมายลบ:
    "ขาดทุน 5,116 บาท" ตรงกับ -5116.02) ตัวเลขหลักเดียวไม่ตรวจ (ลำดับข้อ จำนวนเล็กๆ)
  - วันที่ YYYY-MM-DD / เวลา HH:MM ต้องปรากฏในหลักฐาน
  - LOT-xxxxxx ต้องปรากฏในหลักฐาน
"""
from __future__ import annotations

import re

THINKING = re.compile(r"<thinking>.*?(</thinking>|$)", re.S | re.I)
LOT = re.compile(r"LOT-\d+", re.I)
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# 14:30 หรือ 14.30 น. (แบบจุดต้องมี "น." ไม่งั้นชนกับราคา เช่น 143.20)
TIME = re.compile(r"(?<![\d:.])([01]?\d|2[0-3])(?::([0-5]\d)(?![\d:])|\.([0-5]\d)\s*น\.)")
NUM = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?")


def strip_thinking(text: str) -> str:
    """Nova Lite ใส่ <thinking>...</thinking> ก่อนคำตอบ (check_models.py 22 ต.ค.)"""
    return THINKING.sub("", text or "").strip()


def _numbers(text: str) -> list[str]:
    return [m.group(0) for m in NUM.finditer(text)]


def evidence_numbers(evidence: str) -> set[float]:
    out = set()
    for tok in _numbers(LOT.sub(" ", evidence)):
        try:
            out.add(abs(float(tok.replace(",", ""))))
        except ValueError:
            pass
    return out


def check(answer: str, evidence: str) -> list[str]:
    problems: list[str] = []
    ev_upper = evidence.upper()
    for lot in sorted({m.group(0).upper() for m in LOT.finditer(answer)}):
        if lot not in ev_upper:
            problems.append(f"รหัส {lot} ไม่มีในข้อมูล")
    rest = LOT.sub(" ", answer)
    for d in sorted(set(DATE.findall(rest))):
        if d not in evidence:
            problems.append(f"วันที่ {d} ไม่มีในข้อมูล")
    rest = DATE.sub(" ", rest)
    for m in TIME.finditer(rest):
        hhmm = f"{int(m.group(1)):02d}:{m.group(2) or m.group(3)}"
        if hhmm not in evidence:
            problems.append(f"เวลา {hhmm} ไม่มีในข้อมูล")
    rest = TIME.sub(" ", rest)

    allowed = evidence_numbers(evidence)
    for tok in _numbers(rest):
        plain = tok.replace(",", "")
        decimals = len(plain.split(".")[1]) if "." in plain else 0
        if decimals == 0 and len(plain) < 2:
            continue
        value = float(plain)
        if any(abs(round(a, decimals) - value) < 1e-9 for a in allowed):
            continue
        problems.append(f"ตัวเลข {tok} ไม่มีในข้อมูล (ห้ามคำนวณหรือแต่งตัวเลขเอง)")
    return problems
