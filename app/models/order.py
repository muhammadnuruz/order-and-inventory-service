from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.models.order_item import OrderItem


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class Order:
    id: int
    user_id: int
    status: OrderStatus
    total_price: Decimal
    expires_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItem] = field(default_factory=list)

    @classmethod
    def from_record(cls, record: Any, items: list[OrderItem] | None = None) -> Order:
        data = dict(record)
        data["status"] = OrderStatus(data["status"])
        return cls(**data, items=items or [])
