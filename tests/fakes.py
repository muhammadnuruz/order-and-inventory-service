from __future__ import annotations

from typing import Any


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        self.store[key] = str(value)

    async def delete(self, *keys: str) -> int:
        return sum(self.store.pop(key, None) is not None for key in keys)

    async def incr(self, key: str) -> int:
        value = int(self.store.get(key, "0")) + 1
        self.store[key] = str(value)
        return value

    async def exists(self, key: str) -> int:
        return int(key in self.store)

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 0
