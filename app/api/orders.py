from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status

from app.dependencies import get_current_user_id
from app.schemas.order import CreateOrderRequest, OrderResponse
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: CreateOrderRequest,
    response: Response,
    user_id: UUID = Depends(get_current_user_id),
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        description="Mandatory. Retrying with the same key does not reserve stock twice.",
    ),
) -> OrderResponse:
    result = await order_service.create_order(user_id, payload.items, idempotency_key)
    response.status_code = result.status_code
    return result.order


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
) -> OrderResponse:
    return await order_service.get_order(user_id, order_id)


@router.post("/{order_id}/pay", response_model=OrderResponse)
async def pay_order(
    order_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
) -> OrderResponse:
    return await order_service.pay_order(user_id, order_id)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
) -> OrderResponse:
    return await order_service.cancel_order(user_id, order_id)
