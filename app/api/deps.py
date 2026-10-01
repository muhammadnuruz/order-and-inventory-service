from __future__ import annotations

import re

import asyncpg
from fastapi import Depends, Header
from fastapi.security import OAuth2PasswordBearer

from app.cache.cache import RedisCache
from app.cache.redis import is_jti_denied, redis_client
from app.core.config import settings
from app.core.exceptions import AuthError, InvalidIdempotencyKeyError
from app.core.security import decode_token
from app.db.database import get_connection
from app.models.user import User
from app.repositories.idempotency_key import IdempotencyKeyRepository
from app.repositories.order import OrderRepository
from app.repositories.product import ProductRepository
from app.repositories.user import UserRepository
from app.schemas.token import TokenPayload
from app.services.auth import AuthService
from app.services.order import OrderService
from app.services.product import ProductService
from app.websocket.events import EventPublisher

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[\x21-\x7e]{8,255}$")


def get_user_repo(conn: asyncpg.Connection = Depends(get_connection)) -> UserRepository:
    return UserRepository(conn)


def get_cache() -> RedisCache:
    return RedisCache(redis_client)


def get_product_service(
    conn: asyncpg.Connection = Depends(get_connection),
    cache: RedisCache = Depends(get_cache),
) -> ProductService:
    return ProductService(ProductRepository(conn), cache)


def get_order_service(
    conn: asyncpg.Connection = Depends(get_connection),
    cache: RedisCache = Depends(get_cache),
) -> OrderService:
    return OrderService(
        conn,
        OrderRepository(conn),
        ProductRepository(conn),
        IdempotencyKeyRepository(conn),
        cache,
        EventPublisher(redis_client),
    )


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


def get_idempotency_key(
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> str:
    if idempotency_key is None:
        raise InvalidIdempotencyKeyError("Idempotency-Key header is required")
    if not _IDEMPOTENCY_KEY_PATTERN.match(idempotency_key):
        raise InvalidIdempotencyKeyError(
            "Idempotency-Key must be 8-255 printable ASCII characters without spaces"
        )
    return idempotency_key
