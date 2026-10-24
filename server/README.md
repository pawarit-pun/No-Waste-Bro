# No-Waste-Bro API Server

Backend for No-Waste-Bro, built with **FastAPI** and using **Supabase** as the database.

## Requirements

- Python 3.10+ (developed on Python 3.13)
- A Supabase project with the tables and RPCs the server uses
  (`products`, `inventory_lots`, `product_daily`, `daily_context`, `daily_sales_velocity`,
  `kitchen_capacity_daily`, `lot_risk_assessments`, `forecast_runs`, `lot_shelf_forecasts`,
  `recipe_demand_forecasts`, `optimization_decisions`,
  `pending_tasks`, `ai_recommended_tasks`, `recipes`, `recipe_ingredients`, `donation_partners`, `staff`,
  view `optimization_decisions_status`, RPCs `ensure_kitchen_days`,
  `book_kitchen_hours`, `release_kitchen_hours` and `save_risk_run`; the forecast tables and
  `save_risk_run` are created by `scripts/forecast_tables.sql`)

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

# (optional) Origins allowed to call the API from a browser, comma-separated.
# Defaults to * (any origin). Example: http://localhost:3000,http://localhost:5173
CORS_ORIGINS=*
```

| Variable | Required | Description |
| --- | --- | --- |
| `SUPABASE_URL` | ✅ | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Service role key used to connect to Supabase |
| `DEMO_DATE` | ❌ | Simulated date for demos (`YYYY-MM-DD`) |
| `CORS_ORIGINS` | ❌ | Browser origins allowed to call the API, comma-separated. Default `*` (any origin). Set specific origins once the web dashboard has a fixed URL |

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

## 4. Deploy to AWS Lambda + API Gateway

The whole FastAPI app runs in **one Lambda function**. API Gateway (HTTP API) forwards every path
(`ANY /{proxy+}`) to it, and [Mangum](https://pypi.org/project/mangum/) (`handler` in `main.py`)
turns the Lambda event into a normal request for FastAPI, so the routes need no changes.

```
client → API Gateway (HTTP API) → Lambda [ Mangum → FastAPI → routers / services ] → Supabase
```

| File | Purpose |
| --- | --- |
| `template.yaml` | AWS SAM template: Lambda (python3.13, arm64, 512 MB, 29 s), HTTP API, log group |
| `samconfig.toml` | Deploy defaults: stack `no-waste-bro-api`, region `ap-southeast-1` |
| `requirements-lambda.txt` | Runtime libraries packaged into the Lambda |
| `scripts/build_lambda.sh` | Builds `build/`: Linux (arm64) libraries + app code only |

### Prerequisites (one time)

- AWS CLI v2 with credentials (`aws configure` or `aws configure sso`)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- Docker: only for building the AI pipeline worker image (`AI/pipeline/build_worker.sh`), not for the API itself

### Build and deploy

```bash
cd server
# Reads the service role key from .env so it is never typed or saved in samconfig.toml
# WorkerImageUri = image of the AI pipeline worker, written by AI/pipeline/build_worker.sh (run it once first)
# && stops at the first failing step, so a failed build is never deployed
./scripts/build_lambda.sh && sam deploy --parameter-overrides \
  SupabaseServiceRoleKey="$(grep '^SUPABASE_SERVICE_ROLE_KEY=' .env | cut -d= -f2-)" \
  WorkerImageUri="$(cat ../AI/pipeline/.last_image_uri)"
