# No-Waste-Bro API Server

Backend for No-Waste-Bro, built with **FastAPI** and using **Supabase** as the database.

## Requirements

- Python 3.10+ (developed on Python 3.13)
- A Supabase project with the tables and RPCs the server uses
  (`products`, `inventory_lots`, `sales_history`, `daily_sales_velocity`,
  `kitchen_capacity_daily`, `lot_risk_assessments`, `ai_recommended_tasks`, `recipes`,
  `recipe_ingredients`, `donation_partners`, RPCs `ensure_kitchen_days`,
  `book_kitchen_hours` and `release_kitchen_hours`)

## 1. Install libraries

Run every command from inside the `server/` folder.

```bash
cd server

# Create a virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt
```

> `.venv/` is not in `.gitignore` yet, so be careful not to commit it.

## 2. Configure the environment (.env)

Create `server/.env` from this template:

```env
# Supabase project URL (Project Settings > API)
SUPABASE_URL=https://<your-project-ref>.supabase.co

# Service role key (Project Settings > API > service_role)
# This key bypasses RLS. Never commit it or expose it to clients.
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>

# (optional) Pin the system's "today" for demos, format YYYY-MM-DD.
# If empty, the current date in Thailand time (Asia/Bangkok) is used.
DEMO_DATE=
```

| Variable | Required | Description |
| --- | --- | --- |
| `SUPABASE_URL` | ✅ | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Service role key used to connect to Supabase |
| `DEMO_DATE` | ❌ | Simulated date for demos (`YYYY-MM-DD`) |

- Values are loaded with `pydantic-settings` in `configs/config.py`. If a required variable is missing, the server fails on startup.
- `.env` is read from the **directory you run the command from**, so always start the server from inside `server/`.
- `*.env` is already ignored in `.gitignore`.

## 3. Run the server

### Development (auto-reload)

```bash
fastapi dev main.py
```

or

```bash
uvicorn main:app --reload
```

### Production

```bash
fastapi run main.py
```

or

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The server runs at `http://127.0.0.1:8000` by default.

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

## API Endpoints

All endpoints are under the `/api/v1` prefix. Interactive docs at `/docs` group them by the same tags.

### Products

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/products` | List all products |

### Inventory Lots

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/inventory-lots` | Create an inventory lot |
| `PATCH` | `/api/v1/inventory-lots/ai-status` | Set `ai_status` (`IDLE` / `PROCESSING` / `CHECKED`) for multiple lots |
| `PATCH` | `/api/v1/inventory-lots/{lot_id}` | Update an inventory lot |

### Kitchen

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/kitchen-capacity?days_ahead=1` | Kitchen capacity from today to +`days_ahead` days (0–30) |
| `POST` | `/api/v1/kitchen-bookings` | Book kitchen hours |

### AI

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/ai/scan-inputs` | Input data for the Risk Scanner & Forecaster (lots, sales history, sales velocity) |
| `GET` | `/api/v1/ai/optimize-inputs?run_id=&days_ahead=1` | Input data for the Optimizer (at-risk lots, product rules, recipes, kitchen capacity, donation partners) |

### Risk Assessments

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/risk-assessments` | Save Risk Scanner & Forecast results for one run (all rows or none) |

### Tasks

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/tasks` | Create AI-recommended tasks in bulk; books kitchen hours for `KITCHEN_REPURPOSE` tasks |

## AI Pipeline Flow

The AI agent calls the endpoints in this order for each scan run:

```
1. PATCH /inventory-lots/ai-status   {"ai_status": "PROCESSING"}   lock the lots being scanned
2. GET   /ai/scan-inputs                                          → Risk Scanner + Forecast
3. POST  /risk-assessments                                        ← returns run_id + assessment_id per lot
4. GET   /ai/optimize-inputs?run_id=<run_id>                      → Optimizer decides the action per lot
5. POST  /tasks                                                   ← LLM writes staff tasks (with assessment_id)
6. PATCH /inventory-lots/ai-status   {"ai_status": "CHECKED"}     mark the lots as done
```

| Step | Sends | Gets back |
| --- | --- | --- |
| `scan-inputs` | – | Inventory lots, full sales history, 7/30-day average daily sales |
| `risk-assessments` | One row per lot: days to expiry, forecast demand, predicted leftover, risk score (0–100), risk level. `run_id` is optional; the server creates one if omitted | `run_id` and the `assessment_id` of each lot |
| `optimize-inputs` | `run_id` (optional, latest run if omitted), `days_ahead` | `reference_date`, lots with risk `MEDIUM`/`HIGH`/`CRITICAL` (with lot data), product rules, active recipes with ingredients, kitchen capacity, active donation partners |
| `tasks` | A list of tasks | Created tasks and the kitchen hours that were booked |

`reference_date` is today in Thailand time, or `DEMO_DATE` if set in `.env`.

## Task Rules

`POST /api/v1/tasks` validates each task before anything is written.

