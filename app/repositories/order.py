from __future__ import annotations

from decimal import Decimal

import asyncpg

from app.models.order import Order
from app.models.order_item import OrderItem

_COLUMNS = (
    "id, user_id, status, total_price, expires_at, confirmed_at, cancelled_at, "
    "created_at, updated_at"
)


class OrderRepository:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def create(
        self, user_id: int, total_price: Decimal, expire_minutes: int, items: list[OrderItem]
    ) -> Order:
        record = await self.conn.fetchrow(
            f"""
            INSERT INTO orders (user_id, status, total_price, expires_at)
            VALUES ($1, 'pending', $2, now() + make_interval(mins => $3))
            RETURNING {_COLUMNS}
            """,
            user_id,
            total_price,
            expire_minutes,
        )
        await self.conn.execute(
            """
            INSERT INTO order_items (order_id, product_id, quantity, unit_price)
            SELECT $1, product_id, quantity, unit_price
            FROM unnest($2::int[], $3::int[], $4::numeric[]) AS t(product_id, quantity, unit_price)
            """,
            record["id"],
            [item.product_id for item in items],
            [item.quantity for item in items],
            [item.unit_price for item in items],
        )
        return Order.from_record(record, items)

    async def get(self, order_id: int) -> Order | None:
        record = await self.conn.fetchrow(f"SELECT {_COLUMNS} FROM orders WHERE id = $1", order_id)
        if record is None:
            return None
        return Order.from_record(record, await self.get_items(order_id))

    async def get_items(self, order_id: int) -> list[OrderItem]:
        records = await self.conn.fetch(
            """
            SELECT product_id, quantity, unit_price
            FROM order_items
            WHERE order_id = $1
            ORDER BY product_id
            """,
            order_id,
        )
        return [OrderItem.from_record(record) for record in records]

    async def cancel_pending(self, order_id: int, user_id: int) -> Order | None:
        record = await self.conn.fetchrow(
            f"""
            UPDATE orders
            SET status = 'cancelled', cancelled_at = now()
            WHERE id = $1 AND user_id = $2 AND status = 'pending'
            RETURNING {_COLUMNS}
            """,
            order_id,
            user_id,
        )
        if record is None:
            return None
        return Order.from_record(record, await self.get_items(order_id))

    async def confirm_pending(self, order_id: int, user_id: int) -> Order | None:
        record = await self.conn.fetchrow(
            f"""
            UPDATE orders
            SET status = 'confirmed', confirmed_at = now()
            WHERE id = $1 AND user_id = $2 AND status = 'pending' AND expires_at > now()
            RETURNING {_COLUMNS}
            """,
            order_id,
            user_id,
        )
        if record is None:
            return None
        return Order.from_record(record, await self.get_items(order_id))

    async def lock_expired_pending(self, limit: int) -> list[int]:
        records = await self.conn.fetch(
            """
            SELECT id FROM orders
            WHERE status = 'pending' AND expires_at <= now()
            ORDER BY id
            LIMIT $1
            FOR UPDATE SKIP LOCKED
            """,
            limit,
        )
        return [record["id"] for record in records]

    async def cancel_many(self, order_ids: list[int]) -> list[int]:
        records = await self.conn.fetch(
            """
            UPDATE orders
            SET status = 'cancelled', cancelled_at = now()
            WHERE id = ANY($1::int[]) AND status = 'pending'
            RETURNING id
            """,
            order_ids,
        )
        return [record["id"] for record in records]
