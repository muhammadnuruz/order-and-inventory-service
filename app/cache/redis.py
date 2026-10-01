from __future__ import annotations

from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from redis import asyncio as redis

from app.core.config import settings

redis_client = redis.from_url(settings.REDIS_URL)


async def init_cache() -> None:
    FastAPICache.init(RedisBackend(redis_client), prefix="fastapi-cache")


async def close_cache() -> None:
    await redis_client.aclose()


_DENYLIST_PREFIX = "denylist:jti:"


async def deny_jti(jti: str, ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        return
    await redis_client.set(f"{_DENYLIST_PREFIX}{jti}", "1", ex=ttl_seconds)


async def is_jti_denied(jti: str) -> bool:
    return bool(await redis_client.exists(f"{_DENYLIST_PREFIX}{jti}"))


async def invalidate_posts_cache() -> None:
    await FastAPICache.clear(namespace="posts")
