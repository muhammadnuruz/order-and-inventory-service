from __future__ import annotations

import asyncpg

from app.models.user import User

_COLUMNS = "id, email, hashed_password, is_active, created_at, updated_at"


class UserRepository:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def get(self, user_id: int) -> User | None:
        record = await self.conn.fetchrow(f"SELECT {_COLUMNS} FROM users WHERE id = $1", user_id)
        return User.from_record(record) if record else None

    async def get_by_email(self, email: str) -> User | None:
        record = await self.conn.fetchrow(f"SELECT {_COLUMNS} FROM users WHERE email = $1", email)
        return User.from_record(record) if record else None

    async def create(self, email: str, hashed_password: str) -> User | None:
        record = await self.conn.fetchrow(
            f"""
            INSERT INTO users (email, hashed_password, is_active)
            VALUES ($1, $2, true)
            ON CONFLICT (email) DO NOTHING
            RETURNING {_COLUMNS}
            """,
            email,
            hashed_password,
        )
        return User.from_record(record) if record else None
