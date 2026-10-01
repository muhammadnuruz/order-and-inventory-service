from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.exceptions import AuthError
from app.core.security import decode_token
from app.websocket.manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None) -> None:
    try:
        if token is None:
            raise AuthError("missing token")
        decode_token(token, expected_type="access")
    except AuthError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            await manager.broadcast(message)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
