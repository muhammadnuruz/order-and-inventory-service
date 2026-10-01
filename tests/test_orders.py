from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import asyncpg
import pytest

from app.cache.cache import RedisCache
from app.core.exceptions import (
    IdempotencyKeyReusedError,
    InsufficientStockError,
    InvalidOrderStateError,
    NotFoundError,
)
from app.core.security import hash_password
from app.models.order import OrderStatus
from app.repositories.idempotency_key import IdempotencyKeyRepository
from app.repositories.order import OrderRepository
from app.repositories.product import ProductRepository
from app.repositories.user import UserRepository
from app.schemas.order import OrderCreate, OrderItemCreate, OrderRead
from app.services.order import OrderService
from app.websocket.events import EventPublisher
from tests.fakes import FakeRedis


def build_service(conn: asyncpg.Connection, fake_redis: FakeRedis) -> OrderService:
    return OrderService(
        conn,
        OrderRepository(conn),
        ProductRepository(conn),
        IdempotencyKeyRepository(conn),
        RedisCache(fake_redis),  # type: ignore[arg-type]
        EventPublisher(fake_redis),  # type: ignore[arg-type]
    )


def order_of(*items: tuple[int, int]) -> OrderCreate:
    return OrderCreate(items=[OrderItemCreate(product_id=p, quantity=q) for p, q in items])


async def create_user(pool: asyncpg.Pool, email: str = "buyer@example.com") -> int:
    async with pool.acquire() as conn:
        user = await UserRepository(conn).create(email, hash_password("password123"))
    assert user is not None
    return user.id


async def create_product(pool: asyncpg.Pool, stock: int, price: str = "10.00") -> int:
    async with pool.acquire() as conn:
        product = await ProductRepository(conn).create("Product", Decimal(price), stock)
    return product.id


async def stock_of(pool: asyncpg.Pool, product_id: int) -> int:
    return await pool.fetchval("SELECT stock_quantity FROM products WHERE id = $1", product_id)


async def place_order(
    pool: asyncpg.Pool, fake_redis: FakeRedis, user_id: int, data: OrderCreate, key: str
) -> tuple[OrderRead, bool]:
    async with pool.acquire() as conn:
        return await build_service(conn, fake_redis).create_order(user_id, data, key)


