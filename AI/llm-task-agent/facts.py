"""Build Facts: every number comes from the decision, never from the LLM."""

import re
from dataclasses import dataclass, field
from datetime import datetime

from config import TH_TZ
from models import OptimizationDecision

UNIT_TH = {"PIECE": "ชิ้น", "PACK": "แพ็ก", "KG": "กก.", "G": "กรัม", "L": "ลิตร", "ML": "มล."}
ACTION_TH = {
    "MARKDOWN": "ลดราคา",
    "KITCHEN_REPURPOSE": "ส่งเข้าครัว",
    "DONATE": "บริจาค",
    "ANIMAL_FEED": "ส่งทำอาหารสัตว์",
    "COMPOST": "ส่งทำปุ๋ยหมัก",
    "ANAEROBIC_DIGESTION": "ส่งโรงก๊าซชีวภาพ",
    "LANDFILL": "ส่งฝังกลบ",
    "DISCARD": "แยกทิ้ง",
}
# Partner disposal actions (server: action type must match the partner type); DISCARD = self discard in store
DISPOSAL_ACTIONS = ("ANIMAL_FEED", "COMPOST", "ANAEROBIC_DIGESTION", "LANDFILL")
PARTNER_ACTIONS = ("DONATE", *DISPOSAL_ACTIONS)
# Alternatives may use action types or disposal methods
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
MAX_REJECTED = 5
# Optimizer reason codes ("P2_CATEGORY_DAIRY_NOT_ACCEPTED") -> short Thai, matched after the "P2_" prefix.
# Unknown codes are shown as is.
REJECT_REASON_TH = [
    (r"^EXPIRED_FOR_HUMAN_USE", "หมดอายุสำหรับคนแล้ว"),
    (r"^EXPIRED_TO_KITCHEN", "หมดอายุแล้ว ส่งเข้าครัวไม่ได้"),
    (r"^EXPIRED", "หมดอายุแล้ว"),
    (r"^MIN_DAYS", "อายุคงเหลือไม่ถึงเกณฑ์ของผู้รับ"),
    (r"^CATEGORY_(\w+?)_NOT_ACCEPTED", "ผู้รับไม่รับสินค้าหมวด {0}"),
    (r"^FLAG_ALLOW_(\w+?)_FALSE", "สินค้าไม่อนุญาตให้{0}"),
    (r"^(\w+?)_NOT_ALLOWED", "สินค้าไม่อนุญาตให้{0}"),
    (r"^KITCHEN_HOURS", "ชั่วโมงครัวไม่พอ"),
    (r"^EXPIRES_BEFORE_DUE", "หมดอายุก่อนกำหนดผลิต"),
    (r"^NOT_AN_INGREDIENT", "ไม่ใช่วัตถุดิบของสูตร"),
    (r"^NO_AT_RISK_PRIMARY_INGREDIENT", "ไม่ใช่วัตถุดิบหลักของสูตร"),
    (r"^(?:OVER_)?(?:NO_)?MENU_DEMAND", "ไม่มีความต้องการเมนูพอ"),
    (r"^RECIPE_INACTIVE", "สูตรปิดใช้งาน"),
    (r"^NOT_IN_TIME", "ทำไม่ทันเวลา"),
    (r"^INGREDIENT_SHORT", "วัตถุดิบอื่นของสูตรไม่พอ"),
    (r"^BELOW_MIN_PRICE", "ราคาต่ำกว่าราคาขั้นต่ำ"),
    (r"^(?:NO_SALES_EXPECTED|NO_EXTRA_SALES)", "ลดราคาแล้วก็ขายเพิ่มไม่ได้"),
    (r"^(?:NO_)?PICKUP_SLOT", "ไม่มีรอบรับของ"),
    (r"^(?:NO_|PARTNER_)CAPACITY", "ผู้รับรับเพิ่มไม่ได้"),
    (r"^PARTNER_INACTIVE", "ผู้รับปิดใช้งาน"),
    (r"^BELOW_MIN_KG", "น้ำหนักต่ำกว่าขั้นต่ำของผู้รับ"),
]


