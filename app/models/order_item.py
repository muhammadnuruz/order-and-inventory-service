from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(slots=True, frozen=True)
class OrderItem:
    product_id: int
    quantity: int
    unit_price: Decimal

    @classmethod
    def from_record(cls, record: Any) -> OrderItem:
        return cls(
            product_id=record["product_id"],
            quantity=record["quantity"],
            unit_price=record["unit_price"],
        )
