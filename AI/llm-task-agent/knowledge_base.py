"""Retrieve SOP chunks (RAG) from the Bedrock Knowledge Base, filtered by action_type."""

from config import settings

QUERY_BY_ACTION = {
    "MARKDOWN": "ขั้นตอนลดราคาสินค้าใกล้หมดอายุ ตรวจสอบก่อนติดป้ายและเปลี่ยนราคาใน POS",
    "KITCHEN_REPURPOSE": "ขั้นตอนนำวัตถุดิบไปแปรรูปในครัว ตรวจความพร้อมของครัว สูตร และบันทึกผลผลิต",
    "DONATE": "ขั้นตอนบริจาคอาหาร ตรวจสินค้าและยืนยันการรับมอบกับผู้รับบริจาค",
    "DISCARD": "ขั้นตอนแยกทิ้งสินค้า การอนุมัติ เส้นทางกำจัด และการบันทึกปริมาณจริง",
}
DEFAULT_QUERY = "ขั้นตอนการทำงานและเงื่อนไขหยุด"
MAX_CHUNK_CHARS = 1200


class KBRetriever:
    """Each chunk: {"doc_id", "score", "text"}. Results are cached per action + category for one run."""

    def __init__(self):
        import boto3  # imported here so offline runs work without AWS access

        self.client = boto3.client("bedrock-agent-runtime", region_name=settings.BEDROCK_REGION)
        self._cache: dict[str, list[dict]] = {}

    def retrieve(self, action: str, category: str | None = None) -> list[dict]:
        key = f"{action}|{category}"
        if key in self._cache:
            return self._cache[key]

        query = QUERY_BY_ACTION.get(action, DEFAULT_QUERY)
        if category:
            query += f" สินค้าหมวด {category}"

        # Documents tagged with this action, plus those that apply to every action
        response = self.client.retrieve(
            knowledgeBaseId=settings.BEDROCK_KB_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": {
                "numberOfResults": settings.KB_RESULTS,
                "filter": {"orAll": [
                    {"equals": {"key": "action_type", "value": action}},
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
    """No Knowledge Base (offline runs and tests)."""

    def retrieve(self, action: str, category: str | None = None) -> list[dict]:
        return []
