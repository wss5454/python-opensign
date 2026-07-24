"""WebSocket hub for document lifecycle events."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

ws_router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Tracks connected WebSocket clients and broadcasts JSON events."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        await websocket.send_json(
            {
                "event": "connected",
                "message": "Subscribed to WallaceSign document events",
            }
        )

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        dead: List[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


async def emit_document_finished(document) -> None:
    """Fire when every signer/approver has signed and the document is completed."""
    payload = {
        "event": "document.finished",
        "document_id": document.id,
        "status": document.status,
        "title": document.title,
        "filename": document.filename,
        "public_token": document.public_token,
        "completed_at": _iso(getattr(document, "completed_at", None)),
    }
    logger.info(
        "WebSocket document.finished document_id=%s clients=%s",
        document.id,
        manager.connection_count,
    )
    await manager.broadcast(payload)


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Connect to receive live document events.

    When all signers finish a document, clients receive:

    ```json
    {
      "event": "document.finished",
      "document_id": 12,
      "status": "completed",
      "title": "...",
      "filename": "...",
      "public_token": "...",
      "completed_at": "..."
    }
    ```

    Clients may send `{"type":"ping"}` and will receive `{"event":"pong"}`.
    """
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if isinstance(data, dict) and data.get("type") == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
