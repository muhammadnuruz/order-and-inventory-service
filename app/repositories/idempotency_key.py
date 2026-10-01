from __future__ import annotations

from typing import Any

import asyncpg

from app.models.idempotency_key import IdempotencyKey


class IdempotencyKeyRepository:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def claim(self, user_id: int, key: str, request_hash: str) -> int | None:
        return await self.conn.fetchval(
            """
            INSERT INTO idempotency_keys (user_id, key, request_hash, status)
            VALUES ($1, $2, $3, 'processing')
            ON CONFLICT ON CONSTRAINT uq_idempotency_keys_user_id_key DO NOTHING
            RETURNING id
            """,
            user_id,
            key,
            request_hash,
        )

    async def get(self, user_id: int, key: str) -> IdempotencyKey | None:
        record = await self.conn.fetchrow(
            """
            SELECT id, user_id, key, request_hash, status, response_code, response_body,
                   order_id, created_at
            FROM idempotency_keys
            WHERE user_id = $1 AND key = $2
            """,
            user_id,
            key,
        )
        return IdempotencyKey.from_record(record) if record else None

    async def complete(
        self, key_id: int, response_code: int, response_body: dict[str, Any], order_id: int
    ) -> None:
        await self.conn.execute(
            """
            UPDATE idempotency_keys
            SET status = 'completed', response_code = $2, response_body = $3, order_id = $4
            WHERE id = $1
            """,
            key_id,
            response_code,
            response_body,
            order_id,
        )

    async def delete_older_than(self, hours: int) -> int:
        result = await self.conn.execute(
            "DELETE FROM idempotency_keys WHERE created_at < now() - make_interval(hours => $1)",
            hours,
        )
        return int(result.split()[-1])
