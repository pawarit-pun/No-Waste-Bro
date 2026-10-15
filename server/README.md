# No-Waste-Bro API Server

Backend for No-Waste-Bro, built with **FastAPI** and using **Supabase** as the database.

## Requirements

- Python 3.10+ (developed on Python 3.13)
- A Supabase project with the tables and RPCs the server uses
  (`products`, `inventory_lots`, `sales_history`, `daily_sales_velocity`,
  `kitchen_capacity_daily`, `lot_risk_assessments`, `optimization_decisions`,
  `ai_recommended_tasks`, `recipes`, `recipe_ingredients`, `donation_partners`, `staff`,
  view `optimization_decisions_status`, RPCs `ensure_kitchen_days`,
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

All endpoints are under the `/api/v1` prefix. Interactive docs at `/docs` group them by the same tags (descriptions there are in Thai for the AI team).

### Staff

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/staff?role=STAFF` | Active staff for the user-picker screen. `role` is `STAFF` (default, mobile app) or `MANAGER` (web dashboard). There is no login |

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
| `GET` | `/api/v1/ai/scan-inputs` | Input data for the Risk Scanner & Forecaster: lots with `ai_status = IDLE`, plus sales history and sales velocity for their products |
| `GET` | `/api/v1/ai/optimize-inputs?run_id=&days_ahead=1` | Input data for the Optimizer (at-risk lots, product rules, recipes, kitchen capacity, donation partners) |

### Risk Assessments

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/risk-assessments` | Save Risk Scanner & Forecast results for one run (all rows or none) |

### Optimization Decisions

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/optimization-decisions` | Save the Optimizer's decisions, including every number a task will use (all rows or none) |
| `GET` | `/api/v1/optimization-decisions?run_id=&status=PENDING` | Decisions with the context the LLM needs to write staff instructions |

### Tasks

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/tasks` | Turn decisions into staff tasks in bulk; assigns each task to a staff member and books kitchen hours for `KITCHEN_REPURPOSE` |
| `GET` | `/api/v1/tasks?staff_id=&status=` | Task queue for one staff member (mobile), or all tasks without `staff_id` (dashboard). Default status: `PENDING` + `IN_PROGRESS` |
| `GET` | `/api/v1/tasks/{task_id}` | Task detail with product, lot, assigned staff, assessment, recipe, and partner |
| `POST` | `/api/v1/tasks/{task_id}/accept` | Assigned staff starts the task: `PENDING` → `IN_PROGRESS` |
| `POST` | `/api/v1/tasks/{task_id}/reject` | Assigned staff rejects the task with a reason: → `REJECTED`; releases kitchen hours for kitchen tasks |
| `POST` | `/api/v1/tasks/{task_id}/complete` | Assigned staff finishes the task: `IN_PROGRESS` → `COMPLETED`, and stock is updated (see [Task Lifecycle](#task-lifecycle)) |

## AI Pipeline Flow

**Principle: the Optimizer owns the numbers, the LLM owns the text.** Every number on a task (discount, quantity, recipe, batch count, partner, due time) is copied from an Optimizer decision, so the LLM cannot invent or change them.

```
1. GET   /ai/scan-inputs                                          → Risk Scanner + Forecast (IDLE lots only)
2. PATCH /inventory-lots/ai-status   {"ai_status": "PROCESSING"}   lock the lots returned by step 1
3. POST  /risk-assessments                                        ← run_id + assessment_id per lot
4. GET   /ai/optimize-inputs?run_id=<run_id>                      → Optimizer decides the action per lot
5. POST  /optimization-decisions                                  ← decision_id per decision
6. GET   /optimization-decisions?status=PENDING                   → LLM (RAG) writes instructions
7. POST  /tasks                                                   ← decision_id + text + priority only
8. PATCH /inventory-lots/ai-status   {"ai_status": "CHECKED"}     mark the lots as done
```

| Step | Caller | Sends | Gets back |
| --- | --- | --- | --- |
| `scan-inputs` | Risk Scanner + Forecast | – | Lots with `ai_status = IDLE` (sorted by expiry), plus sales history and 7/30-day average daily sales for those lots' products |
| `risk-assessments` | Risk Scanner | One row per lot: days to expiry, forecast demand, predicted leftover, risk score (0–100), risk level. `run_id` is optional | `run_id` and the `assessment_id` of each lot |
| `optimize-inputs` | Optimizer | `run_id` (optional, latest run if omitted), `days_ahead` | `reference_date`, lots with risk `MEDIUM`/`HIGH`/`CRITICAL`, product rules, active recipes with ingredients, kitchen capacity, active donation partners, and `ingredient_stock` (usable, unexpired stock of every recipe ingredient, earliest expiry first) |
| `optimization-decisions` (POST) | Optimizer | One or more decisions per assessment, with all numbers | `decision_id` of each decision |
| `optimization-decisions` (GET) | LLM | `run_id` (optional, latest), `status=PENDING` | Decisions with assessment, lot (incl. shelf location), product, recipe, and partner context |
| `tasks` | LLM | `decision_id`, `priority`, `ai_reasoning`, `staff_instructions` | Created tasks and the kitchen hours that were booked |

Each lot is scanned once: `scan-inputs` only returns `IDLE` lots, and lots never return to `IDLE` once they are `PROCESSING` or `CHECKED`. Lock the returned lots right after step 1.

`reference_date` is today in Thailand time, or `DEMO_DATE` if set in `.env`.

A decision's `status` is computed by the `optimization_decisions_status` view: `PENDING` until a task is created from it, then `TASK_CREATED`. Each decision can become exactly one task (enforced by a unique index).

## Decision Rules

`POST /api/v1/optimization-decisions` validates each decision before anything is written.

| `action_type` | Required fields | Must be empty |
| --- | --- | --- |
| `MARKDOWN` | `discount_pct` (between 0 and 100, exclusive) | `batch_count` |
| `KITCHEN_REPURPOSE` | `target_recipe_id`, `batch_count`, `due_by` | `discount_pct`, `new_recommended_price` |
| `DONATE` | `target_partner_id` | `discount_pct`, `new_recommended_price`, `batch_count` |
| `DISCARD` | – | `discount_pct`, `new_recommended_price`, `batch_count` |

All decisions require `assessment_id` and `action_quantity` (> 0). The server fills in `run_id` and `lot_id` from the assessment.

**Checked against real data**

- The product must allow the action (`allow_markdown`, `allow_kitchen_repurposing`, `allow_donation`).
- The total `action_quantity` per lot in one request cannot exceed the lot's `current_quantity`.
- `MARKDOWN`: if `new_recommended_price` is omitted, the server sets it to `current_selling_price × (1 − discount_pct / 100)`. The price cannot be below the product's `min_allowed_price`.
- `KITCHEN_REPURPOSE`: the recipe must be active, and the lot's product must be one of its ingredients.
- `DONATE`: the partner must be active, accept the product's category, and the lot must have at least `min_days_before_expiry` days left.

## Task Rules

`POST /api/v1/tasks` accepts only `decision_id` (required), `priority` (1–5, default 3), `ai_reasoning`, and `staff_instructions`. Any other field is ignored.

**Copied by the server**

- From the decision: `lot_id`, `assessment_id`, `action_type`, `action_quantity`, `discount_pct`, `new_recommended_price`, `target_recipe_id`, `batch_count`, `target_partner_id`, `due_by`, `expected_profit_impact`.
- From the lot: `product_id`, and `original_price` (the current selling price).

**Automatic assignment**

- Each task is assigned when it is created, in the same insert, so the first Realtime event already has `assigned_staff_id`.
- Candidates are active `STAFF` whose `responsible_categories` include the product's category.
- With several candidates, the one with the fewest open tasks (`PENDING` + `IN_PROGRESS`) wins; ties go to the lowest `staff_id`. Tasks assigned earlier in the same request count toward the workload.
- If nobody covers the category, `assigned_staff_id` is `null` and the manager handles it.

**Kitchen booking (`KITCHEN_REPURPOSE`)**

- Hours: `recipe.estimated_prep_time_mins × batch_count ÷ 60`, booked in the recipe's `department_id`.
- The booking date is the date of the decision's `due_by` in Thailand time.
- Hours for tasks that use the same kitchen on the same day are added together and booked once.
- Kitchen hours are booked when the task is created, not when the decision is saved.
- If any kitchen is full, or saving the tasks fails, every booking made by this request is released and no task is created.

## Task Lifecycle

```
PENDING ──accept──▶ IN_PROGRESS ──complete──▶ COMPLETED
   │                    │
   └──────reject────────┴──────────────────▶ REJECTED
```

Every action sends `staff_id` in the body (there is no login), and only the assigned staff member may act. A task must be accepted before it can be completed.

**Reject** requires `rejection_reason`. Stock does not change. For `KITCHEN_REPURPOSE`, the kitchen hours booked at creation are released (recomputed with the same rule used for booking).

**Complete** takes `actual_quantity_handled` (0 to `action_quantity`) and updates stock in one database transaction (`complete_task` function). If any step fails, nothing changes.

| `action_type` | Stock effect |
| --- | --- |
| `MARKDOWN` | The task lot loses `actual_quantity_handled` units, which become a **new lot** at `new_recommended_price` (same product, dates, cost, and location; `ai_status = CHECKED`) |
| `KITCHEN_REPURPOSE` | The task lot loses `actual_quantity_handled` units; **every other recipe ingredient** is deducted; a **new output lot** is created |
| `DONATE` / `DISCARD` | The task lot loses `actual_quantity_handled` units |

Kitchen details:

- Other ingredients need `required_quantity × batch_count ÷ net content`, **rounded up** to whole units. They are taken from unexpired lots (as of the reference date), earliest expiry first, across several lots if needed. If any ingredient is short, the request fails with `422` and names the missing products.
- The output lot holds `output_quantity × batch_count` units, expires on the reference date + `shelf_life_days`, sells at `regular_price`, costs `base_cost`, sits at the kitchen (`location_aisle` = department), and starts as `IDLE` so the next scan picks it up.
- The booked kitchen hours count as used.

Every new lot has `source_task_id` pointing to the task. The response's `effects` lists each changed lot (before → after) and each new lot.

## Realtime for the Mobile App

`ai_recommended_tasks` is in the `supabase_realtime` publication, and the `anon` role can read it (prototype, no login). The app subscribes to its own tasks and refetches from the API when an event arrives:

```js
supabase.channel('my-tasks')
  .on('postgres_changes',
      { event: '*', schema: 'public', table: 'ai_recommended_tasks',
        filter: 'assigned_staff_id=eq.STF-003' },
      () => refetchTasks())          // GET /api/v1/tasks?staff_id=STF-003
  .subscribe()
```

Use the event only as a signal; the API applies the queue's filtering and ordering.

## Error Responses

| Status | When |
| --- | --- |
| `400` | The database rejected the write, or kitchen hours exceed capacity on `POST /kitchen-bookings` |
| `403` | On task actions, `staff_id` is not the assigned staff member |
| `404` | Unknown `staff_id` or `task_id` on task routes, lot not found on `PATCH /inventory-lots/{lot_id}`, none of the `lot_ids` found on `PATCH /inventory-lots/ai-status`, or unknown `department_id` on `POST /kitchen-bookings` |
| `409` | Duplicate `lot_id` in the same `run_id` on `POST /risk-assessments`; on `POST /tasks`, a kitchen is full or a decision already has a task; on task actions, the task is not in the required status |
| `422` | Request body fails validation, or a decision fails the checks in [Decision Rules](#decision-rules); on `POST /tasks`, an unknown or repeated `decision_id`; on `complete`, a quantity out of range, not enough stock in the lot, or missing recipe ingredients |

`PATCH /inventory-lots/ai-status` returns lot IDs that do not exist in `not_found` instead of failing, as long as at least one lot was updated.

## Example Requests

> **Warning:** these requests write real data to Supabase, including risk assessments, decisions, tasks, lot status, and **booked kitchen hours**. Release any test bookings afterwards with the `release_kitchen_hours` RPC.

```bash
B=http://127.0.0.1:8000/api/v1

# 1) Save scan results → keep assessment_id
curl -X POST $B/risk-assessments -H "Content-Type: application/json" -d '{
  "model_version": "risk-v1",
  "assessments": [{
    "lot_id": "LOT-000001", "days_to_expiry": 0, "quantity_at_assessment": 85,
    "forecast_daily_demand": 30.8, "predicted_units_sold_before_expiry": 30.8,
    "predicted_leftover_units": 54.2, "sell_through_probability": 0.36,
    "risk_score": 82.5, "risk_level": "CRITICAL"
  }]
}'

# 2) Optimizer input for the latest run
curl "$B/ai/optimize-inputs"

# 3) Save the Optimizer's decisions → keep decision_id
curl -X POST $B/optimization-decisions -H "Content-Type: application/json" -d '{
  "optimizer_version": "opt-v1",
  "decisions": [
    {"assessment_id": "<assessment_id>", "action_type": "MARKDOWN",
     "action_quantity": 30, "discount_pct": 30, "expected_profit_impact": -300},
    {"assessment_id": "<assessment_id>", "action_type": "KITCHEN_REPURPOSE",
     "action_quantity": 2, "target_recipe_id": "RCP-006", "batch_count": 1,
     "due_by": "2026-10-14T17:00:00+07:00"}
  ]
}'

# 4) Decisions waiting for the LLM
curl "$B/optimization-decisions?status=PENDING"

# 5) Create tasks (books BAKERY_DEPT for 0.83 h)
curl -X POST $B/tasks -H "Content-Type: application/json" -d '{"tasks": [
  {"decision_id": "<markdown decision_id>", "priority": 2,
   "staff_instructions": "Put 30% off labels on 30 bottles at CHILL-A / A-01"},
  {"decision_id": "<kitchen decision_id>", "priority": 1,
   "staff_instructions": "Bring 2 bottles from CHILL-A / A-01 to the bakery before 17:00"}
]}'

# 6) Mark lots as checked
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
│   ├── dates.py                # Thailand timezone and today_bkk() (supports DEMO_DATE)
│   └── openapi.py              # Swagger page text and tag descriptions (Thai)
├── db/
│   ├── supabase.py             # Supabase client (service role)
│   └── helpers.py              # fetch_all() past the 1,000-row limit (with filter/order), fetch_by_ids()
├── routers/                    # API endpoints, one file per tag
│   ├── products.py
│   ├── inventory_lots.py
│   ├── kitchen.py
│   ├── ai.py                   # scan-inputs, optimize-inputs
│   ├── risk_assessments.py
│   ├── optimization_decisions.py
│   ├── tasks.py
│   └── staff.py
├── schemas/                    # Pydantic request and response models
│   ├── enums.py                # ActionType, RiskLevel, LotAIStatus, DecisionStatus, StaffRole, TaskStatus (match DB)
│   ├── inventory_lot.py
│   ├── kitchen.py
│   ├── risk_assessment.py
│   ├── decision.py             # Decision rules per action_type
│   ├── task.py                 # Task creation (decision_id + text) and accept / reject / complete bodies
│   └── responses.py            # Response shapes shown in Swagger
├── services/                   # Business logic shared by routers
│   ├── kitchen.py              # department_exists, book_hours, release_hours
│   ├── decisions.py            # Decision checks against real data, listing with context
│   ├── tasks.py                # Task creation (auto-assign, kitchen booking, rollback), task queue and detail
│   └── task_actions.py         # Accept, reject (releases kitchen hours), complete (calls the complete_task DB function)
└── requirements.txt
```

## Known Limitations

- `DONATE` decisions cannot be created until the `donation_partners` table has data.
- Lots are scanned only once by design (prototype): nothing resets `ai_status` back to `IDLE`.
- When a kitchen task is rejected, released hours are recomputed per task and rounded to 0.01 h, so a booking that summed several tasks can leave up to 0.01 h booked per task.
- The `anon` read policy on `ai_recommended_tasks` lets anyone with the anon key read tasks. Acceptable for a prototype without login.
