from __future__ import annotations

import asyncio

from redis import asyncio as redis

from app.cache.cache import RedisCache
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.database import connect
from app.repositories.idempotency_key import IdempotencyKeyRepository
from app.repositories.order import OrderRepository
from app.repositories.product import ProductRepository
from app.services.order import OrderService
from app.tasks.celery_app import celery_app
from app.websocket.events import EventPublisher

configure_logging(settings.ENVIRONMENT, settings.LOG_LEVEL)
log = get_logger(__name__)


async def expire_pending_orders_async(dsn: str | None = None, redis_url: str | None = None) -> int:
    conn = await connect(dsn)
    client = redis.from_url(redis_url or settings.REDIS_URL, decode_responses=True)
    try:
        service = OrderService(
            conn,
            OrderRepository(conn),
            ProductRepository(conn),
            IdempotencyKeyRepository(conn),
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
        await conn.close()


async def purge_idempotency_keys_async(dsn: str | None = None) -> int:
    conn = await connect(dsn)
    try:
        return await IdempotencyKeyRepository(conn).delete_older_than(
            settings.IDEMPOTENCY_KEY_TTL_HOURS
        )
    finally:
        await conn.close()


@celery_app.task(name="orders.expire_pending")
def expire_pending_orders() -> int:
    return asyncio.run(expire_pending_orders_async())


@celery_app.task(name="idempotency_keys.purge_expired")
def purge_idempotency_keys() -> int:
    deleted = asyncio.run(purge_idempotency_keys_async())
    log.info("idempotency_keys.purged", deleted=deleted)
    return deleted
