"""Fires N parallel orders at one product against a running stack.

Usage: python scripts/load_test.py --base-url http://localhost:8080 --requests 50 --stock 10
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections import Counter

import httpx


async def main(base_url: str, requests: int, stock: int) -> int:
    api = f"{base_url}/api/v1"
    email = f"load-{uuid.uuid4().hex[:8]}@example.com"

    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(f"{api}/auth/register", json={"email": email, "password": "password123"})
        login = await client.post(
            f"{api}/auth/login", data={"username": email, "password": "password123"}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        product = await client.post(
            f"{api}/products",
            json={"name": "Load test item", "price": "9.99", "stock_quantity": stock},
            headers=headers,
        )
        product_id = product.json()["id"]
        body = {"items": [{"product_id": product_id, "quantity": 1}]}

        responses = await asyncio.gather(
            *(
                client.post(
                    f"{api}/orders",
                    json=body,
                    headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
                )
                for _ in range(requests)
            )
        )
        left = (await client.get(f"{api}/products/{product_id}")).json()["stock_quantity"]

    counts = Counter(response.status_code for response in responses)
    print(f"product {product_id}: {dict(counts)}, stock left: {left}")
    return 0 if counts[201] == min(requests, stock) and left == max(stock - requests, 0) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--stock", type=int, default=10)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.base_url, args.requests, args.stock)))
