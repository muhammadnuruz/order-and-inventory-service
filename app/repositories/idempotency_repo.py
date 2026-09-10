import json
from uuid import UUID

from psycopg import AsyncConnection


async def try_claim(
    conn: AsyncConnection, user_id: UUID, key: str
) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO idempotency_keys (user_id, idempotency_key, status)
            VALUES (%s, %s, 'processing')
            ON CONFLICT (user_id, idempotency_key) DO NOTHING
            RETURNING id, status, order_id, response_code, response_body
            """,
            (user_id, key),
        )
        return await cur.fetchone()


async def get(conn: AsyncConnection, user_id: UUID, key: str) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, status, order_id, response_code, response_body
            FROM idempotency_keys
            WHERE user_id = %s AND idempotency_key = %s
            """,
            (user_id, key),
        )
        return await cur.fetchone()


async def mark_completed(
    conn: AsyncConnection,
    user_id: UUID,
    key: str,
    order_id: UUID,
    response_code: int,
    response_body: dict,
) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE idempotency_keys
            SET status = 'completed',
                order_id = %s,
                response_code = %s,
                response_body = %s
            WHERE user_id = %s AND idempotency_key = %s
            """,
            (order_id, response_code, json.dumps(response_body), user_id, key),
        )
