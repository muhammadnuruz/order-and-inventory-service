import json
from uuid import UUID

from app.config import get_settings
from app.db import transaction
from app.errors import NotFoundError
from app.redis_client import get_redis
from app.repositories import product_repo
from app.schemas.product import ProductResponse


def _cache_key(product_id: UUID) -> str:
    return f"product:{product_id}"


def _to_response(row: dict) -> ProductResponse:
    return ProductResponse(
        id=row["id"],
        name=row["name"],
        price=row["price"],
        stock_quantity=row["stock_quantity"],
    )


async def create_product(
    name: str, price: float, stock_quantity: int
) -> ProductResponse:
    async with transaction() as conn:
        row = await product_repo.create_product(conn, name, price, stock_quantity)
    return _to_response(row)


async def get_product(product_id: UUID) -> ProductResponse:
    redis = get_redis()
    key = _cache_key(product_id)

    cached = await redis.get(key)
    if cached is not None:
        return ProductResponse(**json.loads(cached))

    async with transaction() as conn:
        row = await product_repo.get_by_id(conn, product_id)
    if row is None:
        raise NotFoundError("Product not found")

    response = _to_response(row)
    await redis.set(
        key,
        json.dumps(response.model_dump(mode="json")),
        ex=get_settings().product_cache_ttl_seconds,
    )
    return response


async def invalidate_product_cache(product_id: UUID) -> None:
    await get_redis().delete(_cache_key(product_id))
