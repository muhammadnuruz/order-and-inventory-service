from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncGenerator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from tests.fakes import FakeRedis

TABLES = "users, products, orders, order_items, idempotency_keys"

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


def _migrate(url: str) -> None:
    sync_url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "SYNC_DATABASE_URL": sync_url},
        capture_output=True,
    )


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        _migrate(url)
        yield url
        return

    try:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16", driver="asyncpg").start()
    except Exception as exc:
        pytest.skip(f"TEST_DATABASE_URL is not set and docker is not available: {exc}")

    try:
        url = container.get_connection_url()
        _migrate(url)
        yield url
    finally:
        container.stop()


@pytest.fixture
async def session_factory(database_url: str) -> AsyncGenerator[SessionFactory, None]:
    engine = create_async_engine(database_url, pool_size=20, max_overflow=0)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
