from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, name: str, price: Decimal, stock_quantity: int) -> Product:
        product = Product(name=name, price=price, stock_quantity=stock_quantity)
        self.session.add(product)
        await self.session.flush()
        await self.session.refresh(product)
        return product

    async def get(self, product_id: int) -> Product | None:
        return await self.session.get(Product, product_id)

    async def get_page(self, skip: int, limit: int) -> list[Product]:
        result = await self.session.execute(
            select(Product).order_by(Product.id.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Product))
        return int(result.scalar_one())
