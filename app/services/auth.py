from __future__ import annotations

from app.core.exceptions import ConflictError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.token import Token
from app.schemas.user import UserCreate


class AuthService:
    def __init__(self, users: UserRepository) -> None:
        self.users = users

    async def register(self, data: UserCreate) -> User:
        email = data.email.lower()
        user = await self.users.create(email=email, hashed_password=hash_password(data.password))
        if user is None:
            raise ConflictError(f"a user with email {email!r} already exists")
        return user

    async def authenticate(self, email: str, password: str) -> User | None:
        user = await self.users.get_by_email(email.lower())
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    @staticmethod
    def make_token(user: User) -> Token:
        subject = str(user.id)
        return Token(
            access_token=create_access_token(subject=subject),
            refresh_token=create_refresh_token(subject=subject),
        )
