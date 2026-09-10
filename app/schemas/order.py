from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class OrderItemRequest(BaseModel):
    product_id: UUID
    quantity: int = Field(gt=0)


class CreateOrderRequest(BaseModel):
    items: list[OrderItemRequest] = Field(min_length=1)


class OrderItemResponse(BaseModel):
    product_id: UUID
    quantity: int
    unit_price: float


class OrderResponse(BaseModel):
    id: UUID
    user_id: UUID
    status: str
    total_price: float
    items: list[OrderItemResponse]
    created_at: datetime
    expires_at: datetime | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
