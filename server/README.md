# No-Waste-Bro API Server

Backend for No-Waste-Bro, built with **FastAPI** and using **Supabase** as the database.

## Requirements

- Python 3.10+ (developed on Python 3.13)
- A Supabase project with the tables and RPCs the server uses
  (`products`, `inventory_lots`, `sales_history`, `daily_sales_velocity`,
  `kitchen_capacity_daily`, RPCs `ensure_kitchen_days` and `book_kitchen_hours`)

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

All endpoints are under the `/api/v1` prefix.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/products` | List all products |
| `POST` | `/api/v1/inventory-lots` | Create an inventory lot |
| `PATCH` | `/api/v1/inventory-lots/{lot_id}` | Update an inventory lot |
| `GET` | `/api/v1/kitchen-capacity?days_ahead=1` | Kitchen capacity from today to +`days_ahead` days (0–30) |
| `POST` | `/api/v1/kitchen-bookings` | Book kitchen hours |
| `GET` | `/api/v1/ai/scan-inputs` | Input data for the Risk Scanner & Forecaster |

Example requests:

```bash
curl http://127.0.0.1:8000/api/v1/products

curl -X POST http://127.0.0.1:8000/api/v1/kitchen-bookings \
  -H "Content-Type: application/json" \
  -d '{"department_id": "<department-id>", "booking_date": "2026-10-14", "hours": 2}'
```

## Project Structure

```
server/
├── main.py           # FastAPI app and router registration
├── configs/          # Environment loading (pydantic-settings)
├── core/             # Shared utilities, e.g. Thailand-time dates
├── db/               # Supabase client and data-fetching helpers
├── routers/          # API endpoints
├── schemas/          # Pydantic request models
├── services/         # Business logic
└── requirements.txt
```
