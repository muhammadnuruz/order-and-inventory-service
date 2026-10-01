from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True, frozen=True)
class User:
    id: int
    email: str
    hashed_password: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: Any) -> User:
        return cls(**dict(record))