def fmt_num(value) -> str | None:
    """28.0 -> '28', 143.20 -> '143.2'"""
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
    """ISO datetime; no timezone = Thai time."""
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
    alternatives: list[str] = field(default_factory=list)  # feasible, compared with the chosen action
    rejected: list[str] = field(default_factory=list)  # ruled out by the Optimizer, with reasons
    references: list[str] = field(default_factory=list)  # reference values only, never compared

    @property
    def due(self) -> str | None:
        return self.due_dt.strftime("%Y-%m-%d %H:%M") if self.due_dt else None

    @property
    def location_or_check(self) -> str:
        return self.location or "ตรวจสอบกับระบบ"

    @property
    def expiry_text(self) -> str | None:
        """Negative days written out: the LLM read "เหลือ -2 วัน" as "expires in 2 days"."""
        d = self.days_to_expiry
        if d is None:
            return None
        if d < 0:
            return f"หมดอายุไปแล้ว {-d} วัน"
        return "หมดอายุวันนี้" if d == 0 else f"เหลืออายุ {d} วัน"

    @property
    def reference_values(self) -> set[float]:
        """Reference-only amounts, which must not appear in the LLM's text."""
        found = re.findall(r"(-?[\d.]+) บาท$", "\n".join(self.references), flags=re.M)
        return {abs(float(n)) for n in found}

    @property
    def comparison_diffs(self) -> set[float]:
        """Baht differences computed in code, one per alternative."""
        found = re.findall(r"ทางที่เลือก(?:ดีกว่า|แย่กว่า) ([\d.]+) บาท", self.alternatives_prompt())
        return {float(n) for n in found}

    @property
    def chosen_is_worse(self) -> bool:
        """An alternative beats the chosen action, so a manager should review."""
        return any("ทางที่เลือกแย่กว่า" in line for line in self.alternatives)

    @property
    def has_partner(self) -> bool:
        return bool(self.partner_id or self.partner_name)

    @property
    def partner_label(self) -> str | None:
        if self.partner_name and self.partner_id:
            return f"{self.partner_name} ({self.partner_id})"
        return self.partner_name or self.partner_id

    def to_prompt(self) -> str:
        """FACTS for the LLM; missing values say NO_DATA so it does not guess."""
        days = f" ({self.expiry_text})" if self.expiry_text else ""
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
        if self.action in (*PARTNER_ACTIONS, "DISCARD"):
            if self.has_partner:
                lines.append(f"- ผู้รับ: {self.partner_label}, ประเภท: {self.partner_type or NO_DATA}")
            else:
                lines.append("- ผู้รับ: ไม่มี (ทิ้งตามเส้นทางที่ร้านอนุมัติ)")
        lines.append(f"- ต้องเสร็จภายใน: {self.due or NO_DATA}")
        if self.expected_profit:
            lines.append(f"- ผลกระทบกำไรที่คาดของทางที่เลือก: {self.expected_profit} บาท")
        return "\n".join(lines)

    def alternatives_prompt(self) -> str:
        lines = [*self.alternatives, *self.rejected, *self.references]
        return "\n".join(lines) if lines else "- ไม่มีข้อมูลทางเลือกอื่น"


def _comparison(chosen: float | None, other: float | None) -> str:
    """Compared in code: the LLM gets the direction wrong with negative numbers."""
    if chosen is None or other is None:
        return ""
    diff = round(float(chosen) - float(other), 2)
    if diff > 0:
        return f" → ทางที่เลือกดีกว่า {fmt_num(diff)} บาท"
    if diff < 0:
        return f" → ทางที่เลือกแย่กว่า {fmt_num(-diff)} บาท"
    return " → เท่ากับทางที่เลือก"


def _option_label(alt: dict) -> str:
    label = alt.get("disposal_method") or alt.get("action_type") or "ทางเลือก"
    label = OPTION_TH.get(label, label)
    if alt.get("discount_pct") is not None:
        label += f" {fmt_num(alt['discount_pct'])}%"
    return label


def _alternative_line(alt: dict, chosen_impact: float | None) -> str:
    """Feasible alternative, compared with the chosen action."""
    raw_impact = alt.get("expected_profit_impact", alt.get("net_profit_thb"))
    text = f"- ทางเลือกอื่น: {_option_label(alt)}, ผลกระทบกำไร {fmt_num(raw_impact) or NO_DATA} บาท"
    text += _comparison(chosen_impact, raw_impact)
    note = alt.get("note")
    return text + (f" ({note})" if note else "")


def _reason_th(code: str) -> str:
    key = re.sub(r"^[A-Z]\d+_", "", code.split(" ")[0])  # "P4_MIN_DAYS -3d ..." -> "MIN_DAYS"
    for pattern, text in REJECT_REASON_TH:
        m = re.match(pattern, key)
        if m:
            return text.format(*(OPTION_TH.get(g, g) for g in m.groups()))
    return key


def _rejected_line(alt: dict) -> str:
    """{"option": "DONATION:P-DON-01", "rejected_because": [...]} -> one line without numbers."""
    kind, _, target = alt["option"].partition(":")
    label = OPTION_TH.get(kind, kind) + (f" {target}" if target and target != "ALL" else "")
    reasons = list(dict.fromkeys(_reason_th(r) for r in alt.get("rejected_because") or []))
    return f"- ตัดออก: {label} เพราะ{', '.join(reasons) or NO_DATA}"


def _reference_line(alt: dict) -> str:
    """feasible: false = a reference value, not something staff could do."""
    impact = fmt_num(alt.get("expected_profit_impact"))
    note = re.sub(r"^ค่าอ้างอิง\S*:\s*", "", alt.get("note") or _option_label(alt))
    return f"- ค่าอ้างอิง (ไม่ใช่ทางเลือก ห้ามนำไปเปรียบเทียบ): {note} {impact or NO_DATA} บาท"


def _split_alternatives(alts: list[dict], chosen_impact: float | None) -> tuple[list[str], list[str], list[str]]:
    feasible, rejected, references = [], [], []
    for alt in alts:
        if alt.get("role") == "chosen":
            continue
        if alt.get("rejected_because") is not None or "option" in alt:
            rejected.append(_rejected_line(alt))
        elif alt.get("feasible") is False:
            references.append(_reference_line(alt))
        else:
            feasible.append(_alternative_line(alt, chosen_impact))
    return feasible[:MAX_ALTERNATIVES], rejected[:MAX_REJECTED], references


def build_facts(d: OptimizationDecision) -> Facts:
    lot, product, assessment = d.lot, d.product, d.assessment
    recipe, partner = d.recipe, d.partner

    location = " / ".join(
        x for x in (lot.get("location_aisle"), lot.get("location_shelf")) if x
    ) or None

    expected_output = None
    if d.batch_count and recipe.get("output_quantity"):
        expected_output = fmt_num(d.batch_count * float(recipe["output_quantity"]))

    alternatives, rejected, references = _split_alternatives(d.alternatives, d.expected_profit_impact)

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
        alternatives=alternatives,
        rejected=rejected,
        references=references,
    )
