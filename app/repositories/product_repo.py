from uuid import UUID

from psycopg import AsyncConnection


async def create_product(
    conn: AsyncConnection, name: str, price: float, stock_quantity: int
) -> dict:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO products (name, price, stock_quantity)
            VALUES (%s, %s, %s)
            RETURNING id, name, price, stock_quantity, created_at, updated_at
            """,
            (name, price, stock_quantity),
        )
        return await cur.fetchone()


async def get_by_id(conn: AsyncConnection, product_id: UUID) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, name, price, stock_quantity, created_at, updated_at
            FROM products WHERE id = %s
            """,
            (product_id,),
        )
        return await cur.fetchone()


async def reserve_stock(
    conn: AsyncConnection, product_id: UUID, quantity: int
) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE products
            SET stock_quantity = stock_quantity - %s,
                updated_at = now()
            WHERE id = %s AND stock_quantity >= %s
            RETURNING id, name, price, stock_quantity
            """,
            (quantity, product_id, quantity),
        )
        return await cur.fetchone()


async def release_stock(
    conn: AsyncConnection, product_id: UUID, quantity: int
) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE products
            SET stock_quantity = stock_quantity + %s,
                updated_at = now()
            WHERE id = %s
            """,
            (quantity, product_id),
        )
