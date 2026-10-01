from __future__ import annotations

import json
import random
from typing import Any

from redis import asyncio as redis
from redis.exceptions import RedisError

from app.core.logging import get_logger

log = get_logger(__name__)

PRODUCTS_LIST_VERSION_KEY = "products:list:version"


def product_key(product_id: int) -> str:
    return f"product:{product_id}"


def products_list_key(version: int, skip: int, limit: int) -> str:
    return f"products:list:v{version}:{skip}:{limit}"


def order_key(order_id: int) -> str:
    return f"order:{order_id}"


class RedisCache:
    """Fail-open cache: any Redis error is logged and treated as a miss."""

    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    async def get_json(self, key: str) -> Any | None:
        try:
            raw = await self.client.get(key)
        except RedisError:
            log.warning("cache.get_failed", key=key)
            return None
        return json.loads(raw) if raw is not None else None

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        jitter = random.randint(0, max(1, ttl_seconds // 10))
        try:
            await self.client.set(key, json.dumps(value), ex=ttl_seconds + jitter)
        except RedisError:
            log.warning("cache.set_failed", key=key)

    async def delete(self, *keys: str) -> None:
        if not keys:
            return
        try:
            await self.client.delete(*keys)
        except RedisError:
            log.warning("cache.delete_failed", keys=keys)

    async def get_version(self, key: str) -> int:
        try:
            value = await self.client.get(key)
        except RedisError:
            return 0
        return int(value) if value is not None else 0

    async def bump_version(self, key: str) -> None:
        try:
            await self.client.incr(key)
        except RedisError:
            log.warning("cache.bump_failed", key=key)

    async def invalidate_products(self, product_ids: list[int]) -> None:
        await self.delete(*(product_key(product_id) for product_id in product_ids))
        await self.bump_version(PRODUCTS_LIST_VERSION_KEY)
