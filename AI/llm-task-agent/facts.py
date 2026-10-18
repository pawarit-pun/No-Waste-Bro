"""Build Facts: every number the task uses comes from the decision, never from the LLM."""

from dataclasses import dataclass, field
from datetime import datetime

from config import TH_TZ
from models import OptimizationDecision

UNIT_TH = {"PIECE": "ชิ้น", "PACK": "แพ็ก", "KG": "กก.", "G": "กรัม", "L": "ลิตร", "ML": "มล."}
ACTION_TH = {
    "MARKDOWN": "ลดราคา",
    "KITCHEN_REPURPOSE": "ส่งเข้าครัว",
    "DONATE": "บริจาค",
    "DISCARD": "แยกทิ้ง",
}
# Labels for alternatives (the Optimizer may use action types or disposal methods)
OPTION_TH = {
    **ACTION_TH,
    "SELF_DISCARD": "ทิ้งเอง",
    "LANDFILL": "ส่งฝังกลบ",
    "ANIMAL_FEED": "ส่งทำอาหารสัตว์",
    "COMPOSTING": "ส่งทำปุ๋ยหมัก",
    "COMPOST": "ส่งทำปุ๋ยหมัก",
    "ANAEROBIC_DIGESTION": "ส่งย่อยแบบไม่ใช้ออกซิเจน",
    "KITCHEN": "ส่งเข้าครัว",
    "DONATION": "บริจาค",
}
NO_DATA = "ไม่มีข้อมูล"
MAX_ALTERNATIVES = 3


def fmt_num(value) -> str | None:
    """Format a number without trailing zeros, e.g. 28.0 -> '28', 143.20 -> '143.2'."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO datetime; a value without timezone is Thai time."""
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TH_TZ)
    return dt.astimezone(TH_TZ)


@dataclass
class Facts:
    decision_id: str
    action: str
    lot_id: str
    product_name: str
    category: str | None
    unit: str
    qty: str
    location: str | None
    current_qty: str | None = None
    price_old: str | None = None
    discount_pct: str | None = None
    new_price: str | None = None
    expiry: str | None = None
    days_to_expiry: int | None = None
    risk_level: str | None = None
    risk_score: str | None = None
    leftover: str | None = None
    due_dt: datetime | None = None
    recipe_id: str | None = None
    recipe_name: str | None = None
    kitchen: str | None = None
    batch: str | None = None
    expected_output: str | None = None
    partner_id: str | None = None
    partner_name: str | None = None
    partner_type: str | None = None
    expected_profit: str | None = None
    alternatives: list[str] = field(default_factory=list)

    @property
    def due(self) -> str | None:
        return self.due_dt.strftime("%Y-%m-%d %H:%M") if self.due_dt else None

    @property
    def location_or_check(self) -> str:
        return self.location or "ตรวจสอบกับระบบ"

    @property
    def has_partner(self) -> bool:
        return bool(self.partner_id or self.partner_name)

    @property
    def partner_label(self) -> str | None:
        if self.partner_name and self.partner_id:
            return f"{self.partner_name} ({self.partner_id})"
        return self.partner_name or self.partner_id

    def to_prompt(self) -> str:
        """FACTS block for the LLM. Missing values say NO_DATA so the model does not guess."""
        days = f" (เหลือ {self.days_to_expiry} วัน)" if self.days_to_expiry is not None else ""
        lines = [
            f"- action_type: {self.action} ({ACTION_TH.get(self.action, self.action)})",
            f"- สินค้า: {self.product_name} ({self.category or NO_DATA}), lot: {self.lot_id}",
            f"- ตำแหน่ง: {self.location or NO_DATA}",
            f"- จำนวนคงเหลือใน lot: {self.current_qty or NO_DATA} {self.unit}, "
            f"จำนวนที่ต้องทำในงานนี้: {self.qty} {self.unit}",
            f"- หมดอายุ: {self.expiry or NO_DATA}{days}, "
            f"risk_level: {self.risk_level or NO_DATA}, risk_score: {self.risk_score or NO_DATA}",
        ]
        if self.leftover:
            lines.append(f"- คาดว่าจะเหลือตอนหมดอายุถ้าไม่ทำอะไร: {self.leftover} {self.unit}")
        if self.action == "MARKDOWN":
            lines.append(
                f"- ราคาเดิม: {self.price_old or NO_DATA} บาท, ส่วนลด: {self.discount_pct or NO_DATA}%, "
                f"ราคาใหม่: {self.new_price or NO_DATA} บาท"
            )
        if self.action == "KITCHEN_REPURPOSE":
            recipe = f"{self.recipe_id or NO_DATA} {self.recipe_name or ''}".rstrip()
            lines.append(
                f"- สูตร: {recipe}, ครัว: {self.kitchen or NO_DATA}, จำนวน batch: {self.batch or NO_DATA}"
            )
            if self.expected_output:
                lines.append(f"- ผลผลิตที่คาด: {self.expected_output} ชิ้น (ค่าประมาณ ไม่ใช่เป้าบังคับ)")
        if self.action in ("DONATE", "DISCARD"):
            if self.has_partner:
                lines.append(f"- ผู้รับ: {self.partner_label}, ประเภท: {self.partner_type or NO_DATA}")
            else:
                lines.append("- ผู้รับ: ไม่มี (ทิ้งตามเส้นทางที่ร้านอนุมัติ)")
        lines.append(f"- ต้องเสร็จภายใน: {self.due or NO_DATA}")
        if self.expected_profit:
            lines.append(f"- ผลกระทบกำไรที่คาดของทางที่เลือก: {self.expected_profit} บาท")
        return "\n".join(lines)

    def alternatives_prompt(self) -> str:
        return "\n".join(self.alternatives) if self.alternatives else "- ไม่มีข้อมูลทางเลือกอื่น"


