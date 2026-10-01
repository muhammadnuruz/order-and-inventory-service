from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import AsyncGenerator

import asyncpg
import httpx
import pytest

from app.db import database
from app.main import app
from tests.fakes import FakeRedis


@pytest.fixture
async def api(
    db_pool: asyncpg.Pool, fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[httpx.AsyncClient, None]:
    monkeypatch.setattr(database, "_pool", db_pool)
    monkeypatch.setattr("app.api.deps.redis_client", fake_redis)
    monkeypatch.setattr("app.cache.redis.redis_client", fake_redis)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def auth_headers(api: httpx.AsyncClient, email: str = "buyer@example.com") -> dict[str, str]:
    credentials = {"email": email, "password": "password123"}
    assert (await api.post("/api/v1/auth/register", json=credentials)).status_code == 201
    response = await api.post(
        "/api/v1/auth/login", data={"username": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def create_product(api: httpx.AsyncClient, headers: dict[str, str], stock: int) -> int:
    response = await api.post(
        "/api/v1/products",
        json={"name": "Keyboard", "price": "49.90", "stock_quantity": stock},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_order_endpoints_require_auth(api: httpx.AsyncClient) -> None:
    assert (await api.post("/api/v1/orders", json={"items": []})).status_code == 401
    assert (await api.get("/api/v1/orders/1")).status_code == 401
    assert (await api.post("/api/v1/products", json={})).status_code == 401


@pytest.mark.parametrize("key", [None, "short", "has space in it", "x" * 256])
async def test_invalid_idempotency_key_is_rejected(api: httpx.AsyncClient, key: str | None) -> None:
    headers = await auth_headers(api)
    product_id = await create_product(api, headers, stock=5)
    if key is not None:
        headers["Idempotency-Key"] = key

    response = await api.post(
        "/api/v1/orders",
        json={"items": [{"product_id": product_id, "quantity": 1}]},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_idempotency_key"


async def test_retry_with_same_key_replays_response(api: httpx.AsyncClient) -> None:
    headers = await auth_headers(api)
    product_id = await create_product(api, headers, stock=5)
    headers["Idempotency-Key"] = str(uuid.uuid4())
    body = {"items": [{"product_id": product_id, "quantity": 2}]}

    first = await api.post("/api/v1/orders", json=body, headers=headers)
    second = await api.post("/api/v1/orders", json=body, headers=headers)
    product = await api.get(f"/api/v1/products/{product_id}")

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert "Idempotent-Replayed" not in first.headers
    assert second.headers["Idempotent-Replayed"] == "true"
    assert product.json()["stock_quantity"] == 3


async def test_fifty_parallel_requests_over_http(api: httpx.AsyncClient) -> None:
    headers = await auth_headers(api)
    product_id = await create_product(api, headers, stock=10)
    body = {"items": [{"product_id": product_id, "quantity": 1}]}

    responses = await asyncio.gather(
        *(
            api.post(
                "/api/v1/orders",
                json=body,
                headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            )
            for _ in range(50)
        )
    )

    assert Counter(r.status_code for r in responses) == {201: 10, 409: 40}
    product = await api.get(f"/api/v1/products/{product_id}")
    assert product.json()["stock_quantity"] == 0


async def test_order_lifecycle(api: httpx.AsyncClient, fake_redis: FakeRedis) -> None:
    headers = await auth_headers(api)
    product_id = await create_product(api, headers, stock=10)
    created = await api.post(
        "/api/v1/orders",
        json={"items": [{"product_id": product_id, "quantity": 4}]},
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = created.json()["id"]

    assert (await api.get(f"/api/v1/orders/{order_id}", headers=headers)).json()[
        "status"
    ] == "pending"
    cancelled = await api.post(f"/api/v1/orders/{order_id}/cancel", headers=headers)
    again = await api.post(f"/api/v1/orders/{order_id}/cancel", headers=headers)
    fetched = await api.get(f"/api/v1/orders/{order_id}", headers=headers)
    product = await api.get(f"/api/v1/products/{product_id}")

    assert cancelled.json()["status"] == "cancelled"
    assert again.status_code == 409
    assert fetched.json()["status"] == "cancelled"
    assert product.json()["stock_quantity"] == 10
    assert any('"stock_changed"' in message for _, message in fake_redis.published)


async def test_other_users_order_is_not_found(api: httpx.AsyncClient) -> None:
    owner = await auth_headers(api, "owner@example.com")
    stranger = await auth_headers(api, "stranger@example.com")
    product_id = await create_product(api, owner, stock=10)
    created = await api.post(
        "/api/v1/orders",
        json={"items": [{"product_id": product_id, "quantity": 1}]},
        headers={**owner, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = created.json()["id"]

    assert (await api.get(f"/api/v1/orders/{order_id}", headers=owner)).status_code == 200
    assert (await api.get(f"/api/v1/orders/{order_id}", headers=stranger)).status_code == 404
    assert (await api.post(f"/api/v1/orders/{order_id}/pay", headers=stranger)).status_code == 404
