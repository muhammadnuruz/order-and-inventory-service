from __future__ import annotations

import asyncio
import json
from typing import Any

from redis import asyncio as redis
from redis.exceptions import RedisError

from app.core.logging import get_logger
from app.websocket.manager import ConnectionManager

log = get_logger(__name__)

EVENTS_CHANNEL = "ws:events"


class EventPublisher:
    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    async def publish(self, event: dict[str, Any]) -> None:
        try:
            await self.client.publish(EVENTS_CHANNEL, json.dumps(event))
        except RedisError:
            log.warning("events.publish_failed", event_type=event.get("event"))

    async def stock_changed(self, stock: dict[int, int]) -> None:
        for product_id, stock_quantity in sorted(stock.items()):
            await self.publish(
                {"event": "stock_changed", "product_id": product_id, "stock_quantity": stock_quantity}
            )


async def listen_for_events(client: redis.Redis, manager: ConnectionManager) -> None:
    """Forwards events from every app process (and the worker) to local websocket clients."""
    while True:
        try:
            async with client.pubsub() as pubsub:
                await pubsub.subscribe(EVENTS_CHANNEL)
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        await manager.broadcast(message["data"])
        except asyncio.CancelledError:
            raise
        except RedisError:
            log.warning("events.listener_disconnected")
            await asyncio.sleep(1)
