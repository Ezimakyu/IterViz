"""Per-session WebSocket fan-out.

Glasshouse maintains a single WebSocket endpoint per session at
``/api/v1/sessions/{session_id}/stream``. Backend services broadcast
messages -- subclasses of :class:`~app.schemas.WSMessage` -- and every
connection currently subscribed to that session receives the JSON
representation.

This module is intentionally minimal so M5 can extend it with
node-status, agent-claim, and progress broadcasts without rewriting the
plumbing.
"""

from __future__ import annotations

import asyncio
from typing import Optional

try:  # FastAPI is the runtime dep, but we keep this importable in tests.
    from fastapi import WebSocket, WebSocketDisconnect
except Exception:  # pragma: no cover - fastapi is part of the runtime deps
    WebSocket = object  # type: ignore[assignment]
    WebSocketDisconnect = Exception  # type: ignore[assignment]

from .logger import get_logger
from .schemas import (
    ImplementationSubgraph,
    SubgraphNodeStatus,
    WSMessage,
    WSSubgraphCreated,
    WSSubgraphNodeStatusChanged,
)

log = get_logger(__name__)


class ConnectionManager:
    """Tracks live WebSocket connections per session.

    Connections are kept in a per-session set; broadcast iterates a
    snapshot to avoid mutating the set while sending.
    """

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(session_id, set()).add(websocket)
        log.info(
            "ws.connected",
            extra={
                "session_id": session_id,
                "active_connections": len(self._connections[session_id]),
            },
        )

    async def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            bucket = self._connections.get(session_id)
            if bucket is not None:
                bucket.discard(websocket)
                if not bucket:
                    self._connections.pop(session_id, None)
        log.info("ws.disconnected", extra={"session_id": session_id})

    async def broadcast(self, session_id: str, message: WSMessage) -> int:
        """Send ``message`` to every connection on ``session_id``.

        Returns the number of connections the message was successfully
        delivered to. Failed connections are removed from the pool.
        """

        async with self._lock:
            connections = list(self._connections.get(session_id, ()))

        if not connections:
            return 0

        payload = message.model_dump(mode="json")
        delivered = 0
        stale: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_json(payload)
                delivered += 1
            except Exception as exc:  # pragma: no cover - depends on socket state
                log.warning(
                    "ws.send_failed",
                    extra={"session_id": session_id, "error": str(exc)},
                )
                stale.append(ws)

        if stale:
            async with self._lock:
                bucket = self._connections.get(session_id)
                if bucket is not None:
                    for ws in stale:
                        bucket.discard(ws)
                    if not bucket:
                        self._connections.pop(session_id, None)

        return delivered

    def connection_count(self, session_id: Optional[str] = None) -> int:
        """Diagnostic helper: number of live connections."""

        if session_id is None:
            return sum(len(v) for v in self._connections.values())
        return len(self._connections.get(session_id, ()))


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Broadcast helpers (M6)
# ---------------------------------------------------------------------------


async def broadcast_subgraph_created(
    session_id: str,
    parent_node_id: str,
    subgraph: ImplementationSubgraph,
) -> int:
    msg = WSSubgraphCreated(
        parent_node_id=parent_node_id,
        subgraph=subgraph,
    )
    delivered = await manager.broadcast(session_id, msg)
    log.info(
        "ws.broadcast.subgraph_created",
        extra={
            "session_id": session_id,
            "parent_node_id": parent_node_id,
            "subgraph_id": subgraph.id,
            "delivered_to": delivered,
        },
    )
    return delivered


async def broadcast_subgraph_node_status_changed(
    session_id: str,
    parent_node_id: str,
    subgraph_node_id: str,
    status: SubgraphNodeStatus,
    progress: float,
) -> int:
    msg = WSSubgraphNodeStatusChanged(
        parent_node_id=parent_node_id,
        subgraph_node_id=subgraph_node_id,
        status=status,
        progress=progress,
    )
    delivered = await manager.broadcast(session_id, msg)
    log.info(
        "ws.broadcast.subgraph_node_status",
        extra={
            "session_id": session_id,
            "parent_node_id": parent_node_id,
            "subgraph_node_id": subgraph_node_id,
            "status": status.value if hasattr(status, "value") else status,
            "progress": progress,
            "delivered_to": delivered,
        },
    )
    return delivered


__all__ = [
    "ConnectionManager",
    "manager",
    "broadcast_subgraph_created",
    "broadcast_subgraph_node_status_changed",
]
