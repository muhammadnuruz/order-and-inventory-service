from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
from tests.conftest import SessionFactory
from tests.fakes import FakeRedis


def build_service(session: AsyncSession, fake_redis: FakeRedis) -> OrderService:
    return OrderService(
        session,
        OrderRepository(session),
        ProductRepository(session),
        IdempotencyKeyRepository(session),
        RedisCache(fake_redis),  # type: ignore[arg-type]
        EventPublisher(fake_redis),  # type: ignore[arg-type]
    )


def order_of(*items: tuple[int, int]) -> OrderCreate:
    return OrderCreate(items=[OrderItemCreate(product_id=p, quantity=q) for p, q in items])


async def create_user(sessions: SessionFactory, email: str = "buyer@example.com") -> int:
    async with sessions() as session:
        user = await UserRepository(session).create(email, hash_password("password123"))
        await session.commit()
    assert user is not None
    return user.id


async def create_product(sessions: SessionFactory, stock: int, price: str = "10.00") -> int:
    async with sessions() as session:
        product = await ProductRepository(session).create("Product", Decimal(price), stock)
        await session.commit()
    return product.id


async def scalar(sessions: SessionFactory, sql: str, **params: object) -> int:
    async with sessions() as session:
        return int((await session.execute(text(sql), params)).scalar_one())


async def stock_of(sessions: SessionFactory, product_id: int) -> int:
    return await scalar(
        sessions, "SELECT stock_quantity FROM products WHERE id = :id", id=product_id
    )


async def place_order(
    sessions: SessionFactory, fake_redis: FakeRedis, user_id: int, data: OrderCreate, key: str
) -> tuple[OrderRead, bool]:
    async with sessions() as session:
        return await build_service(session, fake_redis).create_order(user_id, data, key)


