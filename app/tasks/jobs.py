from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from redis import asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.cache.cache import RedisCache
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.repositories.idempotency_key import IdempotencyKeyRepository
from app.repositories.order import OrderRepository
from app.repositories.product import ProductRepository
from app.services.order import OrderService
from app.tasks.celery_app import celery_app
from app.websocket.events import EventPublisher

configure_logging(settings.ENVIRONMENT, settings.LOG_LEVEL)
log = get_logger(__name__)


@asynccontextmanager
async def task_session(database_url: str | None = None) -> AsyncGenerator[AsyncSession, None]:
    # Every task runs in a fresh event loop (asyncio.run), so it can't reuse the app's pool.
    engine = create_async_engine(database_url or settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


async def expire_pending_orders_async(
    database_url: str | None = None, redis_url: str | None = None
) -> int:
    client = redis.from_url(redis_url or settings.REDIS_URL, decode_responses=True)
    try:
        async with task_session(database_url) as session:
            service = OrderService(
                session,
                OrderRepository(session),
                ProductRepository(session),
                IdempotencyKeyRepository(session),
                RedisCache(client),
                EventPublisher(client),
            )
            expired = 0
            while batch := await service.expire_orders(settings.EXPIRE_ORDERS_BATCH_SIZE):
                expired += len(batch)
                log.info("orders.expired", order_ids=batch)
            return expired
    finally:
        await client.aclose()


async def purge_idempotency_keys_async(database_url: str | None = None) -> int:
    async with task_session(database_url) as session:
        deleted = await IdempotencyKeyRepository(session).delete_older_than(
            settings.IDEMPOTENCY_KEY_TTL_HOURS
        )
        await session.commit()
        return deleted


@celery_app.task(name="orders.expire_pending")
def expire_pending_orders() -> int:
    return asyncio.run(expire_pending_orders_async())


@celery_app.task(name="idempotency_keys.purge_expired")
def purge_idempotency_keys() -> int:
    deleted = asyncio.run(purge_idempotency_keys_async())
    log.info("idempotency_keys.purged", deleted=deleted)
    return deleted
