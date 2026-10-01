from __future__ import annotations


class AppError(Exception):
    code: str = "error"
    status_code: int = 400

    def __init__(self, message: str, *, headers: dict[str, str] | None = None) -> None:
        self.message = message
        self.headers = headers
        super().__init__(message)


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404


class ConflictError(AppError):
    code = "conflict"
    status_code = 409


class AuthError(AppError):
    code = "unauthorized"
    status_code = 401


class ForbiddenError(AppError):
    code = "forbidden"
    status_code = 403


class InsufficientStockError(AppError):
    code = "insufficient_stock"
    status_code = 409


class InvalidOrderStateError(AppError):
    code = "invalid_order_state"
    status_code = 409


class InvalidIdempotencyKeyError(AppError):
    code = "invalid_idempotency_key"
    status_code = 400


class IdempotencyKeyReusedError(AppError):
    code = "idempotency_key_reused"
    status_code = 422


class IdempotencyInProgressError(AppError):
    code = "idempotency_in_progress"
    status_code = 409

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message, headers={"Retry-After": str(retry_after_seconds)})
