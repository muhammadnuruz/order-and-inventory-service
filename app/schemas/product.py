from uuid import UUID

from pydantic import BaseModel, Field


class CreateProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    price: float = Field(gt=0)
    stock_quantity: int = Field(ge=0)


class ProductResponse(BaseModel):
    id: UUID
    name: str
    price: float
    stock_quantity: int
