from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncGenerator, Iterator

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.db.database import create_pool
from app.main import app
from tests.fakes import FakeRedis

TABLES = "users, products, orders, order_items, idempotency_keys"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


def _migrate(url: str) -> None:
    env = {**os.environ, "SYNC_DATABASE_URL": url.replace("postgresql://", "postgresql+psycopg://")}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=env,
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

        container = PostgresContainer("postgres:16", driver=None).start()
    except Exception as exc:
        pytest.skip(f"TEST_DATABASE_URL is not set and docker is not available: {exc}")

    try:
        url = container.get_connection_url()
        _migrate(url)
        yield url
    finally:
        container.stop()


@pytest.fixture
async def db_pool(database_url: str) -> AsyncGenerator[asyncpg.Pool, None]:
    pool = await create_pool(database_url)
    await pool.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
    yield pool
    await pool.close()
