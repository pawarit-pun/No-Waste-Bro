# No-Waste-Bro

**An AI agent that cuts food waste in a hypermarket.**
Every morning it checks each lot on the shelves, predicts which ones will not sell before they expire, decides the most profitable way to handle them (markdown, kitchen, donation, animal feed, compost, biogas, landfill), writes step-by-step tasks for the staff, and tracks the work until the stock is updated.

> Hackathon prototype (NTT DATA 2026). All store data is mock data built to match real-world references; see [Data](#data).

---

## How it works

```
                Risk Scanner + Forecaster        Optimizer                 LLM Task Agent
 lots IDLE ──►  which lots will be left?   ──►  what to do, how many?  ──► step-by-step task text
                (LightGBM, risk 0-100)          (MILP, max net profit)     (Bedrock Nova Lite + SOP RAG)
                                                                                   │
                                                                                   ▼
 stock updated ◄── staff: Start → Complete ◄── task assigned ◄── manager approves (or AI auto-approve)
 (mobile app)                                   by category        in the Review queue (dashboard)
```

1. **Risk Scanner + Forecaster** (`AI/risk_forecaster`): forecasts daily demand per product (LightGBM, weather / holiday / payday features), splits it between lots of the same product, and scores each lot by the share expected to be left at expiry. HIGH / CRITICAL lots go on; LOW / MEDIUM are rescanned tomorrow.
2. **Optimizer** (`AI/food_waste_optimizer`): solves all at-risk lots together as one MILP: discount level, kitchen recipes and batches, partner pickups (days, time windows, kg limits, trip cost), counting the cost of goods on every path. Output: `optimization_decisions`.
3. **LLM Task Agent** (`AI/llm-task-agent`): turns each decision into a task: priority, staff instructions, numbered steps and reasoning for the manager. Step titles and every number come from code; the LLM only writes the wording, and a validator checks it (fallback: Qwen3 Next, then a template).
4. **Review queue**: plans wait for a manager in the dashboard, or for the Manager Agent's **auto-approve** rules (off by default, limited to safe actions). Approval creates the task, assigns staff by product category and books kitchen hours.
5. **Staff app**: the task appears in real time; completing it updates stock (markdown splits the lot at the new price, kitchen work consumes ingredients and creates a new lot of the dish, donation / disposal removes the units).

**Design rules**

- *The Optimizer owns the numbers, the LLM owns the text.* Quantities, prices, recipes, partners and deadlines are copied from the decision; the LLM cannot change them.
- *One `run_id` links everything*: risk assessments, decisions, plans and tasks of the same scan.
- *The AI never changes store data on its own*: the Manager Agent only notifies and proposes; a person confirms.

**Actions (`action_type`)**

| Action | Meaning | Partner |
| --- | --- | --- |
| `MARKDOWN` | Discount and relabel | – |
| `KITCHEN_REPURPOSE` | Send to an in-store kitchen to make a dish | – |
| `DONATE` | Food bank / charity | DONATION, FOOD_BANK, CHARITY, COMMUNITY, TEMPLE |
| `ANIMAL_FEED` | Animal feed | ANIMAL_FEED |
| `COMPOST` | Composting | COMPOSTING |
| `ANAEROBIC_DIGESTION` | Biogas plant | ANAEROBIC_DIGESTION |
| `LANDFILL` | Landfill | LANDFILL |
| `DISCARD` | Thrown away in store | – |

---

## Architecture

```
 Staff app (Flutter, iOS)         Manager dashboard (React, S3 + CloudFront)
          │  REST + Supabase Realtime          │
          ▼                                    ▼
 ┌──────────────── AWS (SAM stack no-waste-bro-api, ap-southeast-1) ────────────────┐
 │ API Gateway ─► ApiFunction (FastAPI on Lambda)                                    │
 │                   │ invoke                    │ invoke                            │
 │                   ▼                           ▼                                   │
 │   PipelineWorkerFunction           ManagerAgentFunction        EventBridge        │
 │   (container image: scan →         (chat, what-if, events,     hourly check,      │
 │    optimize → tasks)                Morning brief / Evening)   07:30, 21:30       │
 │                   └──────── Amazon Bedrock (us-east-1): Nova Lite, Qwen3 Next,    │
 │                             Knowledge Base of store SOPs (S3) ────────────────────┤
 └───────────────────────────────────────────┬──────────────────────────────────────┘
                                             ▼
                       Supabase (PostgreSQL + Realtime + RPC functions)
```

- The API is the single entry point: AI components read inputs and write results through it, never straight to the database.
- Long work runs off the request path: `POST /ai/pipeline-runs` answers `202` and the worker reports progress to `pipeline_runs` (API Gateway stops at 30 s).
- Stock changes (complete a task, book kitchen hours, save a scan) are Postgres functions, so each runs in one transaction.

---

## Repository

| Folder | What | Stack | Docs |
| --- | --- | --- | --- |
| [`server/`](server/) | REST API, business rules, deployment (`template.yaml`), demo scripts | FastAPI, Pydantic, supabase-py, Mangum, AWS SAM | [server/README.md](server/README.md) |
| [`staff_tasks_app/`](staff_tasks_app/) | Staff mobile app: pick yourself, task list, task detail, start / complete / reject | Flutter, Riverpod, Dio, supabase_flutter | |
| [`manager_dashboard/`](manager_dashboard/) | Manager web app | React 19, TypeScript, Tailwind CSS 4, Vite | [manager_dashboard/README.md](manager_dashboard/README.md) |
| [`AI/risk_forecaster/`](AI/risk_forecaster/) | Demand forecast + lot risk, training and calibration | pandas, LightGBM, scikit-learn | [README](AI/risk_forecaster/README.md), [criteria sources](AI/risk_forecaster/docs/criteria_sources.md) |
| [`AI/food_waste_optimizer/`](AI/food_waste_optimizer/) | Lot allocation across all actions | NumPy, SciPy MILP (HiGHS) | [README](AI/food_waste_optimizer/README.md) |
| [`AI/llm-task-agent/`](AI/llm-task-agent/) | Decision → task text with SOP retrieval and validation | Bedrock Converse, Knowledge Base, Pydantic | [README](AI/llm-task-agent/README.md) |
| [`AI/pipeline/`](AI/pipeline/) | Runs the three AI steps in order (Lambda container image) | Docker, AWS Lambda | [README](AI/pipeline/README.md) |
| [`AI/manager_agent/`](AI/manager_agent/) | Manager assistant: chat with tools, what-if, notifications, proposals, daily reports, auto-approve | Bedrock Converse + tools | [README](AI/manager_agent/README.md) |
| [`AI/backtest/`](AI/backtest/) | Measures the AI on a simulated store (60 days, or one-shot day) | Python | [README](AI/backtest/README.md) |

---

## Features

**Staff (mobile app)**
- Pick yourself on "Who's on shift?" (no login in the prototype).
- My tasks: All / Pending / In progress / Done, urgent banner, new tasks pushed live (Supabase Realtime).
- Task detail: what to do, where, how many, new price or recipe or pickup partner, numbered steps, why the AI chose it.
- Start, Complete (actual quantity handled), Reject (with a reason).

**Manager (web dashboard)**
- **Overview**: live counters, Morning brief and Evening summary written by the agent.
- **Review queue**: approve / reject the AI's plans, Optimizer alternatives per lot, AI auto-approve rules with undo.
- **Inventory**, **Kitchen** (hours, jobs, menu demand), **Pickups** (7-day partner schedule with kg vs capacity).
- **Task log**: every approved task with its timeline. **Pipeline runs**: each AI run, step by step.
- **AI assistant**: chat in Thai about any lot or plan, what-if scenarios (no markdown, partner unavailable, kitchen hours, demand × 0.5–1.5), notification bell with proposals to confirm.
- **Run demo**: reset the demo store and start the AI pipeline with one button.

---

## Data

The prototype runs on mock data designed to look like a real hypermarket. Sources and assumptions are listed in [`AI/risk_forecaster/docs/criteria_sources.md`](AI/risk_forecaster/docs/criteria_sources.md) and `server/README.md` (Forecast Data).

| Data | Content |
| --- | --- |
| Sales history | 1 year of daily sales for 14 products (16 Oct 2025 – 15 Oct 2026), simulated with real Bangkok weather (Open-Meteo), holidays and paydays, including stock-outs and markdown days |
| Demo store | 13 lots on demo day **2026-10-16** (meat, seafood, dairy, bakery, produce, ready-to-eat) |
| Store setup | 6 kitchen recipes in 2 kitchens (8 h/day each), 5 pickup partners (food bank, animal feed, compost, biogas, landfill) with days, time windows, kg limits and costs |
| People | 1 manager, 3 staff, each responsible for 1–2 product categories |
| SOPs | Store procedures in the Bedrock Knowledge Base, used by the task agent and the manager assistant |

---

## Getting started

**Live environment**

| | URL |
| --- | --- |
| API | `https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1` |
| Swagger (Thai descriptions) | `https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/docs` |
| Dashboard | output `DashboardUrl` of the stack (`cd server && sam list stack-outputs`) |

**Run locally**

```bash
# API (http://127.0.0.1:8000/docs)
cd server && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt     # then create .env (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, DEMO_DATE): see server/README.md
fastapi dev main.py

# Staff app (iOS Simulator; uses the AWS API by default)
cd staff_tasks_app && flutter pub get && open -a Simulator && flutter run
#   local API: flutter run --dart-define=API_BASE_URL=http://localhost:8000/api/v1

# Manager dashboard (http://localhost:5173)
cd manager_dashboard && npm install && cp .env.example .env && npm run dev
```

Each AI component runs on its own from its folder (separate virtual environments); see its README.

**Deploy to AWS** (from the repository root)

```bash
./AI/pipeline/build_worker.sh            # AI image: pipeline worker + manager agent → ECR
cd server && ./scripts/build_lambda.sh && sam deploy --parameter-overrides \
  SupabaseServiceRoleKey="$(grep '^SUPABASE_SERVICE_ROLE_KEY=' .env | cut -d= -f2-)" \
  WorkerImageUri="$(cat ../AI/pipeline/.last_image_uri)" DemoDate=2026-10-16
cd .. && ./manager_dashboard/scripts/deploy_dashboard.sh   # dashboard → S3 + CloudFront
```

---

## Running the demo

The system date is pinned to **2026-10-16** (`DemoDate`). Every reset must use the same date.

1. **Reset**: dashboard → *Run demo* → Reset (or `python -m scripts.demo reset --date 2026-10-16` in `server/`). All 13 lots return to `IDLE`; plans, tasks and scan results are cleared.
2. **Run the AI**: *Run demo* → Run (or `POST /ai/pipeline-runs`). Watch SCAN → OPTIMIZE → TASKS on *Pipeline runs* (2–5 minutes; the first run after a while is ~30 s slower).
3. **Review**: approve plans in *Review queue*; ask the AI assistant why a lot got its plan, or try a what-if.
4. **Work**: on the phone, the assigned staff sees the task appear, starts and completes it; the dashboard *Task log*, *Kitchen* and *Pickups* update live.

Backup without Bedrock: `python -m scripts.demo reset-seed --date 2026-10-16` loads ready-made tasks instantly.

---

## Prototype limitations

- No real authentication: users pick their name; the API has no auth and CORS is `*`.
- All data is mock data; there is no POS feed, so profit figures are the Optimizer's estimates.
- Notifications reach the phone only while the app is open (Supabase Realtime; no push notifications).
- The demo runs on a pinned date (`DEMO_DATE`), and `demo_reset` deletes every plan and task.
- Cut-offs, lead times and some costs are team assumptions to be tuned with real store data (marked **[C]** in the criteria sources).
