from fastapi import FastAPI

from core.openapi import APP_DESCRIPTION, APP_TITLE, APP_VERSION, TAGS_METADATA
from routers import ai, inventory_lots, kitchen, products, risk_assessments, tasks

API_PREFIX = "/api/v1"

app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    description=APP_DESCRIPTION,
    openapi_tags=TAGS_METADATA,
)

for module in (products, inventory_lots, kitchen, ai, risk_assessments, tasks):
    app.include_router(module.router, prefix=API_PREFIX)
