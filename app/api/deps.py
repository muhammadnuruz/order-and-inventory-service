from __future__ import annotations

import asyncpg
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.cache.cache import RedisCache
from app.cache.redis import is_jti_denied, redis_client
from app.core.config import settings
from app.core.exceptions import AuthError
from app.core.security import decode_token
from app.db.database import get_connection
from app.models.user import User
from app.repositories.product import ProductRepository
from app.repositories.user import UserRepository
from app.schemas.token import TokenPayload
from app.services.auth import AuthService
from app.services.product import ProductService

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")


def get_user_repo(conn: asyncpg.Connection = Depends(get_connection)) -> UserRepository:
    return UserRepository(conn)


def get_cache() -> RedisCache:
    return RedisCache(redis_client)


def get_product_service(
    conn: asyncpg.Connection = Depends(get_connection),
    cache: RedisCache = Depends(get_cache),
) -> ProductService:
    return ProductService(ProductRepository(conn), cache)


def get_auth_service(users: UserRepository = Depends(get_user_repo)) -> AuthService:
    return AuthService(users)


async def get_current_token(token: str = Depends(_oauth2_scheme)) -> TokenPayload:
    payload = decode_token(token, expected_type="access")
    if payload.jti is not None and await is_jti_denied(payload.jti):
        raise AuthError("could not validate credentials")
    return payload


async def get_current_user(
    payload: TokenPayload = Depends(get_current_token),
    users: UserRepository = Depends(get_user_repo),
) -> User:
    try:
        user_id = int(payload.sub or "")
    except ValueError as exc:
        raise AuthError("could not validate credentials") from exc

    user = await users.get(user_id)
    if user is None or not user.is_active:
        raise AuthError("could not validate credentials")
    return user
