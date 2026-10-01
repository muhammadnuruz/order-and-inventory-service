from __future__ import annotations

from decimal import Decimal

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order_item import OrderItem
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

    async def exists(self, product_id: int) -> bool:
        return bool(await self.session.scalar(select(exists().where(Product.id == product_id))))

    async def reserve_stock(self, product_id: int, quantity: int) -> tuple[Decimal, int] | None:
        stmt = (
            update(Product)
            .where(Product.id == product_id, Product.stock_quantity >= quantity)
            .values(stock_quantity=Product.stock_quantity - quantity)
            .returning(Product.price, Product.stock_quantity)
            .execution_options(synchronize_session=False)
        )
        row = (await self.session.execute(stmt)).one_or_none()
        return (row.price, row.stock_quantity) if row else None

    async def release_stock_for_orders(self, order_ids: list[int]) -> dict[int, int]:
        product_ids = select(OrderItem.product_id).where(OrderItem.order_id.in_(order_ids))
        await self.session.execute(
            select(Product.id)
            .where(Product.id.in_(product_ids))
            .order_by(Product.id)
            .with_for_update()
        )

        totals = (
            select(OrderItem.product_id, func.sum(OrderItem.quantity).label("quantity"))
            .where(OrderItem.order_id.in_(order_ids))
            .group_by(OrderItem.product_id)
            .subquery()
        )
        stmt = (
            update(Product)
            .where(Product.id == totals.c.product_id)
            .values(stock_quantity=Product.stock_quantity + totals.c.quantity)
            .returning(Product.id, Product.stock_quantity)
            .execution_options(synchronize_session=False)
        )
        rows = (await self.session.execute(stmt)).all()
        return {row.id: row.stock_quantity for row in rows}
