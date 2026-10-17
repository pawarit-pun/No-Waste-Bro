"""PART 9 — การเข้าถึงข้อมูลจริง (แทน database.py เดิม)

1) ApiClient  : เรียก route ตาม Swagger ผ่าน domain + /api/v1/ (ใช้ urllib ของ Python ไม่ต้องติดตั้งอะไรเพิ่ม)
2) Supabase   : load_inputs_from_supabase() สร้างข้อมูลหน้าตาเดียวกับ GET /ai/optimize-inputs จากตารางตรง ๆ
                (ใช้ db.supabase / db.helpers ของโปรเจกต์เดิม import แบบ lazy จึงไม่จำเป็นต้องมี supabase-py ตอน offline)
3) enrich_products_with_flags : optimize-inputs ยังไม่ส่ง allow_animal_feed/composting/anaerobic_digestion/landfill
                มาใน products จึงดึงเติมจาก Supabase (หรือแก้ API ตาม README ข้อ 3 แล้วไม่ต้องเติม)

⚠ POST/PATCH ทุกตัวเขียนข้อมูลจริงลง Supabase — pipeline ตั้ง dry_run=True เป็นค่าเริ่มต้น
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from typing import Any, Callable, Optional

from ai_engine.clock import today_bkk

DEFAULT_API_BASE = "https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1/"
AT_RISK_LEVELS = ["MEDIUM", "HIGH", "CRITICAL"]
DISPOSAL_FLAGS = ("allow_animal_feed", "allow_composting", "allow_anaerobic_digestion", "allow_landfill")


class ApiError(RuntimeError):
    def __init__(self, status: int, body: Any, url: str):
        super().__init__(f"HTTP {status} {url}: {body}")
        self.status, self.body, self.url = status, body, url


class ApiClient:
    """เรียก API ตาม Swagger  base_url เริ่มต้น = DEFAULT_API_BASE (หรือ env API_BASE_URL)

    transport(method, url, body_bytes|None, headers, timeout) -> (status, text) ใช้แทนเน็ตตอนทดสอบ"""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 60.0, transport: Optional[Callable] = None):
        self.base_url = (base_url or os.getenv("API_BASE_URL") or DEFAULT_API_BASE).rstrip("/") + "/"
        self.timeout = timeout
        self._transport = transport or self._urllib_transport

    @staticmethod
    def _urllib_transport(method, url, body, headers, timeout):
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def request(self, method: str, route: str, params: Optional[dict] = None, body: Optional[dict] = None) -> Any:
        url = self.base_url + route.lstrip("/")
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        status, text = self._transport(method, url, data, headers, self.timeout)
        try:
            payload = json.loads(text) if text else None
        except ValueError:
            payload = text
        if status >= 400:
            raise ApiError(status, payload, url)
        return payload

    # ---- route ตาม Swagger ----
    def get_scan_inputs(self) -> dict:
        return self.request("GET", "ai/scan-inputs")

    def set_lot_status(self, lot_ids: list, ai_status: str) -> dict:
        return self.request("PATCH", "inventory-lots/ai-status", body={"lot_ids": lot_ids, "ai_status": ai_status})

    def post_risk_assessments(self, payload: dict) -> dict:
        return self.request("POST", "risk-assessments", body=payload)

    def get_optimize_inputs(self, run_id: Optional[str] = None, days_ahead: int = 1) -> dict:
        return self.request("GET", "ai/optimize-inputs", params={"run_id": run_id, "days_ahead": days_ahead})

    def post_decisions(self, payload: dict) -> dict:
        return self.request("POST", "optimization-decisions", body=payload)

    def get_decisions(self, run_id: Optional[str] = None, status: Optional[str] = None) -> dict:
        return self.request("GET", "optimization-decisions", params={"run_id": run_id, "status": status})


def enrich_products_with_flags(inputs_json: dict, supabase=None) -> dict:
    """เติม allow_animal_feed/composting/anaerobic_digestion/landfill ให้ products ถ้า API ไม่ส่งมา"""
    products = inputs_json.get("products") or []
    if not products or all(f in products[0] for f in DISPOSAL_FLAGS):
        return inputs_json
    if supabase is None:
        try:
            from db.supabase import supabase  # type: ignore  # โปรเจกต์เดิม
        except Exception:
            return inputs_json
    rows = supabase.table("products").select("product_id, " + ", ".join(DISPOSAL_FLAGS)).execute().data
    by_id = {r["product_id"]: r for r in rows}
    for p in products:
        p.update({f: by_id.get(p["product_id"], {}).get(f) for f in DISPOSAL_FLAGS})
    return inputs_json


def load_inputs_from_api(client: Optional[ApiClient] = None, run_id: Optional[str] = None, days_ahead: int = 1,
                         enrich: bool = True) -> dict:
    """GET /ai/optimize-inputs (+ เติม flag การกำจัดจาก Supabase ถ้าทำได้)"""
    data = (client or ApiClient()).get_optimize_inputs(run_id, days_ahead)
    return enrich_products_with_flags(data) if enrich else data


def load_inputs_from_supabase(run_id: Optional[str] = None, days_ahead: int = 1, supabase=None, fetch_all=None) -> dict:
    """สร้างข้อมูลหน้าตาเดียวกับ GET /ai/optimize-inputs จาก Supabase ตรง ๆ (ไม่ผ่าน API)
    ตาราง: lot_risk_assessments, inventory_lots, products, recipes(+recipe_ingredients),
    kitchen_capacity_daily, donation_partners"""
    if supabase is None:
        from db.supabase import supabase  # type: ignore
    if fetch_all is None:
        from db.helpers import fetch_all  # type: ignore
    ref = today_bkk()
    if run_id is None:
        latest = (supabase.table("lot_risk_assessments").select("run_id")
                  .order("assessed_at", desc=True).limit(1).execute())
        run_id = latest.data[0]["run_id"] if latest.data else None
    at_risk = []
    if run_id is not None:
        at_risk = (supabase.table("lot_risk_assessments").select("*, lot:inventory_lots(*)")
                   .eq("run_id", str(run_id)).in_("risk_level", AT_RISK_LEVELS)
                   .order("risk_score", desc=True).execute()).data
    products = fetch_all("products", "*", order_by=("product_id",))
    recipes = (supabase.table("recipes").select("*, ingredients:recipe_ingredients(*)")
               .eq("is_active", True).execute()).data
    end = ref + timedelta(days=days_ahead)
    supabase.rpc("ensure_kitchen_days", {"p_from": ref.isoformat(), "p_to": end.isoformat()}).execute()
    kitchen = (supabase.table("kitchen_capacity_daily")
               .select("department_id, capacity_date, available_hrs, booked_hrs, remaining_hrs, workload_status")
               .gte("capacity_date", ref.isoformat()).lte("capacity_date", end.isoformat())
               .order("capacity_date").execute()).data
    partners = supabase.table("donation_partners").select("*").eq("is_active", True).execute().data

    # ingredient_stock: วัตถุดิบของทุกสูตร เฉพาะ lot ที่ยังไม่หมดอายุ เรียงหมดอายุก่อน (= ลำดับที่ระบบตัดจริง)
    by_id = {p["product_id"]: p for p in products}
    ingredient_ids = sorted({i["ingredient_product_id"] for r in recipes for i in r["ingredients"]})
    stock_lots = fetch_all("inventory_lots",
                           "lot_id, product_id, current_quantity, expiration_date, location_aisle, location_shelf",
                           in_filter=("product_id", ingredient_ids), order_by=("expiration_date", "lot_id")) if ingredient_ids else []
    stock = []
    for pid in ingredient_ids:
        lots = [l for l in stock_lots if l["product_id"] == pid and l["current_quantity"] > 0
                and l["expiration_date"] >= ref.isoformat()]
        prod = by_id.get(pid, {})
        content_unit = "ML" if prod.get("net_content_unit") in ("ML", "L") else "G"
        factor = 1000.0 if prod.get("net_content_unit") in ("KG", "L") else 1.0
        units = sum(l["current_quantity"] for l in lots)
        per_unit = float(prod.get("net_content_value") or 0) * factor
        stock.append({"product_id": pid, "name": prod.get("name"), "net_content_value": prod.get("net_content_value"),
                      "net_content_unit": prod.get("net_content_unit"), "total_units": units,
                      "total_content": units * per_unit, "content_unit": content_unit, "lots": lots})
    return {"reference_date": ref.isoformat(), "run_id": str(run_id) if run_id else None, "at_risk_lots": at_risk,
            "products": products, "recipes": recipes, "kitchen_capacity": kitchen, "donation_partners": partners,
            "ingredient_stock": stock}
