from __future__ import annotations

from redis import asyncio as redis

from app.core.config import settings

redis_client: redis.Redis = redis.from_url(settings.REDIS_URL, decode_responses=True)


async def close_redis() -> None:
    await redis_client.aclose()


_DENYLIST_PREFIX = "denylist:jti:"


async def deny_jti(jti: str, ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        return
    await redis_client.set(f"{_DENYLIST_PREFIX}{jti}", "1", ex=ttl_seconds)


async def is_jti_denied(jti: str) -> bool:
    return bool(await redis_client.exists(f"{_DENYLIST_PREFIX}{jti}"))
