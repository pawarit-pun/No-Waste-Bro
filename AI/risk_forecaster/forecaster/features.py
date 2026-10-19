"""สร้าง feature ของ Forecaster แบบเดียวกันทั้งตอนเทรนและตอนทำนาย

แนวคิด "origin": ตอนทำนายเรารู้ยอดขายถึงเมื่อวานเท่านั้น (origin = วันนี้)
แล้วทำนายวัน origin, origin+1, ... ไปจนถึงวันหมดอายุ (horizon = 1, 2, ...)
ตอนเทรนจึงจำลองแบบเดียวกัน: ทุก origin ในอดีต คำนวณ lag จากข้อมูลก่อน origin แล้วจับคู่กับยอดขายจริงของวันข้างหน้า
(evaluation on a rolling forecasting origin, Hyndman)

ยอดขายที่ใช้เป็น "ยอดสะอาด" = วันที่ของไม่หมดชั้น และไม่ลดราคา (ยอดจริงที่ราคาเต็ม ไม่ถูกตัดหัว)
"""
from datetime import timedelta

import numpy as np
import pandas as pd

from common import config

BOOL_COLS = ["is_weekend", "is_public_holiday", "is_long_weekend_day", "is_pension_day", "is_private_payday"]
CAT_FEATURES = ["product_id", "category"]
CONTEXT_FEATURES = ["is_weekend", "is_public_holiday", "is_long_weekend_day", "pre_long", "is_pension_day",
                    "is_private_payday", "days_since_any_payday", "pay0_2", "pay_late", "rain_mm",
                    "rain_mm_16_20", "temp_max_c", "heavy_rain"]
NUM_FEATURES = ["horizon", "dow"] + CONTEXT_FEATURES + ["shelf_life_days", "lag7", "lag28", "lag56", "ewm7", "dow_mean"]
FEATURES = CAT_FEATURES + NUM_FEATURES
EWM_HALFLIFE = 7


def _to_bool(s):
    return s.astype(str).str.lower().isin(["true", "1"])


def prepare_history(product_daily, clearance_products=()):
    """product_daily (จาก CSV หรือ scan-inputs) -> ตาราง วัน x สินค้า ของยอดสะอาด (NaN = ใช้ไม่ได้)

    clearance_products: สินค้าที่ลดราคาเฉพาะของเหลือช่วงค่ำ วันลดราคาของสินค้าเหล่านี้ยังนับเป็นยอดสะอาด
    """
    df = pd.DataFrame(product_daily).copy()
    df["sale_date"] = pd.to_datetime(df["sale_date"])
    df["is_stockout"] = _to_bool(df["is_stockout"])
    df["markdown_pct"] = pd.to_numeric(df["markdown_pct"])
    full_price = (df["markdown_pct"] == 0) | df["product_id"].isin(set(clearance_products))
    df["clean_sold"] = df["sold_qty"].where(~df["is_stockout"] & full_price)
    pivot = df.pivot_table(index="sale_date", columns="product_id", values="clean_sold", aggfunc="first")
    return df, pivot


def prepare_context(daily_context):
    ctx = pd.DataFrame(daily_context).copy()
    ctx["context_date"] = pd.to_datetime(ctx["context_date"])
    ctx = ctx.sort_values("context_date").set_index("context_date")
    for c in BOOL_COLS:
        ctx[c] = _to_bool(ctx[c]).astype(int)
    off = (ctx.is_weekend == 1) | (ctx.is_public_holiday == 1)
    nxt = ctx.is_long_weekend_day.shift(-1, fill_value=0)
    ctx["pre_long"] = ((~off) & (nxt == 1)).astype(int)            # วันทำงานก่อนหยุดยาว (คนซื้อตุน)
    ctx["pay0_2"] = (ctx.days_since_any_payday <= 2).astype(int)    # 0-2 วันหลังเงินเดือนออก
    ctx["pay_late"] = (ctx.days_since_any_payday >= 12).astype(int)  # ปลายรอบเงินเดือน
    ctx["heavy_rain"] = (ctx.rain_mm >= 50).astype(int)
    return ctx


def origin_stats(pivot, origin):
    """ค่าจากยอดสะอาดก่อน origin: เฉลี่ย 7 / 28 / 56 วัน, ค่าเฉลี่ยถ่วงน้ำหนักเวลา และแยกตามวันในสัปดาห์ (28 วัน)"""
    win56 = pivot.loc[(pivot.index >= origin - timedelta(days=56)) & (pivot.index < origin)]
    win28 = win56.loc[win56.index >= origin - timedelta(days=28)]
    win7 = win28.loc[win28.index >= origin - timedelta(days=7)]
    age = np.asarray((origin - win56.index).days, dtype=float)
    weights = pd.Series(0.5 ** (age / EWM_HALFLIFE), index=win56.index)
    mask = win56.notna()
    ewm = (win56.fillna(0).mul(weights, axis=0).sum() / mask.mul(weights, axis=0).sum()).where(mask.any())
    by_dow = win28.groupby(win28.index.weekday + 1).mean()           # แถว = dow (1 = จันทร์), คอลัมน์ = สินค้า
    return {"lag7": win7.mean(), "lag28": win28.mean(), "lag56": win56.mean(), "ewm7": ewm}, by_dow


def build_rows(pivot, ctx, products, origin, targets):
    """targets = [(product_id, date), ...] -> DataFrame feature 1 แถวต่อ target"""
    stats, by_dow = origin_stats(pivot, origin)
    prod = products.set_index("product_id")
    rows = []
    for pid, day in targets:
        day = pd.Timestamp(day)
        c = ctx.loc[day] if day in ctx.index else None
        dow = day.isoweekday()
        dm = by_dow.at[dow, pid] if (dow in by_dow.index and pid in by_dow.columns) else np.nan
        row = {"product_id": pid, "category": prod.at[pid, "category"], "date": day,
               "horizon": min((day - origin).days + 1, config.MAX_HORIZON), "dow": dow,
               "shelf_life_days": prod.at[pid, "shelf_life_days"]}
        for k, series in stats.items():
            row[k] = series.get(pid, np.nan)
        row["dow_mean"] = dm if not np.isnan(dm) else row["lag28"]
        for col in CONTEXT_FEATURES:
            row[col] = c[col] if c is not None else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def training_rows(history_df, pivot, ctx, products, horizon, min_history_days):
    """ชุดเทรนแบบ origin: ทุก origin ที่มีประวัติพอ x ทุกสินค้า x horizon 1..H (label = ยอดสะอาดของวันเป้าหมาย)"""
    days = sorted(history_df.sale_date.unique())
    first, last = pd.Timestamp(days[0]), pd.Timestamp(days[-1])
    origin = first + timedelta(days=min_history_days)
    labels = history_df.set_index(["product_id", "sale_date"])
    parts = []
    while origin <= last:
        targets = [(pid, origin + timedelta(days=h)) for pid in pivot.columns for h in range(horizon)
                   if origin + timedelta(days=h) <= last]
        part = build_rows(pivot, ctx, products, origin, targets)
        part["origin"] = origin
        key = list(zip(part.product_id, part.date))
        part["y"] = labels["clean_sold"].reindex(key).to_numpy()
        part["latent_demand"] = labels["latent_demand"].reindex(key).to_numpy() if "latent_demand" in labels else np.nan
        parts.append(part)
        origin += timedelta(days=1)
    return pd.concat(parts, ignore_index=True)
