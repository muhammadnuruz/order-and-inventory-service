from datetime import datetime
from uuid import UUID

from psycopg import AsyncConnection


async def create_order(
    conn: AsyncConnection,
    user_id: UUID,
    total_price: float,
    expires_at: datetime,
) -> dict:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO orders (user_id, status, total_price, expires_at)
            VALUES (%s, 'pending', %s, %s)
            RETURNING id, user_id, status, total_price,
                      created_at, expires_at, confirmed_at, cancelled_at
            """,
            (user_id, total_price, expires_at),
        )
        return await cur.fetchone()


async def add_order_item(
    conn: AsyncConnection,
    order_id: UUID,
    product_id: UUID,
    quantity: int,
    unit_price: float,
) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO order_items (order_id, product_id, quantity, unit_price)
            VALUES (%s, %s, %s, %s)
            """,
            (order_id, product_id, quantity, unit_price),
        )


async def get_order(conn: AsyncConnection, order_id: UUID) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, user_id, status, total_price,
                   created_at, expires_at, confirmed_at, cancelled_at
            FROM orders WHERE id = %s
            """,
            (order_id,),
        )
        return await cur.fetchone()


async def get_items(conn: AsyncConnection, order_id: UUID) -> list[dict]:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT product_id, quantity, unit_price
            FROM order_items WHERE order_id = %s
            ORDER BY product_id
            """,
            (order_id,),
        )
        return await cur.fetchall()


async def confirm_order(conn: AsyncConnection, order_id: UUID) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE orders
            SET status = 'confirmed', confirmed_at = now()
            WHERE id = %s AND status = 'pending'
            RETURNING id, user_id, status, total_price,
                      created_at, expires_at, confirmed_at, cancelled_at
            """,
            (order_id,),
        )
        return await cur.fetchone()


async def cancel_order(conn: AsyncConnection, order_id: UUID) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE orders
            SET status = 'cancelled', cancelled_at = now()
            WHERE id = %s AND status = 'pending'
            RETURNING id, user_id, status, total_price,
                      created_at, expires_at, confirmed_at, cancelled_at
            """,
            (order_id,),
        )
        return await cur.fetchone()


async def find_expired_pending_ids(
    conn: AsyncConnection, now: datetime, limit: int = 100
) -> list[UUID]:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id FROM orders
            WHERE status = 'pending' AND expires_at <= %s
            ORDER BY expires_at
            LIMIT %s
            """,
            (now, limit),
        )
        return [row["id"] for row in await cur.fetchall()]
