"""Forecaster: ทำนายความต้องการต่อวันที่ราคาเต็ม + ผลของการลดราคา + ความผันผวน

การแบ่งข้อมูล (ตามเวลา, rolling origin):
  train      : วันเป้าหมายก่อน validation
  validation : 20% ก่อน test (อย่างน้อย 28 วัน) ใช้เลือก parameter ของ LightGBM, เลือกโมเดล, วัด phi
  test       : 20% ล่าสุด (อย่างน้อย 28 วัน) ใช้รายงานผลเท่านั้น
  ใช้งานจริง  : เทรนใหม่ด้วยข้อมูลทั้งหมด

- 2 โมเดล: same-dow (ค่าเฉลี่ยวันเดียวกันในสัปดาห์ 4 สัปดาห์ล่าสุด) และ LightGBM (Poisson)
- lift ของการลดราคา: วัน "ลดทั้งวัน" เทียบกับยอดปกติของสินค้าเดียวกันวันเดียวกันในสัปดาห์
- phi_k = variance / mean ของยอดรวม k วัน จาก residual ของ validation ใช้หาโอกาสขายหมดและช่วง low-high
"""
import json
import pickle
from datetime import timedelta

import numpy as np
import pandas as pd

from common import config
from forecaster.features import (CAT_FEATURES, FEATURES, build_rows, prepare_context, prepare_history,
                               training_rows)

PRODUCT_DAILY_COLS = ["product_id", "sale_date", "opening_qty", "received_qty", "sold_qty", "sold_full_price_qty",
                      "markdown_sold_qty", "waste_qty", "closing_qty", "is_stockout", "stockout_hour",
                      "markdown_pct", "regular_price", "avg_selling_price", "latent_demand"]
CONTEXT_COLS = ["context_date", "dow", "is_weekend", "is_public_holiday", "is_long_weekend_day", "is_pension_day",
                "is_private_payday", "days_since_any_payday", "rain_mm", "rain_mm_16_20", "temp_max_c", "temp_min_c"]
BASE_PARAMS = dict(objective="poisson", subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)


def wape(pred, actual):
    pred, actual = np.asarray(pred, float), np.asarray(actual, float)
    return float(np.abs(pred - actual).sum() / max(actual.sum(), 1e-9) * 100)


def bias(pred, actual):
    pred, actual = np.asarray(pred, float), np.asarray(actual, float)
    return float((pred.sum() - actual.sum()) / max(actual.sum(), 1e-9) * 100)


def split_training_csv(df):
    """training_dataset.csv (join แล้ว) -> product_daily, daily_context, products"""
    df = df.copy()
    df["sale_date"] = pd.to_datetime(df["sale_date"])
    product_daily = df[[c for c in PRODUCT_DAILY_COLS if c in df.columns]]
    ctx = df.rename(columns={"sale_date": "context_date"})[CONTEXT_COLS].drop_duplicates("context_date")
    products = df[["product_id", "category", "shelf_life_days"]].drop_duplicates("product_id")
    return product_daily, ctx, products


def split_dates(days):
    """วันเริ่ม validation และ test จากจำนวนวันในประวัติ"""
    days = sorted(pd.to_datetime(pd.Series(days)).unique())
    n = len(days)
    test_n = max(config.MIN_WINDOW_DAYS, int(round(n * config.TEST_FRACTION)))
    val_n = max(config.MIN_WINDOW_DAYS, int(round(n * config.VAL_FRACTION)))
    last = pd.Timestamp(days[-1])
    test_start = last - timedelta(days=test_n - 1)
    val_start = test_start - timedelta(days=val_n)
    return pd.Timestamp(days[0]), val_start, test_start, last


