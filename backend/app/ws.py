"""WebSocket endpoint for live Phase 2 updates.

A single ``ConnectionManager`` instance tracks active connections per
session and broadcasts JSON messages as agents work on nodes. Helper
``broadcast_*`` functions wrap each ``WSMessage`` subtype so callers do
not need to instantiate models inline.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import WebSocket

from .logger import get_logger
from .schemas import (
    AgentType,
    ImplementationSubgraph,
    IntegrationMismatch,
    NodeStatus,
    SubgraphNodeStatus,
    WSAgentConnected,
    WSError,
    WSImplementationComplete,
    WSIntegrationResult,
    WSMessage,
    WSNodeClaimed,
    WSNodeProgress,
    WSNodeStatusChanged,
    WSSubgraphCreated,
    WSSubgraphNodeStatusChanged,
)

log = get_logger(__name__)


class ConnectionManager:
    """Manages WebSocket connections per session."""

    def __init__(self) -> None:
        # session_id -> list of active connections
        self._connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection for a session."""
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(session_id, []).append(websocket)
        log.debug(
            "ws.connected",
            extra={
                "session_id": session_id,
                "total_connections": len(self._connections.get(session_id, [])),
            },
        )

    async def disconnect(
        self, session_id: str, websocket: WebSocket
    ) -> None:
        """Remove a WebSocket connection (idempotent)."""
        async with self._lock:
            connections = self._connections.get(session_id)
            if connections is not None:
                try:
                    connections.remove(websocket)
                except ValueError:
                    pass
                if not connections:
                    self._connections.pop(session_id, None)
        log.debug("ws.disconnected", extra={"session_id": session_id})

    async def broadcast(self, session_id: str, message: WSMessage) -> None:
        """Send a JSON-serialized message to all connections for a session."""
        async with self._lock:
            connections = list(self._connections.get(session_id, []))

        if not connections:
            return

        payload = message.model_dump(mode="json")
        data_str = json.dumps(payload)

        log.debug(
            "ws.broadcast",
            extra={
                "session_id": session_id,
                "type": payload.get("type"),
                "recipients": len(connections),
            },
        )

        dead: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_text(data_str)
            except Exception:  # pragma: no cover - defensive
                dead.append(connection)

        for conn in dead:
            await self.disconnect(session_id, conn)

    def get_connection_count(self, session_id: str) -> int:
        """Synchronous accessor for the number of active connections."""
        return len(self._connections.get(session_id, []))

    def reset(self) -> None:
        """Drop all in-memory connections (test helper)."""
        self._connections.clear()


# Global connection manager instance shared across the FastAPI app.
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Broadcast helpers
# ---------------------------------------------------------------------------

async def broadcast_node_status_changed(
    session_id: str,
    node_id: str,
    status: NodeStatus,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> None:
    """Broadcast a node status change."""
    msg = WSNodeStatusChanged(
        node_id=node_id,
        status=status,
        agent_id=agent_id,
        agent_name=agent_name,
    )
    await manager.broadcast(session_id, msg)


async def broadcast_node_claimed(
    session_id: str,
    node_id: str,
    agent_id: str,
    agent_name: str,
) -> None:
    """Broadcast that a node was claimed by an agent."""
    msg = WSNodeClaimed(
        node_id=node_id,
        agent_id=agent_id,
        agent_name=agent_name,
    )
    await manager.broadcast(session_id, msg)


async def broadcast_node_progress(
    session_id: str,
    node_id: str,
    agent_id: str,
    progress: float,
    message: Optional[str] = None,
) -> None:
    """Broadcast a progress update for a node."""
    msg = WSNodeProgress(
        node_id=node_id,
        agent_id=agent_id,
        progress=progress,
        message=message,
    )
    await manager.broadcast(session_id, msg)


async def broadcast_agent_connected(
    session_id: str,
    agent_id: str,
    agent_name: str,
    agent_type: Optional[AgentType] = None,
) -> None:
    """Broadcast that an agent connected to a session."""
    msg = WSAgentConnected(
        agent_id=agent_id,
        agent_name=agent_name,
        agent_type=agent_type,
    )
    await manager.broadcast(session_id, msg)


async def broadcast_implementation_complete(
    session_id: str,
    success: bool,
    nodes_implemented: int,
    nodes_failed: int,
) -> None:
    """Broadcast that the implementation phase finished."""
    msg = WSImplementationComplete(
        success=success,
        nodes_implemented=nodes_implemented,
        nodes_failed=nodes_failed,
    )
    await manager.broadcast(session_id, msg)


async def broadcast_integration_result(
    session_id: str,
    mismatches: list[IntegrationMismatch],
) -> None:
    """Broadcast the integration pass results (mismatches)."""
    msg = WSIntegrationResult(mismatches=list(mismatches))
    await manager.broadcast(session_id, msg)


async def broadcast_error(
    session_id: str,
    message: str,
    recoverable: bool = True,
) -> None:
    """Broadcast a server-side error to clients of a session."""
    msg = WSError(message=message, recoverable=recoverable)
    await manager.broadcast(session_id, msg)


# ---------------------------------------------------------------------------
# M6: subgraph broadcast helpers
# ---------------------------------------------------------------------------


async def broadcast_subgraph_created(
    session_id: str,
    parent_node_id: str,
    subgraph: ImplementationSubgraph,
) -> None:
    """Broadcast that an implementation subgraph was generated."""
    msg = WSSubgraphCreated(
        parent_node_id=parent_node_id,
        subgraph=subgraph,
    )
    await manager.broadcast(session_id, msg)


async def broadcast_subgraph_node_status_changed(
    session_id: str,
    parent_node_id: str,
    subgraph_node_id: str,
    status: SubgraphNodeStatus,
    progress: float,
) -> None:
    """Broadcast a status transition for a subgraph node."""
    msg = WSSubgraphNodeStatusChanged(
        parent_node_id=parent_node_id,
        subgraph_node_id=subgraph_node_id,
        status=status,
        progress=progress,
    )
    await manager.broadcast(session_id, msg)


__all__ = [
    "ConnectionManager",
    "manager",
    "broadcast_node_status_changed",
    "broadcast_node_claimed",
    "broadcast_node_progress",
    "broadcast_agent_connected",
    "broadcast_implementation_complete",
    "broadcast_integration_result",
    "broadcast_error",
    "broadcast_subgraph_created",
    "broadcast_subgraph_node_status_changed",
]


