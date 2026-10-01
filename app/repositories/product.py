from __future__ import annotations

from decimal import Decimal

import asyncpg

from app.models.product import Product

_COLUMNS = "id, name, price, stock_quantity, created_at, updated_at"


class ProductRepository:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def create(self, name: str, price: Decimal, stock_quantity: int) -> Product:
        record = await self.conn.fetchrow(
            f"""
            INSERT INTO products (name, price, stock_quantity)
            VALUES ($1, $2, $3)
            RETURNING {_COLUMNS}
            """,
            name,
            price,
            stock_quantity,
        )
        return Product.from_record(record)

    async def get(self, product_id: int) -> Product | None:
        record = await self.conn.fetchrow(
            f"SELECT {_COLUMNS} FROM products WHERE id = $1", product_id
        )
        return Product.from_record(record) if record else None

    async def list(self, skip: int, limit: int) -> list[Product]:
        records = await self.conn.fetch(
            f"SELECT {_COLUMNS} FROM products ORDER BY id DESC OFFSET $1 LIMIT $2",
            skip,
            limit,
        )
        return [Product.from_record(record) for record in records]

    async def count(self) -> int:
        return await self.conn.fetchval("SELECT count(*) FROM products")
