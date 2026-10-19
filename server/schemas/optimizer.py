"""Response ของ POST /api/v1/ai/optimize และ GET /api/v1/ai/optimize-runs (ไฟล์ใหม่)"""
from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OptimizeRunResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: Optional[UUID] = Field(None, description="รอบสแกนที่ใช้ (null = ยังไม่เคยสแกน)")
    reference_date: date = Field(..., description="วันที่ระบบถือว่าเป็นวันนี้ (DEMO_DATE หรือวันนี้ตามเวลาไทย)")
    simulated_now: datetime = Field(..., description="วันเวลาที่ Optimizer ใช้คิด = reference_date + เวลาไทยตอนที่เรียก")
    dry_run: bool = Field(..., description="true = คำนวณอย่างเดียว ไม่เขียน DB")
    summary: dict[str, Any] = Field(..., description="สัดส่วนการจัดการ (% ตามจำนวนหน่วย), kg, รายได้, ค่าใช้จ่าย, กำไรสุทธิ")
    baselines: dict[str, Any] = Field(default_factory=dict, description="ผลถ้าไม่ใช้ Optimizer (ไว้เทียบ)")
    decisions: list[dict[str, Any]] = Field(..., description="decision ที่ส่ง/จะส่งเข้า optimization_decisions (รูปแบบเดียวกับ body ของ POST /optimization-decisions)")
    saved: Optional[dict[str, Any]] = Field(None, description="ผลการบันทึก (created + decision_id) เฉพาะ dry_run=false")
    allocations: list[dict[str, Any]] = Field(..., description="รายละเอียดต่อส่วนของ lot: weight_kg, share_pct, เงิน (ไม่บันทึกลงตาราง ส่งให้ส่วนอื่นใช้)")
    lots_released: list[str] = Field(default_factory=list, description="lot ที่ขายราคาปกติได้หมด -> คืน IDLE (หรือจะคืนเมื่อ dry_run=false)")
    skipped_lots: dict[str, Any] = Field(default_factory=dict, description="lot ที่ไม่ได้คิดในรอบนี้พร้อมเหตุผล (เช่น มี decision แล้ว, CHECKED)")
    warnings: list[str] = Field(default_factory=list)
    plan: Optional[dict[str, Any]] = Field(None, description="แผนเต็ม (include_plan=true): ต่อ lot, งานครัว, เที่ยวรับของ, เหตุผลที่ตัดแต่ละทาง")


class ScanRun(BaseModel):
    run_id: UUID
    assessed_at: datetime = Field(..., description="เวลาที่บันทึกผลสแกน (เวลาจริง ไม่ใช่ DEMO_DATE)")
    scan_date: Optional[date] = Field(None, description="วันที่สแกน = วันหมดอายุ - days_to_expiry")
    matches_reference_date: bool = Field(..., description="scan_date ตรงกับ DEMO_DATE / วันนี้")
    lots: int = Field(..., description="จำนวน lot ที่สแกนในรอบนี้")
    levels: dict[str, int] = Field(..., description="จำนวน lot ต่อระดับความเสี่ยง")
    at_risk: int = Field(..., description="HIGH + CRITICAL")
    decided: int = Field(..., description="มี decision แล้ว")
    pending: int = Field(..., description="HIGH / CRITICAL สถานะ PROCESSING ที่ยังไม่มี decision")
    ready: bool = Field(..., description="matches_reference_date และ pending > 0")


class ScanRunsResponse(BaseModel):
    reference_date: date = Field(..., description="วันที่ระบบถือว่าเป็นวันนี้ (DEMO_DATE หรือวันนี้ตามเวลาไทย)")
    suggested_run_id: Optional[UUID] = Field(None, description="รอบล่าสุดที่ ready (null = ไม่มีรอบที่พร้อม)")
    runs: list[ScanRun]