def _alternative_line(alt: dict) -> str | None:
    """One readable line per alternative the Optimizer did not choose."""
    if alt.get("role") == "chosen":
        return None
    label = alt.get("disposal_method") or alt.get("action_type") or "ทางเลือก"
    label = OPTION_TH.get(label, label)
    if alt.get("discount_pct") is not None:
        label += f" {fmt_num(alt['discount_pct'])}%"
    impact = fmt_num(alt.get("expected_profit_impact", alt.get("net_profit_thb")))
    text = f"- ทางเลือกอื่น: {label}, ผลกระทบกำไร {impact or NO_DATA} บาท"
    note = alt.get("note")
    return text + (f" ({note})" if note else "")


def build_facts(d: OptimizationDecision) -> Facts:
    lot, product, assessment = d.lot, d.product, d.assessment
    recipe, partner = d.recipe, d.partner

    location = " / ".join(
        x for x in (lot.get("location_aisle"), lot.get("location_shelf")) if x
    ) or None

    expected_output = None
    if d.batch_count and recipe.get("output_quantity"):
        expected_output = fmt_num(d.batch_count * float(recipe["output_quantity"]))

    alternatives = [line for line in map(_alternative_line, d.alternatives) if line]

    return Facts(
        decision_id=d.decision_id,
        action=d.action_type.upper(),
        lot_id=d.lot_id or lot.get("lot_id") or NO_DATA,
        product_name=product.get("name") or d.lot_id or NO_DATA,
        category=product.get("category"),
        unit=UNIT_TH.get(product.get("unit_of_measure") or "PIECE", "ชิ้น"),
        qty=fmt_num(d.action_quantity),
        location=location,
        current_qty=fmt_num(lot.get("current_quantity")),
        price_old=fmt_num(lot.get("current_selling_price")),
        discount_pct=fmt_num(d.discount_pct),
        new_price=fmt_num(d.new_recommended_price),
        expiry=lot.get("expiration_date"),
        days_to_expiry=assessment.get("days_to_expiry"),
        risk_level=assessment.get("risk_level"),
        risk_score=fmt_num(assessment.get("risk_score")),
        leftover=fmt_num(assessment.get("predicted_leftover_units")),
        due_dt=parse_dt(d.due_by),
        recipe_id=d.target_recipe_id or recipe.get("recipe_id"),
        recipe_name=recipe.get("name"),
        kitchen=recipe.get("department_id"),
        batch=fmt_num(d.batch_count),
        expected_output=expected_output,
        partner_id=d.target_partner_id or partner.get("partner_id"),
        partner_name=partner.get("name"),
        partner_type=partner.get("partner_type"),
        expected_profit=fmt_num(d.expected_profit_impact),
        alternatives=alternatives[:MAX_ALTERNATIVES],
    )
