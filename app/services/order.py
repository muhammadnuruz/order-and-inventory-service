from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from typing import NoReturn

import asyncpg
from fastapi import status

from app.cache.cache import RedisCache, order_key
from app.core.config import settings
from app.core.exceptions import (
    IdempotencyInProgressError,
    IdempotencyKeyReusedError,
    InsufficientStockError,
    InvalidOrderStateError,
    NotFoundError,
)
from app.models.idempotency_key import IdempotencyStatus
from app.models.order import Order
from app.models.order_item import OrderItem
from app.repositories.idempotency_key import IdempotencyKeyRepository
from app.repositories.order import OrderRepository
from app.repositories.product import ProductRepository
from app.schemas.order import OrderCreate, OrderRead
from app.websocket.events import EventPublisher


def request_fingerprint(data: OrderCreate) -> str:
    payload = json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def merge_items(data: OrderCreate) -> dict[int, int]:
    quantities: dict[int, int] = defaultdict(int)
    for item in data.items:
        quantities[item.product_id] += item.quantity
    return dict(sorted(quantities.items()))


class OrderService:
    def __init__(
        self,
        conn: asyncpg.Connection,
        orders: OrderRepository,
        products: ProductRepository,
        idempotency_keys: IdempotencyKeyRepository,
        cache: RedisCache,
        events: EventPublisher,
    ) -> None:
        self.conn = conn
        self.orders = orders
        self.products = products
        self.idempotency_keys = idempotency_keys
        self.cache = cache
        self.events = events

    async def create_order(
        self, user_id: int, data: OrderCreate, idempotency_key: str
    ) -> tuple[OrderRead, bool]:
        request_hash = request_fingerprint(data)

        async with self.conn.transaction():
            # A concurrent request with the same key blocks here until the first one commits.
            key_id = await self.idempotency_keys.claim(user_id, idempotency_key, request_hash)
            if key_id is None:
                return await self._replay(user_id, idempotency_key, request_hash), True

            items: list[OrderItem] = []
            stock: dict[int, int] = {}
            # Sorted by product id so concurrent orders lock rows in the same order (no deadlocks).
            for product_id, quantity in merge_items(data).items():
                reserved = await self.products.reserve_stock(product_id, quantity)
                if reserved is None:
                    if not await self.products.exists(product_id):
                        raise NotFoundError(f"product {product_id} not found")
                    raise InsufficientStockError(f"not enough stock for product {product_id}")
                unit_price, stock[product_id] = reserved
                items.append(OrderItem(product_id, quantity, unit_price))

            total = sum((item.unit_price * item.quantity for item in items), Decimal("0"))
            order = await self.orders.create(
                user_id, total, settings.ORDER_EXPIRE_MINUTES, items
            )
            body = OrderRead.model_validate(order)
            await self.idempotency_keys.complete(
                key_id, status.HTTP_201_CREATED, body.model_dump(mode="json"), order.id
            )

        await self._after_stock_change(stock)
        return body, False

    async def get_order(self, order_id: int, user_id: int) -> OrderRead:
        cached = await self.cache.get_json(order_key(order_id))
        if cached is not None:
            if cached["user_id"] != user_id:
                raise NotFoundError("order not found")
            return OrderRead.model_validate(cached["order"])

        order = await self.orders.get(order_id)
        if order is None or order.user_id != user_id:
            raise NotFoundError("order not found")

        body = OrderRead.model_validate(order)
        await self.cache.set_json(
            order_key(order_id),
            {"user_id": order.user_id, "order": body.model_dump(mode="json")},
            settings.ORDER_CACHE_TTL_SECONDS,
        )
        return body

    async def cancel_order(self, order_id: int, user_id: int) -> OrderRead:
        async with self.conn.transaction():
            order = await self.orders.cancel_pending(order_id, user_id)
            if order is None:
                await self._raise_for_state(order_id, user_id, "cancelled")
            stock = await self.products.release_stock_for_orders([order_id])

        await self.cache.delete(order_key(order_id))
        await self._after_stock_change(stock)
        return OrderRead.model_validate(order)

    async def confirm_order(self, order_id: int, user_id: int) -> OrderRead:
        order = await self.orders.confirm_pending(order_id, user_id)
        if order is None:
            await self._raise_for_state(order_id, user_id, "confirmed")

        await self.cache.delete(order_key(order_id))
        return OrderRead.model_validate(order)

    async def expire_orders(self, batch_size: int = 100) -> list[int]:
        async with self.conn.transaction():
            order_ids = await self.orders.lock_expired_pending(batch_size)
            if not order_ids:
                return []
            stock = await self.products.release_stock_for_orders(order_ids)
            cancelled = await self.orders.cancel_many(order_ids)

        await self.cache.delete(*(order_key(order_id) for order_id in cancelled))
        await self._after_stock_change(stock)
        return cancelled

    async def _replay(self, user_id: int, key: str, request_hash: str) -> OrderRead:
        existing = await self.idempotency_keys.get(user_id, key)
        if existing is None or existing.status != IdempotencyStatus.COMPLETED:
            raise IdempotencyInProgressError(
                "a request with this Idempotency-Key is still being processed",
                retry_after_seconds=1,
            )
        if existing.request_hash != request_hash:
            raise IdempotencyKeyReusedError(
                "this Idempotency-Key was already used with a different request body"
            )
        return OrderRead.model_validate(existing.response_body)

    async def _raise_for_state(self, order_id: int, user_id: int, target: str) -> NoReturn:
        order: Order | None = await self.orders.get(order_id)
        if order is None or order.user_id != user_id:
            raise NotFoundError("order not found")
        if order.status == "pending":
            raise InvalidOrderStateError("order has expired and can no longer be paid")
        raise InvalidOrderStateError(f"order is {order.status}, it cannot be {target}")

    async def _after_stock_change(self, stock: dict[int, int]) -> None:
        await self.cache.invalidate_products(list(stock))
        await self.events.stock_changed(stock)
