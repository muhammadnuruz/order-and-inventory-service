from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class IdempotencyStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"


@dataclass(slots=True, frozen=True)
class IdempotencyKey:
    id: int
    user_id: int
    key: str
    request_hash: str
    status: IdempotencyStatus
    response_code: int | None
    response_body: dict[str, Any] | None
    order_id: int | None
    created_at: datetime

    @classmethod
    def from_record(cls, record: Any) -> IdempotencyKey:
        return cls(
            id=record["id"],
            user_id=record["user_id"],
            key=record["key"],
            request_hash=record["request_hash"],
            status=IdempotencyStatus(record["status"]),
            response_code=record["response_code"],
            response_body=record["response_body"],
            order_id=record["order_id"],
            created_at=record["created_at"],
        )
