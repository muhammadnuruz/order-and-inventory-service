from __future__ import annotations

from typing import Any

from redis.exceptions import ConnectionError as RedisConnectionError

from app.cache.cache import PRODUCTS_LIST_VERSION_KEY, RedisCache, product_key
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services.order import merge_items, request_fingerprint
from tests.fakes import FakeRedis


class BrokenRedis:
    def __getattr__(self, name: str) -> Any:
        async def fail(*args: Any, **kwargs: Any) -> None:
            raise RedisConnectionError("redis is down")

        return fail


async def test_cache_round_trip_and_invalidation() -> None:
    cache = RedisCache(FakeRedis())  # type: ignore[arg-type]

    await cache.set_json(product_key(1), {"id": 1, "stock_quantity": 5}, ttl_seconds=60)
    assert await cache.get_json(product_key(1)) == {"id": 1, "stock_quantity": 5}

    await cache.invalidate_products([1])
    assert await cache.get_json(product_key(1)) is None
    assert await cache.get_version(PRODUCTS_LIST_VERSION_KEY) == 1


async def test_cache_fails_open_when_redis_is_down() -> None:
    cache = RedisCache(BrokenRedis())  # type: ignore[arg-type]

    await cache.set_json("key", {"a": 1}, ttl_seconds=60)
    await cache.invalidate_products([1, 2])
    assert await cache.get_json("key") is None
    assert await cache.get_version(PRODUCTS_LIST_VERSION_KEY) == 0


def test_merge_items_sums_duplicates_and_sorts_by_product_id() -> None:
    data = OrderCreate(
        items=[
            OrderItemCreate(product_id=3, quantity=1),
            OrderItemCreate(product_id=1, quantity=2),
            OrderItemCreate(product_id=3, quantity=4),
        ]
    )

    assert list(merge_items(data).items()) == [(1, 2), (3, 5)]


def test_request_fingerprint_depends_on_body() -> None:
    one = OrderCreate(items=[OrderItemCreate(product_id=1, quantity=1)])
    same = OrderCreate(items=[OrderItemCreate(product_id=1, quantity=1)])
    other = OrderCreate(items=[OrderItemCreate(product_id=1, quantity=2)])

    assert request_fingerprint(one) == request_fingerprint(same)
    assert request_fingerprint(one) != request_fingerprint(other)
