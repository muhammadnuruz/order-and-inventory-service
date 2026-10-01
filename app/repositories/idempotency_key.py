from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency_key import IdempotencyKey, IdempotencyStatus


class IdempotencyKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(self, user_id: int, key: str, request_hash: str) -> int | None:
        stmt = (
            insert(IdempotencyKey)
            .values(
                user_id=user_id,
                key=key,
                request_hash=request_hash,
                status=IdempotencyStatus.PROCESSING,
            )
            .on_conflict_do_nothing(constraint="uq_idempotency_keys_user_id_key")
            .returning(IdempotencyKey.id)
        )
        return await self.session.scalar(stmt)

    async def get(self, user_id: int, key: str) -> IdempotencyKey | None:
        result = await self.session.execute(
            select(IdempotencyKey)
            .where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def complete(
        self, key_id: int, response_code: int, response_body: dict[str, Any], order_id: int
    ) -> None:
        await self.session.execute(
            update(IdempotencyKey)
            .where(IdempotencyKey.id == key_id)
            .values(
                status=IdempotencyStatus.COMPLETED,
                response_code=response_code,
                response_body=response_body,
                order_id=order_id,
            )
            .execution_options(synchronize_session=False)
        )

    async def delete_older_than(self, hours: int) -> int:
        result = await self.session.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.created_at < func.now() - timedelta(hours=hours)
            )
        )
        return result.rowcount  # type: ignore[attr-defined]
