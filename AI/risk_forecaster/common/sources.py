"""แหล่งข้อมูล 2 โหมด ที่หน้าตาเหมือนกัน

- LocalSource: อ่าน CSV ใน data/mock_v3 แล้วจัดรูปให้เหมือน JSON ของ GET /ai/scan-inputs ทุกฟิลด์
  ไม่เขียนอะไรลง Supabase (ใช้พัฒนา / ทดสอบตอนที่ Supabase ยังไม่ได้โหลด v2)
- ApiSource: เรียก route จริง 3 ตัว (scan-inputs, ai-status, risk-assessments)
"""
import json
from datetime import date, timedelta

import pandas as pd

from common import config

SCAN_PRODUCT_FIELDS = ["product_id", "name", "category", "unit_of_measure", "regular_price", "min_allowed_price",
                       "shelf_life_days"]
LOT_FIELDS = ["lot_id", "product_id", "received_date", "expiration_date", "initial_quantity", "current_quantity",
              "unit_cost", "location_aisle", "location_shelf", "current_selling_price", "ai_status"]


def load_reference():
    products = json.loads((config.REFERENCE_DIR / "products.json").read_text(encoding="utf-8"))
    recipes = json.loads((config.REFERENCE_DIR / "recipes.json").read_text(encoding="utf-8"))
    return products, recipes


def _records(df):
    return json.loads(df.to_json(orient="records", date_format="iso", force_ascii=False))


def _csv_history(product_ids, reference_date, history_days, mock_dir=config.MOCK_DIR):
    """ยอดขายย้อนหลังจาก CSV (ถึงเมื่อวานของ reference_date)"""
    pdy = pd.read_csv(mock_dir / "product_daily.csv", dtype={"stockout_hour": "Int64"})
    start = (reference_date - timedelta(days=history_days)).isoformat()
    keep = pdy.product_id.isin(product_ids) & (pdy.sale_date >= start) & (pdy.sale_date < reference_date.isoformat())
    return _records(pdy[keep].sort_values(["product_id", "sale_date"]))


class LocalSource:
    mode = "local"

    def __init__(self, reference_date=date(2026, 10, 16), mock_dir=config.MOCK_DIR):
        self.reference_date = reference_date
        self.mock_dir = mock_dir

    def scan_inputs(self, history_days=config.HISTORY_DAYS):
        ref = self.reference_date
        lots = pd.read_csv(self.mock_dir / "inventory_lots_demo.csv")
        lots = lots[lots.ai_status == "IDLE"].sort_values(["expiration_date", "lot_id"])
        lots = lots[[c for c in LOT_FIELDS if c in lots.columns]]
        if lots.empty:
            return {"reference_date": ref.isoformat(), "inventory_lots": [], "products": [],
                    "product_daily": [], "daily_context": []}
        product_ids = sorted(lots.product_id.unique())
        ref_products, _ = load_reference()
        products = [{k: p[k] for k in SCAN_PRODUCT_FIELDS} for p in ref_products if p["product_id"] in product_ids]
        ctx = pd.read_csv(self.mock_dir / "daily_context.csv")
        ctx_to = max(lots.expiration_date.max(), (ref + timedelta(days=7)).isoformat())
        ctx = ctx[(ctx.context_date >= ref.isoformat()) & (ctx.context_date <= ctx_to)]
        return {
            "reference_date": ref.isoformat(),
            "inventory_lots": _records(lots),
            "products": products,
            "product_daily": _csv_history(product_ids, ref, history_days, self.mock_dir) if history_days else [],
            "daily_context": _records(ctx),
        }

    def extra_history(self, product_ids, reference_date, history_days=config.HISTORY_DAYS):
        return _csv_history(product_ids, reference_date, history_days, self.mock_dir), False

    # โหมด local ไม่เขียนอะไร
    def set_ai_status(self, lot_ids, status):
        return {"updated": [], "not_found": [], "skipped": "local mode"}

    def post_assessments(self, payload):
        return None


class ApiSource:
    mode = "api"

    def __init__(self, base_url=config.API_BASE_URL, timeout=30):
        import requests

        self.http = requests.Session()
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method, path, **kwargs):
        res = self.http.request(method, f"{self.base}{path}", timeout=self.timeout, **kwargs)
        if res.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {res.status_code}: {res.text[:500]}")
        return res.json()

    def scan_inputs(self, history_days=config.HISTORY_DAYS):
        return self._call("GET", "/ai/scan-inputs", params={"history_days": history_days})

    def extra_history(self, product_ids, reference_date, history_days=config.HISTORY_DAYS):
        """สินค้าที่ scan-inputs ไม่ส่งยอดขายมา (เมนูครัวที่ไม่มี lot IDLE) ใช้ CSV ที่ export ไว้แทน (อาจไม่อัปเดต)"""
        rows = _csv_history(product_ids, reference_date, history_days)
        return rows, True

    def set_ai_status(self, lot_ids, status):
        if not lot_ids:
            return {"updated": [], "not_found": []}
        return self._call("PATCH", "/inventory-lots/ai-status", json={"lot_ids": list(lot_ids), "ai_status": status})

    def post_assessments(self, payload):
        return self._call("POST", "/risk-assessments", json=payload)
