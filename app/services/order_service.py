import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.config import get_settings
from app.db import transaction
from app.errors import ConflictError, InsufficientStockError, NotFoundError, ValidationError
from app.redis_client import get_redis
from app.repositories import idempotency_repo, order_repo, product_repo
from app.schemas.order import OrderItemResponse, OrderResponse
from app.services import product_service


@dataclass
class OrderResult:
    order: OrderResponse
    status_code: int


def _idem_cache_key(user_id: UUID, key: str) -> str:
    return f"idem:{user_id}:{key}"


def _order_to_response(order_row: dict, item_rows: list[dict]) -> OrderResponse:
    return OrderResponse(
        id=order_row["id"],
        user_id=order_row["user_id"],
        status=order_row["status"],
        total_price=order_row["total_price"],
        items=[
            OrderItemResponse(
                product_id=i["product_id"],
                quantity=i["quantity"],
                unit_price=i["unit_price"],
            )
            for i in item_rows
        ],
        created_at=order_row["created_at"],
        expires_at=order_row["expires_at"],
        confirmed_at=order_row["confirmed_at"],
        cancelled_at=order_row["cancelled_at"],
    )


async def create_order(
    user_id: UUID, items: list, idempotency_key: str
) -> OrderResult:
    redis = get_redis()
    cache_key = _idem_cache_key(user_id, idempotency_key)

    cached = await redis.get(cache_key)
    if cached is not None:
        body = json.loads(cached)
        return OrderResult(order=OrderResponse(**body), status_code=200)

    quantities: dict[UUID, int] = {}
    for item in items:
        quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
    product_ids = sorted(quantities.keys(), key=str)

    async with transaction() as conn:
        claim = await idempotency_repo.try_claim(conn, user_id, idempotency_key)
        if claim is None:
            existing = await idempotency_repo.get(conn, user_id, idempotency_key)
            if existing and existing["status"] == "completed":
                body = existing["response_body"]
                return OrderResult(order=OrderResponse(**body), status_code=200)
            raise ConflictError(
                "A request with this Idempotency-Key is already being processed"
            )

        prices: dict[UUID, float] = {}
        for pid in product_ids:
            product = await product_repo.get_by_id(conn, pid)
            if product is None:
                raise ValidationError(f"Product {pid} does not exist")
            prices[pid] = product["price"]

        for pid in product_ids:
            reserved = await product_repo.reserve_stock(conn, pid, quantities[pid])
            if reserved is None:
                raise InsufficientStockError(
                    f"Insufficient stock for product {pid}"
                )

        total_price = sum(
            prices[pid] * quantities[pid] for pid in product_ids
        )
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=get_settings().order_expiry_seconds
        )
        order_row = await order_repo.create_order(
            conn, user_id, total_price, expires_at
        )
        item_rows = []
        for pid in product_ids:
            await order_repo.add_order_item(
                conn, order_row["id"], pid, quantities[pid], prices[pid]
            )
            item_rows.append(
                {"product_id": pid, "quantity": quantities[pid], "unit_price": prices[pid]}
            )

        response = _order_to_response(order_row, item_rows)
        body = response.model_dump(mode="json")

        await idempotency_repo.mark_completed(
            conn, user_id, idempotency_key, order_row["id"], 201, body
        )

    await redis.set(
        cache_key,
        json.dumps(body),
        ex=get_settings().idempotency_cache_ttl_seconds,
    )
    for pid in product_ids:
        await product_service.invalidate_product_cache(pid)

    return OrderResult(order=response, status_code=201)


async def get_order(user_id: UUID, order_id: UUID) -> OrderResponse:
    async with transaction() as conn:
        order_row = await order_repo.get_order(conn, order_id)
        if order_row is None or order_row["user_id"] != user_id:
            raise NotFoundError("Order not found")
        item_rows = await order_repo.get_items(conn, order_id)
    return _order_to_response(order_row, item_rows)


async def pay_order(user_id: UUID, order_id: UUID) -> OrderResponse:
    async with transaction() as conn:
        order_row = await order_repo.get_order(conn, order_id)
        if order_row is None or order_row["user_id"] != user_id:
            raise NotFoundError("Order not found")

        confirmed = await order_repo.confirm_order(conn, order_id)
        if confirmed is None:
            raise ConflictError(
                f"Order cannot be paid because its status is '{order_row['status']}'"
            )
        item_rows = await order_repo.get_items(conn, order_id)
    return _order_to_response(confirmed, item_rows)


async def cancel_order(user_id: UUID, order_id: UUID) -> OrderResponse:
    async with transaction() as conn:
        order_row = await order_repo.get_order(conn, order_id)
        if order_row is None or order_row["user_id"] != user_id:
            raise NotFoundError("Order not found")

        cancelled = await order_repo.cancel_order(conn, order_id)
        if cancelled is None:
            raise ConflictError(
                f"Order cannot be cancelled because its status is '{order_row['status']}'"
            )

        item_rows = await order_repo.get_items(conn, order_id)
        for item in item_rows:
            await product_repo.release_stock(
                conn, item["product_id"], item["quantity"]
            )

    for item in item_rows:
        await product_service.invalidate_product_cache(item["product_id"])
    return _order_to_response(cancelled, item_rows)


async def expire_pending_orders() -> int:
    now = datetime.now(timezone.utc)
    async with transaction() as conn:
        expired_ids = await order_repo.find_expired_pending_ids(conn, now)

    count = 0
    for order_id in expired_ids:
        released_product_ids: list[UUID] = []
        async with transaction() as conn:
            cancelled = await order_repo.cancel_order(conn, order_id)
            if cancelled is None:
                continue
            item_rows = await order_repo.get_items(conn, order_id)
            for item in item_rows:
                await product_repo.release_stock(
                    conn, item["product_id"], item["quantity"]
                )
                released_product_ids.append(item["product_id"])
        for pid in released_product_ids:
            await product_service.invalidate_product_cache(pid)
        count += 1
    return count
