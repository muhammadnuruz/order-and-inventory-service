from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_auth_service, get_current_token
from app.cache.redis import deny_jti, is_jti_denied
from app.core.config import settings
from app.core.exceptions import AuthError
from app.core.rate_limit import limiter
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.db.session import get_session
from app.schemas.token import RefreshRequest, Token, TokenPayload
from app.schemas.user import UserCreate, UserRead
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _remaining_ttl(payload: TokenPayload) -> int:
    if payload.exp is None:
        return 0
    return max(0, payload.exp - int(time.time()))


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT)
async def register(
    request: Request,
    data: UserCreate,
    auth_service: AuthService = Depends(get_auth_service),
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    user = await auth_service.register(data)
    await session.commit()
    return UserRead.model_validate(user)


@router.post("/login", response_model=Token)
@limiter.limit(settings.RATE_LIMIT)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    auth_service: AuthService = Depends(get_auth_service),
) -> Token:
    user = await auth_service.authenticate(form_data.username, form_data.password)
    if user is None:
        raise AuthError("incorrect email or password")
    return auth_service.make_token(user)


@router.post("/refresh", response_model=Token)
async def refresh(data: RefreshRequest) -> Token:
    payload = decode_token(data.refresh_token, expected_type="refresh")
    if payload.sub is None or payload.jti is None:
        raise AuthError("could not validate credentials")
    if await is_jti_denied(payload.jti):
        raise AuthError("could not validate credentials")

    await deny_jti(payload.jti, ttl_seconds=_remaining_ttl(payload))
    return Token(
        access_token=create_access_token(subject=payload.sub),
        refresh_token=create_refresh_token(subject=payload.sub),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: TokenPayload = Depends(get_current_token)) -> None:
    if payload.jti is not None:
        await deny_jti(payload.jti, ttl_seconds=_remaining_ttl(payload))
