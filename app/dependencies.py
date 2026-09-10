from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import UnauthorizedError
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> UUID:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Missing Bearer token")
    claims = decode_access_token(credentials.credentials)
    try:
        return UUID(claims["sub"])
    except (KeyError, ValueError):
        raise UnauthorizedError("Invalid token subject")
