from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from configs.config import db_env
from core.openapi import APP_DESCRIPTION, APP_TITLE, APP_VERSION, TAGS_METADATA
from routers import (ai, inventory_lots, kitchen, optimization_decisions, optimizer, products,
                    risk_assessments, staff, tasks)

API_PREFIX = "/api/v1"

app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    description=APP_DESCRIPTION,
    openapi_tags=TAGS_METADATA,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in db_env.cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (products, inventory_lots, kitchen, ai, optimizer, risk_assessments,
            optimization_decisions, tasks, staff):
    app.include_router(module.router, prefix=API_PREFIX)

# Entry point for AWS Lambda (API Gateway → Lambda → Mangum → FastAPI), see template.yaml
# Not used when running locally with fastapi dev / uvicorn
handler = Mangum(app, lifespan="off")