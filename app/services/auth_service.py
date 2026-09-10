from psycopg.errors import UniqueViolation

from app.db import transaction
from app.errors import ConflictError, UnauthorizedError
from app.repositories import user_repo
from app.schemas.auth import TokenResponse, UserResponse
from app.security import create_access_token, hash_password, verify_password


async def register(email: str, password: str) -> UserResponse:
    password_hash = hash_password(password)
    try:
        async with transaction() as conn:
            user = await user_repo.create_user(conn, email, password_hash)
    except UniqueViolation:
        raise ConflictError("A user with this email already exists")
    return UserResponse(id=user["id"], email=user["email"])


async def login(email: str, password: str) -> TokenResponse:
    async with transaction() as conn:
        user = await user_repo.get_by_email(conn, email)

    if user is None or not verify_password(password, user["password_hash"]):
        raise UnauthorizedError("Invalid email or password")

    token = create_access_token(user["id"], user["email"])
    return TokenResponse(access_token=token)
