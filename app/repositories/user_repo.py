from uuid import UUID

from psycopg import AsyncConnection


async def create_user(conn: AsyncConnection, email: str, password_hash: str) -> dict:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO users (email, password_hash)
            VALUES (%s, %s)
            RETURNING id, email, password_hash, created_at
            """,
            (email, password_hash),
        )
        return await cur.fetchone()


async def get_by_email(conn: AsyncConnection, email: str) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, email, password_hash, created_at FROM users WHERE email = %s",
            (email,),
        )
        return await cur.fetchone()


async def get_by_id(conn: AsyncConnection, user_id: UUID) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, email, password_hash, created_at FROM users WHERE id = %s",
            (user_id,),
        )
        return await cur.fetchone()
