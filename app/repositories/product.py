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

    async def exists(self, product_id: int) -> bool:
        return await self.conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM products WHERE id = $1)", product_id
        )

    async def reserve_stock(self, product_id: int, quantity: int) -> tuple[Decimal, int] | None:
        record = await self.conn.fetchrow(
            """
            UPDATE products
            SET stock_quantity = stock_quantity - $2
            WHERE id = $1 AND stock_quantity >= $2
            RETURNING price, stock_quantity
            """,
            product_id,
            quantity,
        )
        return (record["price"], record["stock_quantity"]) if record else None

    async def release_stock_for_orders(self, order_ids: list[int]) -> dict[int, int]:
        await self.conn.execute(
            """
            SELECT id FROM products
            WHERE id IN (SELECT product_id FROM order_items WHERE order_id = ANY($1::int[]))
            ORDER BY id
            FOR UPDATE
            """,
            order_ids,
        )
        records = await self.conn.fetch(
            """
            UPDATE products AS p
            SET stock_quantity = p.stock_quantity + r.quantity
            FROM (
                SELECT product_id, sum(quantity) AS quantity
                FROM order_items
                WHERE order_id = ANY($1::int[])
                GROUP BY product_id
            ) AS r
            WHERE p.id = r.product_id
            RETURNING p.id, p.stock_quantity
            """,
            order_ids,
        )
        return {record["id"]: record["stock_quantity"] for record in records}