class Forecaster:
    def __init__(self):
        self.model = None
        self.params = dict(config.LGBM_GRID[1])
        self.chosen = "same_dow"
        self.categories = {}
        self.phi = {1: 1.5}
        self.lifts = {0: 1.0}
        self.metrics = {}
        self.feature_importance = {}
        self.val_start = self.test_start = None
        self.version = config.MODEL_VERSION

    # ------------------------------------------------------------------ data
    @staticmethod
    def clearance_products(products):
        return set(products.loc[products.category.isin(config.CLEARANCE_ONLY_CATEGORIES), "product_id"])

    def build_training(self, training_df):
        product_daily, ctx_raw, products = split_training_csv(training_df)
        hist, pivot = prepare_history(product_daily, self.clearance_products(products))
        ctx = prepare_context(ctx_raw)
        rows = training_rows(hist, pivot, ctx, products, config.MAX_HORIZON, config.MIN_HISTORY_DAYS)
        self.categories = {c: sorted(rows[c].unique()) for c in CAT_FEATURES}
        return hist, products, rows

    def _X(self, df):
        X = df[FEATURES].copy()
        for c in CAT_FEATURES:
            X[c] = pd.Categorical(X[c], categories=self.categories[c])
        return X

    @staticmethod
    def _baseline(rows):
        return rows.dow_mean.fillna(rows.lag28).fillna(rows.lag56).fillna(rows.lag7).fillna(0).clip(lower=0).to_numpy()

    def model_until(self, rows, until, params=None):
        """LightGBM ที่เทรนด้วยวันเป้าหมายก่อน until เท่านั้น"""
        import lightgbm as lgb
        train = rows[(rows.date < until) & rows.y.notna()]
        return lgb.LGBMRegressor(**BASE_PARAMS, **(params or self.params)).fit(self._X(train), train.y)

    def _predict_rows(self, rows, model):
        base = self._baseline(rows)
        if self.chosen != "lgbm" or model is None:
            return base
        pred = np.clip(model.predict(self._X(rows)), 0, None)
        return np.where(rows.lag28.isna().to_numpy() & rows.lag56.isna().to_numpy(), base, pred)

    # ------------------------------------------------------------------ training
    def fit(self, training_df):
        hist, products, rows = self.build_training(training_df)
        first, self.val_start, self.test_start, last = split_dates(hist.sale_date.unique())
        truth_col = "latent_demand" if rows.latent_demand.notna().any() else "y"

        # 1) validation: เลือก parameter และโมเดล
        val = rows[(rows.origin >= self.val_start) & (rows.origin < self.test_start)
                   & (rows.date < self.test_start) & rows.y.notna()].copy()
        grid = []
        for params in config.LGBM_GRID:
            m = self.model_until(rows, self.val_start, params)
            grid.append((wape(np.clip(m.predict(self._X(val)), 0, None), val[truth_col]), params, m))
        grid.sort(key=lambda g: g[0])
        best_wape, self.params, val_model = grid[0]
        base_wape = wape(self._baseline(val), val[truth_col])
        self.chosen = "lgbm" if best_wape < base_wape else "same_dow"
        val["pred"] = self._predict_rows(val, val_model)
        self.phi = self._estimate_phi(val)

        # 2) test: เทรนด้วย train + validation แล้ววัดผลครั้งเดียว
        test = rows[(rows.origin >= self.test_start) & rows.y.notna()].copy()
        test_model = self.model_until(rows, self.test_start)
        test["pred_lgbm"] = np.clip(test_model.predict(self._X(test)), 0, None)
        test["pred_same_dow"] = self._baseline(test)
        pick = f"pred_{self.chosen}"
        self.metrics = {
            "history": f"{first.date()} -> {last.date()} ({(last - first).days + 1} วัน)",
            "split": {"train": f"{first.date()} -> {(self.val_start - timedelta(days=1)).date()}",
                      "validation": f"{self.val_start.date()} -> {(self.test_start - timedelta(days=1)).date()}",
                      "test": f"{self.test_start.date()} -> {last.date()}"},
            "rows": {"train": int(((rows.date < self.val_start) & rows.y.notna()).sum()),
                     "validation": int(len(val)), "test": int(len(test))},
            "validation_wape": {"same_dow": round(base_wape, 2),
                                **{f"lgbm_{i}": round(g[0], 2) for i, g in enumerate(grid)}},
            "params": self.params, "chosen": self.chosen,
            "test_wape": {"same_dow": round(wape(test.pred_same_dow, test[truth_col]), 2),
                          "lgbm": round(wape(test.pred_lgbm, test[truth_col]), 2)},
            "test_wape_by_horizon": {int(h): round(wape(g[pick], g[truth_col]), 2) for h, g in test.groupby("horizon")},
            "test_wape_by_category": {c: round(wape(g[pick], g[truth_col]), 2) for c, g in test.groupby("category")},
            "test_wape_by_product": {p: round(wape(g[pick], g[truth_col]), 2) for p, g in test.groupby("product_id")},
            # FVA: โมเดลที่เลือกดีกว่าตัวเทียบ same-dow กี่ % (Gilliland, Forecast Value Added)
            "test_fva_pct": round((1 - wape(test[pick], test[truth_col])
                                   / max(wape(test.pred_same_dow, test[truth_col]), 1e-9)) * 100, 2),
            # bias = (ทายรวม - จริงรวม) / จริงรวม x 100: บวก = ทายเกิน (risk_score จะต่ำกว่าจริง), ลบ = ทายขาด
            "test_bias_pct": round(bias(test[pick], test[truth_col]), 2),
            "test_bias_by_category": {c: round(bias(g[pick], g[truth_col]), 2) for c, g in test.groupby("category")},
            "phi_by_days": {int(k): round(v, 3) for k, v in self.phi.items()},
        }
        # coverage: ยอดจริงตกในช่วง 10-90% ของ Negative Binomial กี่ % (ควรใกล้ 80) ของยอดรวม 1 / 3 / 7 วัน
        self.metrics["test_coverage_80"] = self._coverage(test, pick, truth_col)

        # 3) ใช้งานจริง: เทรนด้วยข้อมูลทั้งหมด
        self.model = self.model_until(rows, last + timedelta(days=1))
        gain = self.model.booster_.feature_importance("gain")
        self.feature_importance = dict(sorted(zip(FEATURES, (gain / gain.sum() * 100).round(2).tolist()),
                                              key=lambda kv: -kv[1]))
        self.lifts = self._estimate_lifts(hist, self.clearance_products(products))
        self.metrics["markdown_lift"] = self.lifts
        return self

    @staticmethod
    def _estimate_phi(val):
        """phi ของยอดรวม k วันแรก (k = 1..MAX_HORIZON) เฉพาะ origin x สินค้าที่มียอดครบทุกวัน"""
        phi = {}
        val = val.sort_values(["origin", "product_id", "horizon"])
        for k in range(1, config.MAX_HORIZON + 1):
            part = val[val.horizon <= k]
            g = part.groupby(["origin", "product_id"]).agg(y=("y", "sum"), p=("pred", "sum"), n=("y", "size"))
            g = g[g.n == k]
            if len(g) < 20 or g.p.sum() <= 0:
                break
            # ไม่ให้ลดลงเมื่อรวมหลายวันขึ้น (หน้าต่างยาวมีตัวอย่างน้อย ค่าจะแกว่ง) เลือกค่าที่ระวังกว่า
            phi[k] = float(max(1.05, phi.get(k - 1, 0), ((g.y - g.p) ** 2).sum() / g.p.sum()))
        return phi or {1: 1.5}

    def _coverage(self, test, pick, truth_col, days=(1, 3, 7)):
        """สัดส่วนที่ยอดจริงรวม k วันแรกอยู่ในช่วง [quantile 10%, quantile 90%] ของ NB(mean = ที่ทาย, phi_k)
        ถ้าต่ำกว่า 80 มาก = ช่วงแคบเกินไป (มั่นใจเกินจริง), สูงกว่ามาก = ช่วงกว้างเกินไป (Gneiting et al. 2007)"""
        from risk_scanner import nb
        out = {}
        test = test.sort_values(["origin", "product_id", "horizon"])
        for k in days:
            part = test[test.horizon <= k]
            g = part.groupby(["origin", "product_id"]).agg(y=(truth_col, "sum"), p=(pick, "sum"), n=(truth_col, "size"))
            g = g[g.n == k]
            if g.empty:
                continue
            phi = self.phi_for(k)
            inside = [nb.quantile(0.10, p, phi) <= y <= nb.quantile(0.90, p, phi) for y, p in zip(g.y, g.p)]
            out[int(k)] = {"coverage_pct": round(float(np.mean(inside)) * 100, 1), "n": int(len(g))}
        return out

    def phi_for(self, days):
        days = max(1, int(days))
        if days in self.phi:
            return self.phi[days]
        return self.phi[max(self.phi)]

    @staticmethod
    def _estimate_lifts(hist, clearance_products):
        """ยอดวันลดทั้งวัน / ยอดปกติ (สินค้าเดียวกัน วันเดียวกันในสัปดาห์) ไม่รวมวันของหมดชั้น
        และไม่รวมหมวดที่ลดเฉพาะของเหลือ (RTE: วันที่ไม่ลดราคาคือวันที่ของขายหมดเร็ว ใช้เป็นยอดปกติไม่ได้)"""
        h = hist[~hist.is_stockout & ~hist.product_id.isin(clearance_products)].copy()
        h["dow"] = h.sale_date.dt.weekday + 1
        base = h[h.markdown_pct == 0].groupby(["product_id", "dow"]).sold_qty.mean().rename("base")
        full_day = (h.markdown_pct > 0) & (h.markdown_sold_qty >= config.FULL_DAY_MARKDOWN_SHARE * h.sold_qty)
        md = h[full_day].join(base, on=["product_id", "dow"])
        md = md[md.base > 0]
        ratio = (md.sold_qty / md.base).groupby(md.markdown_pct)
        lifts = {0: 1.0}
        for pct in config.DISCOUNT_LEVELS[1:]:
            if pct in ratio.groups and ratio.get_group(pct).size >= config.MIN_LIFT_DAYS:
                lifts[pct] = round(float(ratio.get_group(pct).mean()), 3)
        # ต้องไม่ลดลงเมื่อส่วนลดมากขึ้น และเติมระดับที่ไม่มีข้อมูลด้วยการประมาณเส้นตรงจากจุดที่มี
        known = sorted(lifts.items())
        for pct in config.DISCOUNT_LEVELS:
            if pct not in lifts:
                lifts[pct] = round(float(np.interp(pct, [k for k, _ in known], [v for _, v in known])), 3)
        running = 1.0
        for pct in sorted(lifts):
            running = max(running, lifts[pct])
            lifts[pct] = running
        return {int(k): v for k, v in sorted(lifts.items())}

    # ------------------------------------------------------------------ prediction
    def predict_daily(self, product_daily, daily_context, products, origin, targets, model=None):
        """ความต้องการที่ราคาเต็มของ (product_id, date) แต่ละคู่ origin = reference_date (รู้ยอดถึงเมื่อวาน)"""
        if not targets:
            return pd.DataFrame(columns=["product_id", "date", "mu"])
        _, pivot = prepare_history(product_daily, self.clearance_products(products))
        ctx = prepare_context(daily_context)
        rows = build_rows(pivot, ctx, products, pd.Timestamp(origin), targets)
        rows["mu"] = self._predict_rows(rows, model if model is not None else self.model)
        return rows[["product_id", "date", "mu"]]

    # ------------------------------------------------------------------ save / load
    def save(self, folder=config.MODEL_DIR):
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / f"{self.version}.pkl", "wb") as f:
            pickle.dump(self, f)
        (folder / f"{self.version}_metrics.json").write_text(
            json.dumps(self.metrics, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        pd.Series(self.feature_importance, name="gain_pct").rename_axis("feature").to_csv(
            folder / f"{self.version}_feature_importance.csv")

    @staticmethod
    def load(folder=config.MODEL_DIR, version=config.MODEL_VERSION):
        with open(folder / f"{version}.pkl", "rb") as f:
            return pickle.load(f)