| `action_type` | Required fields | Must be empty |
| --- | --- | --- |
| `MARKDOWN` | `discount_pct` (between 0 and 100, exclusive) | `batch_count` |
| `KITCHEN_REPURPOSE` | `target_recipe_id`, `batch_count`, `due_by` | `discount_pct` |
| `DONATE` | `target_partner_id` | `discount_pct`, `batch_count` |
| `DISCARD` | – | `discount_pct`, `batch_count` |

All tasks require `lot_id` and `action_quantity` (> 0). `priority` is 1–5 (default 3).

**Filled in by the server**

- `product_id` comes from the lot. If you send one that does not match the lot, the request is rejected.
- `original_price` defaults to the lot's `current_selling_price`.

**Kitchen booking (`KITCHEN_REPURPOSE`)**

- Hours are calculated by the server, not sent by the AI:
  `recipe.estimated_prep_time_mins × batch_count ÷ 60`, booked in the recipe's `department_id`.
- The booking date is the date of `due_by` in Thailand time (a `due_by` without a timezone is treated as Thailand time).
- Hours for tasks that use the same kitchen on the same day are added together and booked once.
- If any kitchen does not have enough hours, every booking made by this request is released and no task is created.
- If saving the tasks fails after booking, every booking is released.

## Error Responses

| Status | When |
| --- | --- |
| `400` | The database rejected the write (for example, a `target_partner_id` that does not exist), or kitchen hours exceed capacity on `POST /kitchen-bookings` |
| `404` | Lot not found on `PATCH /inventory-lots/{lot_id}`, none of the `lot_ids` found on `PATCH /inventory-lots/ai-status`, or unknown `department_id` on `POST /kitchen-bookings` |
| `409` | Duplicate `lot_id` in the same `run_id` on `POST /risk-assessments`, or a kitchen is full on `POST /tasks` |
| `422` | Request body fails validation: missing or invalid fields, task rule violations, unknown `lot_id`, `product_id` mismatch, or an inactive / unknown recipe |

`PATCH /inventory-lots/ai-status` returns lot IDs that do not exist in `not_found` instead of failing, as long as at least one lot was updated.

## Example Requests

> **Warning:** these requests write real data to Supabase, including risk assessments, tasks, lot status, and **booked kitchen hours**. Release any test bookings afterwards with the `release_kitchen_hours` RPC.

```bash
B=http://127.0.0.1:8000/api/v1

# 1) Save scan results → keep run_id and assessment_id
curl -X POST $B/risk-assessments -H "Content-Type: application/json" -d '{
  "model_version": "v1",
  "assessments": [{
    "lot_id": "LOT-000001", "days_to_expiry": 0, "quantity_at_assessment": 85,
    "forecast_daily_demand": 30.8, "predicted_units_sold_before_expiry": 30.8,
    "predicted_leftover_units": 54.2, "sell_through_probability": 0.36,
    "risk_score": 82.5, "risk_level": "CRITICAL"
  }]
}'

# 2) Optimizer input for the latest run
curl "$B/ai/optimize-inputs"

# 3) Create tasks: one markdown + one kitchen task (books BAKERY_DEPT for 0.83 h)
curl -X POST $B/tasks -H "Content-Type: application/json" -d '{"tasks": [
  {"lot_id": "LOT-000001", "action_type": "MARKDOWN", "action_quantity": 30,
   "discount_pct": 30, "priority": 2},
  {"lot_id": "LOT-000001", "action_type": "KITCHEN_REPURPOSE", "action_quantity": 2,
   "target_recipe_id": "RCP-006", "batch_count": 1, "priority": 1,
   "due_by": "2026-10-14T17:00:00+07:00"}
]}'

# 4) Mark lots as checked
curl -X PATCH $B/inventory-lots/ai-status -H "Content-Type: application/json" \
  -d '{"lot_ids": ["LOT-000001"], "ai_status": "CHECKED"}'
```

## Project Structure

```
server/
├── main.py                     # FastAPI app and router registration (/api/v1 prefix)
├── configs/
│   └── config.py               # Environment loading (pydantic-settings)
├── core/
│   └── dates.py                # Thailand timezone and today_bkk() (supports DEMO_DATE)
├── db/
│   ├── supabase.py             # Supabase client (service role)
│   └── helpers.py              # fetch_all(): paginates past the 1,000-row limit
├── routers/                    # API endpoints, one file per tag
│   ├── products.py
│   ├── inventory_lots.py
│   ├── kitchen.py
│   ├── ai.py                   # scan-inputs, optimize-inputs
│   ├── risk_assessments.py
│   └── tasks.py
├── schemas/                    # Pydantic request models
│   ├── enums.py                # ActionType, RiskLevel, LotAIStatus (match DB enums)
│   ├── inventory_lot.py
│   ├── kitchen.py
│   ├── risk_assessment.py
│   └── task.py                 # Task rules per action_type
├── services/                   # Business logic shared by routers
│   ├── kitchen.py              # department_exists, book_hours, release_hours
│   └── tasks.py                # Task creation with kitchen booking and rollback
└── requirements.txt
```

## Known Limitations

- `DONATE` tasks cannot be created until the `donation_partners` table has data.
- There are no endpoints yet for staff to accept, complete, or reject tasks, so booked kitchen hours are only released automatically when task creation fails.
