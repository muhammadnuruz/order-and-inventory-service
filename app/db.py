from contextlib import asynccontextmanager
from typing import AsyncIterator

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import get_settings

_pool: AsyncConnectionPool | None = None


async def init_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=2,
            max_size=20,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        await _pool.open()
        await _pool.wait()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("DB pool is not initialised. Call init_pool() first.")
    return _pool


@asynccontextmanager
async def transaction() -> AsyncIterator:
    pool = get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            yield conn
