from __future__ import annotations

from dataclasses import dataclass, field

from app.websocket.manager import ConnectionManager


@dataclass
class FakeWebSocket:
    sent: list[str] = field(default_factory=list)
    accepted: bool = False
    fail_send: bool = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, message: str) -> None:
        if self.fail_send:
            raise RuntimeError("connection is closed")
        self.sent.append(message)


async def test_connect_accepts_and_tracks_connection() -> None:
    manager = ConnectionManager()
    ws = FakeWebSocket()

    await manager.connect(ws)

    assert ws.accepted is True
    assert ws in manager._active_connections


async def test_broadcast_sends_to_all_connected_clients() -> None:
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await manager.connect(ws1)
    await manager.connect(ws2)

    await manager.broadcast("hello")

    assert ws1.sent == ["hello"]
    assert ws2.sent == ["hello"]


async def test_disconnect_stops_future_broadcasts() -> None:
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await manager.connect(ws1)
    await manager.connect(ws2)

    manager.disconnect(ws1)
    await manager.broadcast("still here")

    assert ws1.sent == []
    assert ws2.sent == ["still here"]


async def test_disconnect_twice_is_a_no_op() -> None:
    manager = ConnectionManager()
    ws = FakeWebSocket()
    await manager.connect(ws)

    manager.disconnect(ws)
    manager.disconnect(ws)  # should not raise

    assert ws not in manager._active_connections


async def test_broadcast_prunes_dead_connections_without_raising() -> None:
    manager = ConnectionManager()
    alive, dead = FakeWebSocket(), FakeWebSocket(fail_send=True)
    await manager.connect(alive)
    await manager.connect(dead)

    await manager.broadcast("ping")

    assert alive.sent == ["ping"]
    assert dead not in manager._active_connections
