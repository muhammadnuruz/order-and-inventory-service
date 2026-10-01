from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, email: str, hashed_password: str) -> User | None:
        stmt = (
            insert(User)
            .values(email=email, hashed_password=hashed_password, is_active=True)
            .on_conflict_do_nothing(index_elements=[User.email])
            .returning(User)
        )
        return await self.session.scalar(stmt)
