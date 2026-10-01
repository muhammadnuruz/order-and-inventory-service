from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user, get_idempotency_key, get_order_service
from app.models.user import User
from app.schemas.order import OrderCreate, OrderRead
from app.services.order import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post(
    "",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "Not enough stock, or the same key is still being processed"},
        422: {"description": "Idempotency-Key reused with a different body"},
    },
)
async def create_order(
    data: OrderCreate,
    current_user: User = Depends(get_current_user),
    idempotency_key: str = Depends(get_idempotency_key),
    order_service: OrderService = Depends(get_order_service),
) -> JSONResponse:
    order, replayed = await order_service.create_order(current_user.id, data, idempotency_key)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=order.model_dump(mode="json"),
        headers={"Idempotent-Replayed": "true"} if replayed else None,
    )


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    order_service: OrderService = Depends(get_order_service),
) -> OrderRead:
    return await order_service.get_order(order_id, current_user.id)


@router.post("/{order_id}/cancel", response_model=OrderRead)
async def cancel_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    order_service: OrderService = Depends(get_order_service),
) -> OrderRead:
    return await order_service.cancel_order(order_id, current_user.id)


@router.post("/{order_id}/pay", response_model=OrderRead)
async def pay_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    order_service: OrderService = Depends(get_order_service),
) -> OrderRead:
    return await order_service.confirm_order(order_id, current_user.id)
