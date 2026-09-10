import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, orders, products
from app.background import expiry_worker
from app.db import close_pool, init_pool
from app.errors import AppError, app_error_handler
from app.redis_client import close_redis, get_redis

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("app")
logger.setLevel(logging.INFO)

_worker_state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_pool()
    await get_redis().ping()
    expiry_worker.start(_worker_state)
    logger.info("Application started")
    yield

    logger.info("Application stopping")
    await expiry_worker.stop(_worker_state)
    await close_redis()
    await close_pool()


app = FastAPI(
    title="Order & Inventory Reservation Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_exception_handler(AppError, app_error_handler)

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(orders.router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
