"""Retrieve SOP chunks (RAG) from the Bedrock Knowledge Base by action_type."""

from config import settings

QUERY_BY_ACTION = {
    "MARKDOWN": "ขั้นตอนลดราคาสินค้าใกล้หมดอายุ ตรวจสอบก่อนติดป้ายและเปลี่ยนราคาใน POS",
    "KITCHEN_REPURPOSE": "ขั้นตอนนำวัตถุดิบไปแปรรูปในครัว ตรวจความพร้อมของครัว สูตร และบันทึกผลผลิต",
    "DONATE": "ขั้นตอนบริจาคอาหาร ตรวจสินค้าและยืนยันการรับมอบกับผู้รับบริจาค",
    "DISCARD": "ขั้นตอนแยกทิ้งสินค้า การอนุมัติ เส้นทางกำจัด และการบันทึกปริมาณจริง",
}
# Partner disposal actions use the DISCARD SOPs (KB documents are tagged MARKDOWN / KITCHEN_REPURPOSE / DONATE / DISCARD / ALL)
KB_ACTION = {"ANIMAL_FEED": "DISCARD", "COMPOST": "DISCARD", "ANAEROBIC_DIGESTION": "DISCARD", "LANDFILL": "DISCARD"}
DEFAULT_QUERY = "ขั้นตอนการทำงานและเงื่อนไขหยุด"
MAX_CHUNK_CHARS = 1200


class KBRetriever:
    """Chunks: {"doc_id", "score", "text"}, cached per action + category."""

    def __init__(self):
        import boto3  # lazy: offline runs need no AWS

        self.client = boto3.client("bedrock-agent-runtime", region_name=settings.BEDROCK_REGION)
        self._cache: dict[str, list[dict]] = {}

    def retrieve(self, action: str, category: str | None = None) -> list[dict]:
        key = f"{action}|{category}"
        if key in self._cache:
            return self._cache[key]

        kb_action = KB_ACTION.get(action, action)
        query = QUERY_BY_ACTION.get(kb_action, DEFAULT_QUERY)
        if category:
            query += f" สินค้าหมวด {category}"

        # Docs for this action + docs for ALL actions
        response = self.client.retrieve(
            knowledgeBaseId=settings.BEDROCK_KB_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": {
                "numberOfResults": settings.KB_RESULTS,
                "filter": {"orAll": [
                    {"equals": {"key": "action_type", "value": kb_action}},
                    {"equals": {"key": "action_type", "value": "ALL"}},
                ]},
            }},
        )

        chunks = []
        for result in response.get("retrievalResults", []):
            metadata = result.get("metadata", {})
            chunks.append({
                "doc_id": metadata.get("doc_id", "UNKNOWN"),
                "score": round(float(result.get("score", 0)), 4),
                "text": " ".join(result["content"]["text"].split())[:MAX_CHUNK_CHARS],
            })
        self._cache[key] = chunks
        return chunks


class NullRetriever:
    """No KB (offline runs and tests)."""

    def retrieve(self, action: str, category: str | None = None) -> list[dict]:
        return []
