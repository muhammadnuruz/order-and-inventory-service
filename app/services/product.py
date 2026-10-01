from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.cache import (
    PRODUCTS_LIST_VERSION_KEY,
    RedisCache,
    product_key,
    products_list_key,
)
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.repositories.product import ProductRepository
from app.schemas.product import ProductCreate, ProductPage, ProductRead


class ProductService:
    def __init__(
        self, session: AsyncSession, products: ProductRepository, cache: RedisCache
    ) -> None:
        self.session = session
        self.products = products
        self.cache = cache

    async def create_product(self, data: ProductCreate) -> ProductRead:
        product = await self.products.create(
            name=data.name, price=data.price, stock_quantity=data.stock_quantity
        )
        await self.session.commit()
        await self.cache.bump_version(PRODUCTS_LIST_VERSION_KEY)
        return ProductRead.model_validate(product)

    async def get_product(self, product_id: int) -> ProductRead:
        key = product_key(product_id)
        cached = await self.cache.get_json(key)
        if cached is not None:
            return ProductRead.model_validate(cached)

        product = await self.products.get(product_id)
        if product is None:
            raise NotFoundError("product not found")

        body = ProductRead.model_validate(product)
        await self.cache.set_json(
            key, body.model_dump(mode="json"), settings.PRODUCT_CACHE_TTL_SECONDS
        )
        return body

    async def list_products(self, skip: int, limit: int) -> ProductPage:
        version = await self.cache.get_version(PRODUCTS_LIST_VERSION_KEY)
        key = products_list_key(version, skip, limit)
        cached = await self.cache.get_json(key)
        if cached is not None:
            return ProductPage.model_validate(cached)

        items = await self.products.get_page(skip=skip, limit=limit)
        total = await self.products.count()
        page = ProductPage(
            items=[ProductRead.model_validate(item) for item in items],
            total=total,
            skip=skip,
            limit=limit,
        )
        await self.cache.set_json(
            key, page.model_dump(mode="json"), settings.PRODUCT_LIST_CACHE_TTL_SECONDS
        )
        return page