```

`samconfig.toml` sets `image_repositories` (the ECR repository of `PipelineWorkerFunction` and `ManagerAgentFunction`, both use the same image). SAM requires it for any container-image function, even though the image itself comes from `WorkerImageUri`. If the repository or account changes, update that line.

Optional parameters (add them to `--parameter-overrides`; any parameter left out goes back to its default on that deploy):

| Parameter | Default | Env var in Lambda |
| --- | --- | --- |
| `SupabaseUrl` | `https://vvhwqamejfaouvfmkhps.supabase.co` | `SUPABASE_URL` |
| `SupabaseServiceRoleKey` | (required) | `SUPABASE_SERVICE_ROLE_KEY` |
| `DemoDate` | empty (today in Bangkok) | `DEMO_DATE` |
| `CorsOrigins` | `*` | `CORS_ORIGINS` |
| `WorkerImageUri` | (required) | image of `PipelineWorkerFunction` (see [AI Pipeline](#ai-pipeline-one-call)) |
| `WorkerApiBaseUrl` | the current AWS API URL | `API_BASE_URL` of the worker |
| `BedrockRegion` / `BedrockKnowledgeBaseId` | `us-east-1` / `N0NJ2UIEIU` | worker's Bedrock settings |

Example for a demo day: `sam deploy --parameter-overrides SupabaseServiceRoleKey="..." DemoDate=2026-10-20`

The outputs show the URLs: `ApiBaseUrl` (for the mobile app) and `DocsUrl` (Swagger). Show them again with
`sam list stack-outputs`.

### Everyday use

| Task | Command |
| --- | --- |
| Deploy code changes | `./scripts/build_lambda.sh` then the `sam deploy` command above |
| Tail logs | `sam logs --tail` |
| Point the mobile app at AWS | `flutter run --dart-define=API_BASE_URL=<ApiBaseUrl>` |
| Reset demo data | `python -m scripts.demo reset-seed` (still runs locally, talks to Supabase directly) |
| Remove everything from AWS | `sam delete` |

Notes:
- **The API URL stays the same across `sam deploy`.** `sam delete` (or renaming the stack / the API resource) creates a new API with a new URL, so only delete when you are done with it.
- Never run `sam deploy --guided` and type the key: SAM would save it into `samconfig.toml`.
- Do not edit the function or its env vars in the AWS console; the next `sam deploy` overwrites them.
- `build/` contains only `main.py`, `configs/`, `core/`, `db/`, `routers/`, `schemas/`, `services/` and the libraries. `.env`, `.venv/` and `scripts/` are never packaged.
- The first request after the function has been idle is slower (cold start, about 1–3 s). Call the API once before a live demo.
- API Gateway cuts requests at 30 seconds, so long AI / LLM work should run outside these routes.

## AI Pipeline (one call)

`POST /api/v1/ai/pipeline-runs` runs the whole AI flow in order. The API cannot wait for it (API Gateway stops at 30 s and the three steps take minutes), so it starts a separate Lambda, `PipelineWorkerFunction` (container image built from `AI/pipeline/`), and answers at once.

```
POST /ai/pipeline-runs ─► row in pipeline_runs (QUEUED) ─► invoke worker (async) ─► 202
worker: SCAN (risk_forecaster/run_scan.py) ─► OPTIMIZE (food_waste_optimizer/run_optimize.py) ─► TASKS (llm-task-agent/main.py)
        each step PATCHes /ai/pipeline-runs/{id}: RUNNING → SUCCEEDED / FAILED
```

| Field | Meaning |
| --- | --- |
| `status` | `QUEUED` → `RUNNING` → `SUCCEEDED` / `FAILED` |
| `current_step` | `SCAN` / `OPTIMIZE` / `TASKS` |
| `run_id` | Scan run, shared by assessments, decisions and tasks |
| `at_risk_lots` / `decisions_created` / `tasks_created` / `failed_batches` | Result of each step (`tasks_created` = plans sent to the review queue; staff get tasks only after a manager approves them) |
| `message` | Why a run ended early (no IDLE lots, no HIGH / CRITICAL lots, 0 decisions) |
| `error` / `steps` | What failed, with the last lines of each step's output |

Rules: one run at a time (`409` otherwise); a run stuck in `QUEUED` / `RUNNING` for 20 minutes is marked `FAILED` on the next start; the worker never retries automatically (a retry would scan and post twice). Running locally with `fastapi dev`, `POST /ai/pipeline-runs` answers `503`; use `python AI/pipeline/worker.py` instead. Build and debug steps: `AI/pipeline/README.md`.

## Manager Agent (chat)

`POST /api/v1/agent/ask` answers the manager's questions in Thai from the web dashboard. It is **read-only**: it never approves, creates tasks or changes prices. The API waits for a separate Lambda, `ManagerAgentFunction` (same container image as the pipeline worker, command `manager_agent.handler.lambda_handler`, code in `AI/manager_agent/`).

```
dashboard ─► POST /agent/ask ─► ManagerAgentFunction (sync, ≤ 25 s)
                                   ├─ Bedrock Converse + tools (Nova Lite, fallback Qwen3 Next)
                                   ├─ tools read this API (GET only) / run the Optimizer dry-run (what-if)
                                   └─ guard: numbers, dates, times, lot IDs must come from tool results
```

Tools: store snapshot, at-risk lots, one lot, tasks, Optimizer plan summary, explain a lot's decision, what-if (no markdown / force a discount level / partner unavailable / kitchen hours / demand × 0.5–1.5), SOP search (Knowledge Base) and `propose_action` (a card the manager confirms, see below). Answers that fail the guard are revised once, then retried on the fallback model, then replaced by a short template with the data cards (`model_used = TEMPLATE`). Locally (`fastapi dev`) the route answers `503`; run `python -m manager_agent "คำถาม"` from the `AI` folder instead.

### Phase 2: notifications and proposals

The agent never changes store data by itself. It writes **notifications** (bell in the dashboard) and **proposals**; the server carries out a proposal only when a manager presses confirm (`POST /agent/proposals/{id}/execute`), checking the current data again first.

| Trigger | Sent by | Agent does |
| --- | --- | --- |
| `TASK_REJECTED` | `POST /tasks/{id}/reject` | notify; propose `RUN_PIPELINE` if the lot is `IDLE` again, or `BLOCK_KITCHEN` (+ re-plan) when a kitchen task was rejected for a kitchen reason |
| `KITCHEN_FULL` | `POST /pending-tasks/approve` (409 kitchen) | notify with a what-if of the plan without that kitchen today |
| `PIPELINE_FAILED` | `PATCH /ai/pipeline-runs/{id}` to `FAILED` (and stale runs) | notify; propose `RELEASE_LOTS` for stuck lots, otherwise `RUN_PIPELINE` |
| `WATCH` | EventBridge every hour 07:00–22:00, or `POST /agent/watch` (Run demo page) | overdue tasks, plans near / past their review deadline, lots stuck in `PROCESSING` |

| Proposal | When confirmed |
| --- | --- |
| `RUN_PIPELINE` | starts a pipeline run (`409` while one is running) |
| `RELEASE_LOTS` | `release_lot_if_idle` per lot (only lots with no open task and no waiting decision) |
| `BLOCK_KITCHEN` | books the kitchen's remaining hours for that day, then optionally starts a pipeline run |

Events are sent async (`InvocationType=Event`); a failed send never breaks the original request. Each notification has a `dedupe_key`, so the same event or the next hourly check does not notify twice. Proposals expire at the end of the system day. Tables: `agent_runs` (audit of every chat / event / watch run), `agent_notifications`, `agent_proposals` (`scripts/agent_tables.sql`, also updates `demo_reset()` to clear notifications and proposals).

### Phase 3: daily routine

| When | Trigger | Agent does |
| --- | --- | --- |
| 07:30 | EventBridge `MORNING_RUN` | starts the day's pipeline run itself if lots are `IDLE` and no run is active (plans still go to the review queue). `AgentAutoRun=false` = notify with a `RUN_PIPELINE` proposal instead |
| pipeline `SUCCEEDED` | `PATCH /ai/pipeline-runs/{id}` sends `PIPELINE_SUCCEEDED` | **Morning brief**: decisions per action (units, kg), rescued / recycled / disposal kg, expected net profit vs the "regular price then landfill" baseline (Optimizer dry-run of the same scan), kitchen hours, plans waiting; anomalies: stuck lots, disposal > 1.5x the 7-report average, waiting kitchen plans over the hours left, plan worse than baseline, plans due within 60 min |
| 21:30 | EventBridge `EVENING_SUMMARY` | **Evening summary**: tasks completed / rejected / open / overdue per action, units and kg really handled, expected profit of completed tasks, compared with the Morning brief |

Reports are saved in `daily_reports` (one row per day and kind, re-runs overwrite; `scripts/daily_reports.sql`) and shown on the dashboard Overview page. `POST /agent/daily/{morning|evening}` makes one now (Run demo page). Profit figures are the Optimizer's estimates; there is no POS data yet.

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
| `GET` | `/api/v1/inventory-lots?include_empty=false` | Current lots for the dashboard Inventory page, earliest expiry first, with product, `days_left` (vs. the system date), origin (supplier / markdown split / kitchen output), latest risk assessment, waiting plans and open tasks |
| `POST` | `/api/v1/inventory-lots` | Create an inventory lot |
| `PATCH` | `/api/v1/inventory-lots/ai-status` | Set `ai_status` (`IDLE` / `PROCESSING` / `CHECKED`) for multiple lots |
| `PATCH` | `/api/v1/inventory-lots/{lot_id}` | Update an inventory lot |

### Kitchen

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/kitchen-capacity?days_ahead=1` | Kitchen capacity from today to +`days_ahead` days (0–30) |
| `GET` | `/api/v1/kitchen-overview?days_ahead=1` | Dashboard Kitchen page: departments with daily capacity, kitchen jobs (staff tasks + plans waiting for approval, with hours computed like the booking) and menu demand of the latest forecast run (read-only) |
| `POST` | `/api/v1/kitchen-bookings` | Book kitchen hours |

### AI Pipeline

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/ai/pipeline-runs` | Start Risk Scanner → Optimizer → LLM Task Agent on the worker. Returns **202** right away with the run (`QUEUED`). Body `{"stop_after": "SCAN" \| "OPTIMIZE" \| "TASKS"}` (default `TASKS`) |
| `GET` | `/api/v1/ai/pipeline-runs?limit=10` | Latest runs |
| `GET` | `/api/v1/ai/pipeline-runs/{pipeline_run_id}` | Status of one run (also on Supabase Realtime, table `pipeline_runs`) |
| `PATCH` | `/api/v1/ai/pipeline-runs/{pipeline_run_id}` | Internal: the worker reports its progress |

### Manager Agent

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/agent/ask` | Ask the AI assistant (Thai). Body `{"question", "history": [{"role", "text"}], "context": {"page", "lot_id"}}`. Returns `answer`, `model_used`, `tool_calls`, `artifacts` (cards), `warnings`, `latency_ms`. `503` when `AGENT_FUNCTION_NAME` is empty, `504` when the agent runs out of time |
| `POST` | `/api/v1/agent/warmup` | Wake the agent Lambda (async, no wait). Call it when the chat panel opens |
| `POST` | `/api/v1/agent/daily/{morning\|evening}` | Make the Morning brief (latest succeeded pipeline run, no new run) or Evening summary now (async) |
| `GET` | `/api/v1/daily-reports?days=7` | Daily reports (Morning brief / Evening summary) newest first, `metrics` + `anomalies` + `message`. Realtime: table `daily_reports` |
| `POST` | `/api/v1/agent/watch` | Run the agent's check now (async), same as the hourly schedule but also outside store hours |
| `GET` | `/api/v1/agent/notifications?unread=false&limit=30` | Notifications, newest first, each with its `proposal`. `unread` = total unread. Realtime: tables `agent_notifications`, `agent_proposals` |
| `POST` | `/api/v1/agent/notifications/{id}/read`, `/api/v1/agent/notifications/read-all` | Mark as read |
| `GET` | `/api/v1/agent/proposals/{id}` | One proposal |
| `POST` | `/api/v1/agent/proposals/{id}/execute` | Body `{"staff_id"}` (a MANAGER). Server does the proposal; `409` if it is no longer `PROPOSED` or cannot be done now (then `FAILED` + `result.error`) |
| `POST` | `/api/v1/agent/proposals/{id}/dismiss` | Body `{"staff_id"}` |
| `POST` | `/api/v1/agent/runs` | Internal: the agent saves one event / watch run (run + proposals + notifications). No auth, like `PATCH /ai/pipeline-runs` |

### AI

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/ai/scan-inputs?history_days=28` | Prediction input for the Risk Scanner & Forecaster: `reference_date`, lots with `ai_status = IDLE`, their products, the last `history_days` of daily sales (`product_daily`) and daily factors for today + 7 days, extended to the latest expiry if later (`daily_context`) |
| `GET` | `/api/v1/ai/optimize-inputs?run_id=&days_ahead=1` | Input data for the Optimizer (at-risk lots with `shelf` curves, `recipe_demand`, product rules, recipes, kitchen capacity, donation partners, ingredient stock) |

### Risk Assessments

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/risk-assessments` | Save Risk Scanner & Forecast results for one run (all rows or none) |

### Optimization Decisions

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/optimization-decisions` | Save the Optimizer's decisions, including every number a task will use (all rows or none) |
| `GET` | `/api/v1/optimization-decisions?run_id=&status=PENDING` | Decisions with the context the LLM needs to write staff instructions |

### Review Queue

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/pending-tasks` | LLM sends task plans (text + priority + steps + `model_used`) for decisions; every plan starts as `WAITING` (no auto-approval) |
| `GET` | `/api/v1/pending-tasks?status=&reviewed_from=` | Review queue for the dashboard with tab counts. Default status: `WAITING` |
| `GET` | `/api/v1/pending-tasks/{review_id}` | Plan detail with decision (incl. Optimizer alternatives), lot, product, risk, recipe, and partner |
| `POST` | `/api/v1/pending-tasks/approve` | Manager approves one or more plans: creates the staff tasks, assigns staff, and books kitchen hours (all or nothing) |
| `POST` | `/api/v1/pending-tasks/reject` | Manager rejects one or more plans with a reason (all or nothing) |

### Demo

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/demo/reset` | Same as `python -m scripts.demo reset`: `demo_reset` for the system date, so every lot is `IDLE` and ready for the AI pipeline (no `demo_seed`, which would mark every lot `CHECKED`). Deletes **all** plans, tasks, decisions and scan results. `409` while an AI pipeline run is active |

### Tasks

| Method | Path | Description |
| --- | --- | --- |
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
7. POST  /pending-tasks                                           ← decision_id + text + priority + model_used (plans → WAITING)
8. PATCH /inventory-lots/ai-status   {"ai_status": "CHECKED"}     mark the lots as done
9. POST  /pending-tasks/approve | /reject                         ← manager (dashboard): approve creates the tasks
```

| Step | Caller | Sends | Gets back |
| --- | --- | --- | --- |
| `scan-inputs` | Risk Scanner + Forecast | `history_days` (0–60, default 28) | `reference_date`, lots with `ai_status = IDLE` (sorted by expiry), their `products` (incl. `shelf_life_days`), `product_daily` for the last `history_days` up to yesterday, and `daily_context` from `reference_date` to `reference_date + 7`, extended to the latest lot expiry if later (see [Forecast Data](#forecast-data)) |
| `risk-assessments` | Risk Scanner | One row per lot: days to expiry, `sellable_hours`, forecast demand, predicted leftover, risk score (0–100), risk level, and for HIGH/CRITICAL lots a `shelf` curve (expected/low/high units sold if discounted x% from today's opening until expiry). Plus `recipe_demand` per active recipe, `reference_date` and `run_metrics`. All new fields and `run_id` are optional. Saved in one transaction by the `save_risk_run` RPC | `run_id` and the `assessment_id` of each lot |
| `optimize-inputs` | Optimizer | `run_id` (optional, latest run if omitted), `days_ahead` | `reference_date`, lots with risk `HIGH`/`CRITICAL` (each with its `shelf` curve), `recipe_demand` of the run (sorted by expected revenue), product rules, active recipes with ingredients, kitchen capacity, active donation partners, and `ingredient_stock` (usable, unexpired stock of every recipe ingredient, earliest expiry first) |
| `optimization-decisions` (POST) | Optimizer | One or more decisions per assessment, with all numbers | `decision_id` of each decision |
| `optimization-decisions` (GET) | LLM | `run_id` (optional, latest), `status=PENDING` | Decisions with assessment, lot (incl. shelf location), product, recipe, and partner context |
| `pending-tasks` | LLM | `decision_id`, `priority`, `ai_reasoning`, `staff_instructions`, `instruction_steps`, `model_used` | `review_id` of each plan (status `WAITING`) |
| `pending-tasks/approve` | Manager | `review_ids`, `manager_id`, optional `review_note` | Created tasks (already assigned) and the kitchen hours that were booked |
| `pending-tasks/reject` | Manager | `review_ids`, `manager_id`, `review_note` (required) | Rejected plans and lots reset to `IDLE` |

Each lot is scanned once: `scan-inputs` only returns `IDLE` lots. Lock the returned lots right after step 1. The only way back to `IDLE` is a manager rejecting every plan of a lot in that run (see [Review Queue and Task Rules](#review-queue-and-task-rules)).

`reference_date` is today in Thailand time, or `DEMO_DATE` if set in `.env`.

A decision's `status` is computed by the `optimization_decisions_status` view: `PENDING` until the LLM sends a plan, `IN_REVIEW` while the plan waits for a manager, then `TASK_CREATED` (approved) or `REJECTED`. Each decision can have exactly one plan and one task (both enforced by unique indexes).

## Decision Rules

`POST /api/v1/optimization-decisions` validates each decision before anything is written.

| `action_type` | Required fields | Must be empty |
| --- | --- | --- |
| `MARKDOWN` | `discount_pct` (between 0 and 100, exclusive) | `batch_count` |
| `KITCHEN_REPURPOSE` | `target_recipe_id`, `batch_count`, `due_by` | `discount_pct`, `new_recommended_price` |
| `DONATE` | `target_partner_id` (type DONATION / FOOD_BANK / CHARITY / COMMUNITY / TEMPLE) | `discount_pct`, `new_recommended_price`, `batch_count` |
| `ANIMAL_FEED` | `target_partner_id` (type ANIMAL_FEED) | `discount_pct`, `new_recommended_price`, `batch_count` |
| `COMPOST` | `target_partner_id` (type COMPOSTING) | `discount_pct`, `new_recommended_price`, `batch_count` |
| `ANAEROBIC_DIGESTION` | `target_partner_id` (type ANAEROBIC_DIGESTION) | `discount_pct`, `new_recommended_price`, `batch_count` |
| `LANDFILL` | `target_partner_id` (type LANDFILL) | `discount_pct`, `new_recommended_price`, `batch_count` |
| `DISCARD` (thrown away in store, no partner) | – | `discount_pct`, `new_recommended_price`, `batch_count` |

All decisions require `assessment_id` and `action_quantity` (> 0). The server fills in `run_id` and `lot_id` from the assessment.

**Checked against real data**

- The product must allow the action (`allow_markdown`, `allow_kitchen_repurposing`, `allow_donation`, `allow_animal_feed`, `allow_composting`, `allow_anaerobic_digestion`, `allow_landfill`).
- The total `action_quantity` per lot in one request cannot exceed the lot's `current_quantity`.
- `MARKDOWN`: if `new_recommended_price` is omitted, the server sets it to `current_selling_price × (1 − discount_pct / 100)`. The price cannot be below the product's `min_allowed_price`.
- `KITCHEN_REPURPOSE`: the recipe must be active, and the lot's product must be one of its ingredients.
- `DONATE`, `ANIMAL_FEED`, `COMPOST`, `ANAEROBIC_DIGESTION`, `LANDFILL`: the partner must be active, have the partner type that matches the action, accept the product's category, and the lot must have at least `min_days_before_expiry` days left (skipped when it is null).

## Review Queue and Task Rules

The LLM never creates staff tasks directly: it sends plans to `pending_tasks`, and a task is created only when the plan is approved: by a manager in the dashboard, or by the Manager Agent under the manager's **Auto-approve** rules (off by default, see below).

`POST /api/v1/pending-tasks` accepts only `decision_id` (required), `priority` (1–5, default 3), `ai_reasoning`, `staff_instructions`, `instruction_steps` (optional list of 1–8 `{title, detail}` objects, shown step by step in the mobile app's "How to do it" section; when it is missing the app shows `staff_instructions` instead), and `model_used` (the model that wrote the text, or `TEMPLATE` when the LLM failed validation). Any other field is ignored.

- The decision must still be `PENDING`. All plans in one request are saved together or not at all.
- The server fills in `run_id`, `assessment_id`, `lot_id`, and `review_deadline` (the decision's `due_by`, or 22:00 Thailand time on the lot's expiry day when there is no `due_by`, as for `MARKDOWN`).
- Plans that nobody reviews stay `WAITING`; there is no expiry.

**Approve / reject** (`POST /pending-tasks/approve`, `POST /pending-tasks/reject`)

- `manager_id` must be an active `MANAGER`; every `review_id` must still be `WAITING`. Several plans (for example every plan of one lot) can be sent in one request, all or nothing.
- Approve creates the tasks with the rules below, then sets each plan to `APPROVED` with `task_id`, `reviewed_by`, and `reviewed_at`. If a kitchen is full (`409`) or any step fails, the new tasks are deleted, the kitchen hours are released, and the plans stay `WAITING`.
- Reject requires `review_note`. No task is created. If a lot has no other plan waiting or approved in that run and the lot is `CHECKED`, it goes back to `IDLE` so the next pipeline run can plan it again.

**Auto-approve (Phase 4, `scripts/auto_approve.sql`)**

- `GET` / `PUT /agent/policies/auto-approve` (`manager_id`, `enabled`, `params`). The manager who saves becomes the owner; approved plans get `reviewed_by` = owner and `approved_by_agent = true` (`reviewed_by` is an FK to `staff` and roles are only MANAGER / STAFF).
- Defaults: `actions` = MARKDOWN (allowed: MARKDOWN, DONATE, ANIMAL_FEED, COMPOST, ANAEROBIC_DIGESTION; never kitchen, landfill or discard), `max_discount_pct` 30, `max_value_thb` 2000 (`action_quantity × current_selling_price`), `min_minutes_before_deadline` 30, `daily_limit` 30, `undo_minutes` 15.
- A plan passes only if the optimizer has no feasible alternative with a higher expected profit, the text is not `TEMPLATE`, the lot is not expired, and the new price is not below `min_allowed_price`. Every waiting plan of the lot must pass (whole lots only).
- `POST /agent/auto-approve` (internal, used by the agent) re-checks every rule against fresh data and approves lot by lot with the normal approve flow; failures are listed in `skipped` (`AA_*` codes) and `errors`.
- `POST /pending-tasks/{review_id}/undo-auto` (`staff_id` = a manager) within `undo_minutes` while the task is still `PENDING`: deletes the task and puts every plan of that lot from the same approval back to `WAITING` with `agent_undone_at`, so the agent never approves them again. List / detail responses include `approved_by_agent`, `agent_undone_at`, `undo_until`.

The rules below apply when a plan is approved.

**Copied by the server**

- From the decision: `lot_id`, `assessment_id`, `action_type`, `action_quantity`, `discount_pct`, `new_recommended_price`, `target_recipe_id`, `batch_count`, `target_partner_id`, `due_by`, `expected_profit_impact`.
- From the lot: `product_id`, and `original_price` (the current selling price).

**Automatic assignment**

- Each task is assigned when it is created (on approval), in the same insert, so the first Realtime event already has `assigned_staff_id`.
- Candidates are active `STAFF` whose `responsible_categories` include the product's category.
- With several candidates, the one with the fewest open tasks (`PENDING` + `IN_PROGRESS`) wins; ties go to the lowest `staff_id`. Tasks assigned earlier in the same request count toward the workload.
- If nobody covers the category, `assigned_staff_id` is `null` and the manager handles it.

**Kitchen booking (`KITCHEN_REPURPOSE`)**

- Hours: `recipe.estimated_prep_time_mins × batch_count ÷ 60`, booked in the recipe's `department_id`.
- The booking date is the date of the decision's `due_by` in Thailand time.
- Hours for tasks that use the same kitchen on the same day are added together and booked once.
- Kitchen hours are booked when the plan is approved, not when the decision or the plan is saved.
- If any kitchen is full, or saving the tasks fails, every booking made by this approval is released and no task is created.

## Task Log

`GET /api/v1/task-log` lists approved tasks for the dashboard's **Task log** page: tasks created since `created_from` (default: today's midnight, Thailand time) plus every task that is still open, newest first. Filters: `status` (several values, including `OVERDUE`), `action_type`, `staff_id`. `counts` is computed before the status filter.

Each item is a task (same context as `GET /tasks`) plus `events` (timeline), `review` (who approved it, or `approved_by_agent`), `is_overdue` / `minutes_late` (against the system time, DEMO_DATE + current clock), `started_at`, `finished_at`, `wait_minutes` (approval → start) and `work_minutes` (start → done).

History comes from `task_events` (`scripts/task_events.sql`): a trigger on `ai_recommended_tasks` writes `CREATED` on insert and `STARTED` / `COMPLETED` (with `quantity`) / `REJECTED` (with `note`) when `task_status` changes, so the mobile app needs no change. Existing tasks are backfilled from `created_at` / `completed_at`. Events are deleted with their task (undo of an AI approval, `demo_reset()`). Without the script the route still works with `events_available = false`.

## Pickup Schedule

`GET /api/v1/pickup-schedule?days_ahead=6` powers the dashboard's **Pickups** page. Each active partner in `donation_partners` gives one slot per day in its `pickup_days` (1 = Monday … 7 = Sunday, the same convention as the Optimizer) between `pickup_time_start` and `pickup_time_end`, from the system date (DEMO_DATE) for `days_ahead` days.

A slot's `items` are the approved tasks for that partner whose `due_by` falls on that day (`source = TASK`, with task status and staff) and the plans still waiting in the Review queue (`source = PLAN`). `kg_confirmed` / `kg_waiting` use each product's `net_content` (G / ML ÷ 1000) and are compared with `max_capacity_kg_per_pickup` and `min_kg_per_pickup`. `costs` uses the Optimizer's dedicated-trip formula (fixed + travel, donation = fixed only, + handling per kg − buyback per kg). `alerts`: `OVER_CAPACITY`, `BELOW_MIN`, `NOT_READY` (the window is open or over and a task is not done), `WAITING_APPROVAL`. Provisional trips the Optimizer plans for later days are not stored, so they are not shown. Read-only, no new table.

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
| `DONATE` / `ANIMAL_FEED` / `COMPOST` / `ANAEROBIC_DIGESTION` / `LANDFILL` / `DISCARD` | The task lot loses `actual_quantity_handled` units |

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

`pending_tasks` is also in the publication with an `anon` read policy, so the dashboard can refresh the review queue (`GET /api/v1/pending-tasks`) when a plan arrives or is reviewed.

## Error Responses

| Status | When |
| --- | --- |
| `400` | The database rejected the write, or kitchen hours exceed capacity on `POST /kitchen-bookings` |
| `403` | On task actions, `staff_id` is not the assigned staff member; on review actions, `manager_id` is not an active `MANAGER` |
| `404` | Unknown `staff_id` or `task_id` on task routes, unknown `manager_id` or `review_id` on review routes, lot not found on `PATCH /inventory-lots/{lot_id}`, none of the `lot_ids` found on `PATCH /inventory-lots/ai-status`, or unknown `department_id` on `POST /kitchen-bookings` |
| `409` | Existing `run_id` or duplicate `lot_id` in the same `run_id` on `POST /risk-assessments`; on `POST /pending-tasks`, a decision is no longer `PENDING`; on `POST /pending-tasks/approve`, a kitchen is full or a plan is no longer `WAITING`; on task actions, the task is not in the required status |
| `422` | Request body fails validation, or a decision fails the checks in [Decision Rules](#decision-rules); on `POST /pending-tasks`, an unknown or repeated `decision_id`; on review actions, a repeated `review_id`; on `complete`, a quantity out of range, not enough stock in the lot, or missing recipe ingredients |

`PATCH /inventory-lots/ai-status` returns lot IDs that do not exist in `not_found` instead of failing, as long as at least one lot was updated.

## Example Requests

> **Warning:** these requests write real data to Supabase, including risk assessments, decisions, tasks, lot status, and **booked kitchen hours**. Release any test bookings afterwards with the `release_kitchen_hours` RPC.

```bash
B=https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1   # local server: http://127.0.0.1:8000/api/v1

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

# 5) Send the LLM's plans to the review queue → keep review_id
curl -X POST $B/pending-tasks -H "Content-Type: application/json" -d '{"tasks": [
  {"decision_id": "<markdown decision_id>", "priority": 2, "model_used": "amazon.nova-lite-v1:0",
   "staff_instructions": "Put 30% off labels on 30 bottles at CHILL-A / A-01",
   "instruction_steps": [
     {"title": "Find the lot", "detail": "Go to CHILL-A / A-01 and check the lot code on the label"},
     {"title": "Print 30 labels", "detail": "Print the new price from the handheld label printer"},
     {"title": "Label and move to front", "detail": "Cover the old price and put the bottles at the front"}]},
  {"decision_id": "<kitchen decision_id>", "priority": 1,
   "staff_instructions": "Bring 2 bottles from CHILL-A / A-01 to the bakery before 17:00"}
]}'

