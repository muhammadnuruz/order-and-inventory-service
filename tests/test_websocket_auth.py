from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_access_token, create_refresh_token


def test_ws_connect_with_valid_access_token_succeeds(client: TestClient) -> None:
    token = create_access_token(subject="1")

    with client.websocket_connect(f"/api/v1/ws?token={token}") as websocket:
        websocket.send_text("hello")
        assert websocket.receive_text() == "hello"


def test_ws_connect_without_token_is_rejected(client: TestClient) -> None:
    try:
        with client.websocket_connect("/api/v1/ws"):
            pass
    except WebSocketDisconnect as exc:
        assert exc.code in (1008, 1000, 1006)
    else:
        raise AssertionError("expected the handshake to be rejected")


def test_ws_connect_with_garbage_token_is_closed(client: TestClient) -> None:
    try:
        with client.websocket_connect("/api/v1/ws?token=not-a-jwt"):
            pass
        raised = False
    except WebSocketDisconnect as exc:
        raised = True
        assert exc.code == 1008

    assert raised


def test_ws_connect_with_refresh_token_is_rejected(client: TestClient) -> None:
    refresh = create_refresh_token(subject="1")

    try:
        with client.websocket_connect(f"/api/v1/ws?token={refresh}"):
            pass
        raised = False
    except WebSocketDisconnect as exc:
        raised = True
        assert exc.code == 1008

    assert raised