async def test_fifty_parallel_orders_for_ten_items_only_ten_succeed(
    db_pool: asyncpg.Pool, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(db_pool)
    product_id = await create_product(db_pool, stock=10)

    results = await asyncio.gather(
        *(
            place_order(db_pool, fake_redis, user_id, order_of((product_id, 1)), str(uuid.uuid4()))
            for _ in range(50)
        ),
        return_exceptions=True,
    )

    succeeded = [r for r in results if isinstance(r, tuple)]
    rejected = [r for r in results if isinstance(r, InsufficientStockError)]
    assert len(succeeded) == 10
    assert len(rejected) == 40
    assert await stock_of(db_pool, product_id) == 0
    assert await db_pool.fetchval("SELECT sum(quantity) FROM order_items") == 10


async def test_same_idempotency_key_in_parallel_creates_one_order(
    db_pool: asyncpg.Pool, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(db_pool)
    product_id = await create_product(db_pool, stock=10)
    key = str(uuid.uuid4())

    results = await asyncio.gather(
        *(
            place_order(db_pool, fake_redis, user_id, order_of((product_id, 2)), key)
            for _ in range(20)
        )
    )

    assert len({order.id for order, _ in results}) == 1
    assert sum(not replayed for _, replayed in results) == 1
    assert await stock_of(db_pool, product_id) == 8
    assert await db_pool.fetchval("SELECT count(*) FROM orders") == 1


async def test_reusing_key_with_different_body_is_rejected(
    db_pool: asyncpg.Pool, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(db_pool)
    product_id = await create_product(db_pool, stock=10)

    await place_order(db_pool, fake_redis, user_id, order_of((product_id, 1)), "key-00000001")
    with pytest.raises(IdempotencyKeyReusedError):
        await place_order(db_pool, fake_redis, user_id, order_of((product_id, 3)), "key-00000001")

    assert await stock_of(db_pool, product_id) == 9


async def test_same_key_is_scoped_per_user(db_pool: asyncpg.Pool, fake_redis: FakeRedis) -> None:
    alice = await create_user(db_pool, "alice@example.com")
    bob = await create_user(db_pool, "bob@example.com")
    product_id = await create_product(db_pool, stock=10)

    first, _ = await place_order(
        db_pool, fake_redis, alice, order_of((product_id, 1)), "shared-key"
    )
    second, replayed = await place_order(
        db_pool, fake_redis, bob, order_of((product_id, 1)), "shared-key"
    )

    assert first.id != second.id
    assert replayed is False
    assert await stock_of(db_pool, product_id) == 8


async def test_failed_order_rolls_back_everything(
    db_pool: asyncpg.Pool, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(db_pool)
    in_stock = await create_product(db_pool, stock=5)
    sold_out = await create_product(db_pool, stock=0)

    with pytest.raises(InsufficientStockError):
        await place_order(
            db_pool, fake_redis, user_id, order_of((in_stock, 2), (sold_out, 1)), "key-rollback"
        )
    with pytest.raises(NotFoundError):
        await place_order(db_pool, fake_redis, user_id, order_of((999, 1)), "key-missing")

    assert await stock_of(db_pool, in_stock) == 5
    assert await db_pool.fetchval("SELECT count(*) FROM orders") == 0
    assert await db_pool.fetchval("SELECT count(*) FROM idempotency_keys") == 0


async def test_duplicate_lines_are_merged_and_total_is_computed(
    db_pool: asyncpg.Pool, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(db_pool)
    cheap = await create_product(db_pool, stock=10, price="2.50")
    pricey = await create_product(db_pool, stock=10, price="100.00")

    order, _ = await place_order(
        db_pool, fake_redis, user_id, order_of((pricey, 1), (cheap, 2), (cheap, 1)), "key-merge"
    )

    assert [(i.product_id, i.quantity) for i in order.items] == [(cheap, 3), (pricey, 1)]
    assert order.total_price == Decimal("107.50")
    assert order.status == OrderStatus.PENDING


async def test_crossing_multi_item_orders_do_not_deadlock(
    db_pool: asyncpg.Pool, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(db_pool)
    a = await create_product(db_pool, stock=100)
    b = await create_product(db_pool, stock=100)

    await asyncio.wait_for(
        asyncio.gather(
            *(
                place_order(
                    db_pool,
                    fake_redis,
                    user_id,
                    order_of((a, 1), (b, 1)) if i % 2 else order_of((b, 1), (a, 1)),
                    str(uuid.uuid4()),
                )
                for i in range(40)
            )
        ),
        timeout=30,
    )

    assert await stock_of(db_pool, a) == 60
    assert await stock_of(db_pool, b) == 60


async def test_cancel_returns_reserved_stock_once(
    db_pool: asyncpg.Pool, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(db_pool)
    product_id = await create_product(db_pool, stock=10)
    order, _ = await place_order(
        db_pool, fake_redis, user_id, order_of((product_id, 4)), "key-cancel"
    )

    async def cancel() -> OrderRead:
        async with db_pool.acquire() as conn:
            return await build_service(conn, fake_redis).cancel_order(order.id, user_id)

    results = await asyncio.gather(*(cancel() for _ in range(5)), return_exceptions=True)

    assert sum(isinstance(r, OrderRead) for r in results) == 1
    assert sum(isinstance(r, InvalidOrderStateError) for r in results) == 4
    assert await stock_of(db_pool, product_id) == 10


async def test_cannot_cancel_or_read_someone_elses_order(
    db_pool: asyncpg.Pool, fake_redis: FakeRedis
) -> None:
    owner = await create_user(db_pool, "owner@example.com")
    stranger = await create_user(db_pool, "stranger@example.com")
    product_id = await create_product(db_pool, stock=10)
    order, _ = await place_order(db_pool, fake_redis, owner, order_of((product_id, 1)), "key-owner")

    async with db_pool.acquire() as conn:
        service = build_service(conn, fake_redis)
        with pytest.raises(NotFoundError):
            await service.get_order(order.id, stranger)
        with pytest.raises(NotFoundError):
            await service.cancel_order(order.id, stranger)


async def test_pay_confirms_and_confirmed_order_cannot_be_cancelled(
    db_pool: asyncpg.Pool, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(db_pool)
    product_id = await create_product(db_pool, stock=10)
    order, _ = await place_order(db_pool, fake_redis, user_id, order_of((product_id, 1)), "key-pay")

    async with db_pool.acquire() as conn:
        service = build_service(conn, fake_redis)
        confirmed = await service.confirm_order(order.id, user_id)
        with pytest.raises(InvalidOrderStateError):
            await service.cancel_order(order.id, user_id)

    assert confirmed.status == OrderStatus.CONFIRMED
    assert confirmed.confirmed_at is not None
    assert await stock_of(db_pool, product_id) == 9


async def test_expired_orders_are_cancelled_and_stock_released(
    db_pool: asyncpg.Pool, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(db_pool)
    product_id = await create_product(db_pool, stock=10)
    expired, _ = await place_order(
        db_pool, fake_redis, user_id, order_of((product_id, 3)), "key-old"
    )
    fresh, _ = await place_order(db_pool, fake_redis, user_id, order_of((product_id, 2)), "key-new")
    await db_pool.execute(
        "UPDATE orders SET expires_at = now() - interval '1 second' WHERE id = $1", expired.id
    )

    async with db_pool.acquire() as conn:
        service = build_service(conn, fake_redis)
        with pytest.raises(InvalidOrderStateError):
            await service.confirm_order(expired.id, user_id)
        cancelled = await service.expire_orders()
        assert await service.expire_orders() == []
        statuses = {o.id: (await service.get_order(o.id, user_id)).status for o in (expired, fresh)}

    assert cancelled == [expired.id]
    assert statuses == {expired.id: OrderStatus.CANCELLED, fresh.id: OrderStatus.PENDING}
    assert await stock_of(db_pool, product_id) == 8