async def test_fifty_parallel_orders_for_ten_items_only_ten_succeed(
    session_factory: SessionFactory, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(session_factory)
    product_id = await create_product(session_factory, stock=10)

    results = await asyncio.gather(
        *(
            place_order(
                session_factory, fake_redis, user_id, order_of((product_id, 1)), str(uuid.uuid4())
            )
            for _ in range(50)
        ),
        return_exceptions=True,
    )

    succeeded = [r for r in results if isinstance(r, tuple)]
    rejected = [r for r in results if isinstance(r, InsufficientStockError)]
    assert len(succeeded) == 10
    assert len(rejected) == 40
    assert await stock_of(session_factory, product_id) == 0
    assert await scalar(session_factory, "SELECT sum(quantity) FROM order_items") == 10


async def test_same_idempotency_key_in_parallel_creates_one_order(
    session_factory: SessionFactory, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(session_factory)
    product_id = await create_product(session_factory, stock=10)
    key = str(uuid.uuid4())

    results = await asyncio.gather(
        *(
            place_order(session_factory, fake_redis, user_id, order_of((product_id, 2)), key)
            for _ in range(20)
        )
    )

    assert len({order.id for order, _ in results}) == 1
    assert sum(not replayed for _, replayed in results) == 1
    assert await stock_of(session_factory, product_id) == 8
    assert await scalar(session_factory, "SELECT count(*) FROM orders") == 1


async def test_reusing_key_with_different_body_is_rejected(
    session_factory: SessionFactory, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(session_factory)
    product_id = await create_product(session_factory, stock=10)

    await place_order(
        session_factory, fake_redis, user_id, order_of((product_id, 1)), "key-00000001"
    )
    with pytest.raises(IdempotencyKeyReusedError):
        await place_order(
            session_factory, fake_redis, user_id, order_of((product_id, 3)), "key-00000001"
        )

    assert await stock_of(session_factory, product_id) == 9


async def test_same_key_is_scoped_per_user(
    session_factory: SessionFactory, fake_redis: FakeRedis
) -> None:
    alice = await create_user(session_factory, "alice@example.com")
    bob = await create_user(session_factory, "bob@example.com")
    product_id = await create_product(session_factory, stock=10)

    first, _ = await place_order(
        session_factory, fake_redis, alice, order_of((product_id, 1)), "shared-key"
    )
    second, replayed = await place_order(
        session_factory, fake_redis, bob, order_of((product_id, 1)), "shared-key"
    )

    assert first.id != second.id
    assert replayed is False
    assert await stock_of(session_factory, product_id) == 8


async def test_failed_order_rolls_back_everything(
    session_factory: SessionFactory, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(session_factory)
    in_stock = await create_product(session_factory, stock=5)
    sold_out = await create_product(session_factory, stock=0)

    with pytest.raises(InsufficientStockError):
        await place_order(
            session_factory,
            fake_redis,
            user_id,
            order_of((in_stock, 2), (sold_out, 1)),
            "key-rollback",
        )
    with pytest.raises(NotFoundError):
        await place_order(session_factory, fake_redis, user_id, order_of((999, 1)), "key-missing")

    assert await stock_of(session_factory, in_stock) == 5
    assert await scalar(session_factory, "SELECT count(*) FROM orders") == 0
    assert await scalar(session_factory, "SELECT count(*) FROM idempotency_keys") == 0


async def test_duplicate_lines_are_merged_and_total_is_computed(
    session_factory: SessionFactory, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(session_factory)
    cheap = await create_product(session_factory, stock=10, price="2.50")
    pricey = await create_product(session_factory, stock=10, price="100.00")

    order, _ = await place_order(
        session_factory,
        fake_redis,
        user_id,
        order_of((pricey, 1), (cheap, 2), (cheap, 1)),
        "key-merge",
    )

    assert [(i.product_id, i.quantity) for i in order.items] == [(cheap, 3), (pricey, 1)]
    assert order.total_price == Decimal("107.50")
    assert order.status == OrderStatus.PENDING


async def test_crossing_multi_item_orders_do_not_deadlock(
    session_factory: SessionFactory, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(session_factory)
    a = await create_product(session_factory, stock=100)
    b = await create_product(session_factory, stock=100)

    await asyncio.wait_for(
        asyncio.gather(
            *(
                place_order(
                    session_factory,
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

    assert await stock_of(session_factory, a) == 60
    assert await stock_of(session_factory, b) == 60


async def test_cancel_returns_reserved_stock_once(
    session_factory: SessionFactory, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(session_factory)
    product_id = await create_product(session_factory, stock=10)
    order, _ = await place_order(
        session_factory, fake_redis, user_id, order_of((product_id, 4)), "key-cancel"
    )

    async def cancel() -> OrderRead:
        async with session_factory() as session:
            return await build_service(session, fake_redis).cancel_order(order.id, user_id)

    results = await asyncio.gather(*(cancel() for _ in range(5)), return_exceptions=True)

    assert sum(isinstance(r, OrderRead) for r in results) == 1
    assert sum(isinstance(r, InvalidOrderStateError) for r in results) == 4
    assert await stock_of(session_factory, product_id) == 10


async def test_cannot_cancel_or_read_someone_elses_order(
    session_factory: SessionFactory, fake_redis: FakeRedis
) -> None:
    owner = await create_user(session_factory, "owner@example.com")
    stranger = await create_user(session_factory, "stranger@example.com")
    product_id = await create_product(session_factory, stock=10)
    order, _ = await place_order(
        session_factory, fake_redis, owner, order_of((product_id, 1)), "key-owner"
    )

    async with session_factory() as session:
        service = build_service(session, fake_redis)
        with pytest.raises(NotFoundError):
            await service.get_order(order.id, stranger)
        with pytest.raises(NotFoundError):
            await service.cancel_order(order.id, stranger)


async def test_pay_confirms_and_confirmed_order_cannot_be_cancelled(
    session_factory: SessionFactory, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(session_factory)
    product_id = await create_product(session_factory, stock=10)
    order, _ = await place_order(
        session_factory, fake_redis, user_id, order_of((product_id, 1)), "key-pay"
    )

    async with session_factory() as session:
        service = build_service(session, fake_redis)
        confirmed = await service.confirm_order(order.id, user_id)
        with pytest.raises(InvalidOrderStateError):
            await service.cancel_order(order.id, user_id)

    assert confirmed.status == OrderStatus.CONFIRMED
    assert confirmed.confirmed_at is not None
    assert await stock_of(session_factory, product_id) == 9


async def test_expired_orders_are_cancelled_and_stock_released(
    session_factory: SessionFactory, fake_redis: FakeRedis
) -> None:
    user_id = await create_user(session_factory)
    product_id = await create_product(session_factory, stock=10)
    expired, _ = await place_order(
        session_factory, fake_redis, user_id, order_of((product_id, 3)), "key-old"
    )
    fresh, _ = await place_order(
        session_factory, fake_redis, user_id, order_of((product_id, 2)), "key-new"
    )
    async with session_factory() as session:
        await session.execute(
            text("UPDATE orders SET expires_at = now() - interval '1 second' WHERE id = :id"),
            {"id": expired.id},
        )
        await session.commit()

    async with session_factory() as session:
        service = build_service(session, fake_redis)
        with pytest.raises(InvalidOrderStateError):
            await service.confirm_order(expired.id, user_id)
        cancelled = await service.expire_orders()
        assert await service.expire_orders() == []
        statuses = {o.id: (await service.get_order(o.id, user_id)).status for o in (expired, fresh)}

    assert cancelled == [expired.id]
    assert statuses == {expired.id: OrderStatus.CANCELLED, fresh.id: OrderStatus.PENDING}
    assert await stock_of(session_factory, product_id) == 8
