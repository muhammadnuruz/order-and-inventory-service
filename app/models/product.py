from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(slots=True, frozen=True)
class Product:
    id: int
    name: str
    price: Decimal
    stock_quantity: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: Any) -> Product:
        return cls(**dict(record))
