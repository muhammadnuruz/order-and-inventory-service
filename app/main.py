from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.router import api_router
from app.cache.redis import close_redis, redis_client
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import AccessLogMiddleware, RequestIDMiddleware
from app.core.rate_limit import limiter
from app.db.database import close_pool, get_pool, init_pool
from app.websocket.events import listen_for_events
from app.websocket.manager import manager

configure_logging(settings.ENVIRONMENT, settings.LOG_LEVEL)
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_pool()
    events_listener = asyncio.create_task(listen_for_events(redis_client, manager))
    log.info("app.startup", environment=settings.ENVIRONMENT)
    yield
    events_listener.cancel()
    await asyncio.gather(events_listener, return_exceptions=True)
    await close_pool()
    await close_redis()
    log.info("app.shutdown")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    redoc_url=None,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
register_exception_handlers(app)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(RequestIDMiddleware)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.VERSION}


@app.get("/health/ready", tags=["health"])
async def health_ready() -> JSONResponse:
    try:
        await get_pool().fetchval("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    try:
        redis_ok = bool(await redis_client.ping())
    except RedisError:
        redis_ok = False
    return JSONResponse(
        {"db": db_ok, "redis": redis_ok},
        status_code=200 if db_ok and redis_ok else 503,
    )
