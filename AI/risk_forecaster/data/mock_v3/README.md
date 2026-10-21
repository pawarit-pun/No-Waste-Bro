# Mock data v3 (not loaded into Supabase yet)

Made by `server/scripts/forecast_data/simulate.py` (v3), copied here by `python tools/build_dataset.py ../server/scripts/forecast_data/data data/mock_v3`.
Columns match the Supabase tables exactly:
`product_daily.csv` = `product_daily`, `daily_context.csv` = `daily_context`, `inventory_lots_demo.csv` = `inventory_lots`.
`training_dataset.csv` = the three joined like `scripts.export_training_data` does (`product_daily` + `daily_context` + `products`).

Two extra files exist only for the AI (no Supabase table):

| File | 1 row = | Used for |
| --- | --- | --- |
| `lot_daily.csv` | lot x day on the shelf at opening (08:00) | `calibrate_risk.py` re-scans every past day |
| `lot_outcomes.csv` | lot: sold / damaged / **expired** units at the end | actual risk score = expired / quantity on that day x 100 |

Supabase still holds v1 until these files are loaded. Until then, `GET /ai/scan-inputs` returns v1 data.

## What changed from v2

| | v2 | v3 | Benchmark |
| --- | --- | --- | --- |
| Waste by department | bakery 2.4, seafood 2.4, meat 0.1, RTE 23% | bakery 6.3, seafood 8.0, meat 4.2, produce 2.8, dairy 1.8, RTE 20.3% | FMI shrink: bakery 8.5, seafood 7.6, meat 5.7, deli 8.7% |
| Stock-outs | 0.5-4.5% (too good) | 3.1-8.3% (all 10.3%, RTE 19.8%) | about 8% |
| Markdown tests | 12% of days, from 16:00 | about 6% of days, **full day** for 1-3 days, stock topped up before the test | needed to measure "discount from opening until expiry" |
| RTE | 1 production run | 3 runs (11:00 / 14:00 / 17:00), evening clearance 50 / 30 / 20% | |
| Damage | none | produce 3%, meat 2.5%, bakery / seafood 2%, dairy 1% | |
| Per-lot log | none | `lot_daily.csv`, `lot_outcomes.csv` | |
| Demo lots | 13 | 13 (same ids), levels from the real pipeline: CRITICAL 7, HIGH 1, LOW 5 | |

**v4 (after `bash server/scripts/reset_mock_lots.sh`):** 27 demo lots (LOT-000001..013 unchanged + 014..027:
several lots per product, real delivery days and case packs, one over-delivery). Same generator and seed for history.
Scanner check: CRITICAL 4 / HIGH 9 / MEDIUM 5 / LOW 9, 13 lots to the Optimizer. Details: `server/scripts/forecast_data/README.md`.

## Checks

```bat
cd AI
python data_checks\validate_mock_data.py
```

All 5 pass: stock balances, waste / stock-out within targets, markdown effect measurable
(x1.17 / x1.11 / x1.41 measured vs x1.12 / x1.20 / x1.35 set), LightGBM beats same-dow (25.39% vs 27.81%),
demo lots have CRITICAL / HIGH / LOW.

## Still open

1. **History is 96 days.** `simulate.py` extends to 365 days once `server/scripts/forecast_data/data/weather_archive.json`
   and `weather_forecast.json` cover the year (Open-Meteo is blocked in the cloud session). Then:
   `python simulate.py` → `python tools/build_dataset.py ../server/scripts/forecast_data/data data/mock_v3` → `train_forecaster.py` → `calibrate_risk.py` → `validate_mock_data.py`.
2. **Load into Supabase** (`product_daily`, `daily_context`, `inventory_lots` incl. `LOT-000011`..`013`), then
   `select demo_snapshot();` and `select demo_reset('<demo day>');` Planned once, after the 1-year data.
3. RTE waste stays above the deli benchmark (small volumes, same-day expiry); treat RTE results with care.