# 5b) Manager approves → tasks are created and assigned (books BAKERY_DEPT for 0.83 h)
curl -X POST $B/pending-tasks/approve -H "Content-Type: application/json" \
  -d '{"review_ids": ["<review_id>", "<review_id>"], "manager_id": "STF-001"}'

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
│   ├── agent.py                # Manager Agent chat (calls ManagerAgentFunction)
│   ├── risk_assessments.py
│   ├── optimization_decisions.py
│   ├── pending_tasks.py        # Review queue: LLM plans → manager approve / reject
│   ├── tasks.py
│   └── staff.py
├── schemas/                    # Pydantic request and response models
│   ├── enums.py                # ActionType, RiskLevel, LotAIStatus, DecisionStatus, ReviewStatus, StaffRole, TaskStatus (match DB)
│   ├── inventory_lot.py
│   ├── kitchen.py
│   ├── risk_assessment.py
│   ├── decision.py             # Decision rules per action_type
│   ├── task.py                 # Task text (decision_id + text) and accept / reject / complete bodies
│   ├── pending_task.py         # Plans from the LLM (+ model_used) and approve / reject bodies
│   └── responses.py            # Response shapes shown in Swagger
├── services/                   # Business logic shared by routers
│   ├── kitchen.py              # department_exists, book_hours, release_hours
│   ├── kitchen_overview.py     # Dashboard Kitchen page (capacity + jobs + menu demand)
│   ├── decisions.py            # Decision checks against real data, listing with context
│   ├── pending_tasks.py        # Review queue: save plans, list with context, approve (creates tasks) / reject (resets lots)
│   ├── tasks.py                # Task creation on approval (auto-assign, kitchen booking, rollback), task queue and detail
│   ├── task_actions.py         # Accept, reject (releases kitchen hours), complete (calls the complete_task DB function)
│   ├── agent.py                # Manager Agent: chat, notifications, proposals (execute / dismiss)
│   └── agent_events.py         # Send events to the Manager Agent (async, never raises)
└── requirements.txt
```

## Forecast Data

Two tables feed the forecast. In the training CSV, join them on `product_daily.sale_date = daily_context.context_date`.

| Use | Where | What |
| --- | --- | --- |
| **Training** (offline) | CSV in `AI/risk_forecaster/data/`, re-export with `python -m scripts.export_training_data` | All of `product_daily` up to yesterday, all of `daily_context`, `products`, a joined `training_dataset.csv`, and a data dictionary |
| **Prediction** (each scan) | `GET /ai/scan-inputs?history_days=28` | IDLE lots, their products, the last `history_days` of `product_daily` (up to yesterday), and `daily_context` for today to today + 7 (extended to the latest lot expiry if later). Past days' factors come from `AI/risk_forecaster/data/mock_v3/daily_context.csv` |

Both use the same columns, so features must be computed the same way in both places. Today's `product_daily`
row is never sent: it is a whole-day summary known only after closing, and today's sales are what the model
predicts. Today's stock on the shelf is in `inventory_lots`. Use `history_days=0` if the model does not use
recent sales.

**`product_daily`** (one row per product per day, 12 Jul – 15 Oct 2026)

| Column | Meaning |
| --- | --- |
| `opening_qty`, `received_qty` | Stock on the shelf at 08:00, and stock received that day |
| `sold_qty` = `sold_full_price_qty` + `markdown_sold_qty` | Units sold at full price and at a discount |
| `waste_qty` | Units thrown away (expired or damaged) |
| `closing_qty` | Stock at 22:00 = opening + received − sold − waste (enforced by a CHECK) |
| `is_stockout`, `stockout_hour` | The shelf ran empty before closing; that day's sales are censored (below real demand) |
| `markdown_pct`, `avg_selling_price` | Highest discount of the day, and the weighted average price |
| `latent_demand` | Real demand before the stock limit. For evaluating models only; never use it as a feature |

**`daily_context`** (one row per day, 12 Jul – 25 Oct 2026)

| Column | Source |
| --- | --- |
| `dow`, `is_weekend` | Calendar |
| `is_public_holiday`, `holiday_name`, `is_long_weekend_day` | Cabinet holiday announcements, including the Bangkok flood holidays on 28–29 Sep 2026 |
| `is_pension_day`, `days_since_any_payday` | Comptroller General's Department 2026 pay calendar (civil servant rounds 1 and 2, pensions) |
| `is_private_payday` | Assumption: last working day of the month |
| `rain_mm`, `rain_mm_16_20`, `temp_max_c`, `temp_min_c` | Open-Meteo at 13.75, 100.50 (Bangkok): observed up to 15 Oct, forecast from 16 Oct |

How the data was made: weather, holidays and paydays are real. Sales are simulated hour by hour from those factors
(day of week, discount effect and day-to-day variation measured from the original `sales_history`), with supplier
delivery days, case packs and a full-shelf rule, so stockouts and waste happen for realistic reasons. Stock on 15 Oct
matches `inventory_lots` exactly. The old `sales_history` table was removed: `product_daily` holds the same
numbers. The view `daily_sales_velocity` (7/30-day average sales, used only by `demo_seed`) reads `product_daily`.

**Demo day:** the data ends on 15 Oct 2026, so run demos with `DEMO_DATE=2026-10-16` and
`python -m scripts.demo reset-seed --date 2026-10-16`.

## Demo Data

Scripts to reset the database and load the demo tasks, so a demo can be rehearsed any number of times.

**One-time setup:** open Supabase → SQL Editor, paste `scripts/demo_functions.sql`, and run it. It creates the table `demo_lot_baseline` (the starting state of LOT-000001 to LOT-000010) and three functions: `demo_reset`, `demo_seed`, and `demo_snapshot`.

```bash
# run from the server folder
python -m scripts.demo reset-seed                    # reset, then load today's demo tasks (most common)
python -m scripts.demo reset                         # reset only
python -m scripts.demo seed                          # load demo tasks (after a reset)
python -m scripts.demo reset-seed --date 2026-10-20  # prepare a specific demo day
python -m scripts.demo snapshot                      # after loading new mock data: save current lots as the baseline
python -m scripts.export_training_data               # export training CSVs for the AI team to ../AI/risk_forecaster/data
```

| Command | What it does |
|---|---|
| `reset` | Deletes **all** review-queue plans, tasks, decisions, risk assessments and forecast runs (with their shelf curves and recipe demand); deletes lots that are not in the baseline (markdown splits, kitchen output, the donation lot); restores the baseline lots (quantity, price, `ai_status = IDLE`, dates shifted to the demo day); releases every kitchen booking; restarts lot numbering after the baseline |
| `seed` | Creates 8 tasks for STF-002/003/004 from real sales velocity: markdown, kitchen, one completed markdown, and one donation to `P-DON-01` on its next pickup day. Due times are fixed clock times on the demo day (15:30–19:00) |
| `snapshot` | Replaces the baseline with every lot currently in `inventory_lots` |

The same functions can be called from the SQL Editor: `select demo_reset(); select demo_seed();`

Notes:
- `reset` also deletes plans and tasks created by the real AI pipeline.
- `seed` inserts its tasks directly (already approved), so the mobile app has work at once; it does not add plans to the review queue.
- `seed` is tied to LOT-000001 to LOT-000010. If new mock data changes these lots, update the task list in `demo_seed`.
- On demo day, remove `DEMO_DATE` from `.env` (or set it to the demo day) so task completion uses the same date as the seeded data.

## Known Limitations

- Lots are scanned only once by design (prototype): only rejecting every plan of a lot resets `ai_status` back to `IDLE`.
- When a kitchen task is rejected, released hours are recomputed per task and rounded to 0.01 h, so a booking that summed several tasks can leave up to 0.01 h booked per task.
- The `anon` read policies on `ai_recommended_tasks` and `pending_tasks` let anyone with the anon key read tasks and plans. Acceptable for a prototype without login.
