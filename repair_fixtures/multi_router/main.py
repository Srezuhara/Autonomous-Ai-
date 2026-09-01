from fastapi import FastAPI

from routers.suppliers import router as suppliers_router
from routers.products import router as products_router
from routers.warehouses import router as warehouses_router

app = FastAPI()

app.include_router(suppliers_router)
app.include_router(products_router)
app.include_router(warehouses_router)
