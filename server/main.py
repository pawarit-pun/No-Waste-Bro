from fastapi import FastAPI

from routers import ai, inventory_lots, kitchen, products

API_PREFIX = "/api/v1"

app = FastAPI(title="No-Waste-Bro API")

for module in (products, inventory_lots, kitchen, ai):
    app.include_router(module.router, prefix=API_PREFIX)
