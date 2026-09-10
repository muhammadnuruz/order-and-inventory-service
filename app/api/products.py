from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies import get_current_user_id
from app.schemas.product import CreateProductRequest, ProductResponse
from app.services import product_service

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: CreateProductRequest,
    _user_id: UUID = Depends(get_current_user_id),
) -> ProductResponse:
    return await product_service.create_product(
        payload.name, payload.price, payload.stock_quantity
    )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    _user_id: UUID = Depends(get_current_user_id),
) -> ProductResponse:
    return await product_service.get_product(product_id)
