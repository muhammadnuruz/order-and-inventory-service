from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_current_user, get_product_service
from app.models.user import User
from app.schemas.product import ProductCreate, ProductPage, ProductRead
from app.services.product import ProductService

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    current_user: User = Depends(get_current_user),
    product_service: ProductService = Depends(get_product_service),
) -> ProductRead:
    return await product_service.create_product(data)


@router.get("", response_model=ProductPage)
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    product_service: ProductService = Depends(get_product_service),
) -> ProductPage:
    return await product_service.list_products(skip=skip, limit=limit)


@router.get("/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: int,
    product_service: ProductService = Depends(get_product_service),
) -> ProductRead:
    return await product_service.get_product(product_id)
