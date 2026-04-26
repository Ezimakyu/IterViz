"""Tests for the WebSocket connection manager and broadcasts."""

from __future__ import annotations

import asyncio

import pytest

from app import ws as ws_svc
from app.schemas import NodeStatus


class FakeWebSocket:
    """Minimal stand-in for ``starlette.WebSocket``."""

    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[str] = []
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, data: str) -> None:
        if self.closed:
            raise RuntimeError("closed")
        self.sent.append(data)


@pytest.fixture(autouse=True)
def _reset_manager() -> None:
    ws_svc.manager.reset()
    yield
    ws_svc.manager.reset()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.mark.asyncio
async def test_connect_disconnect_lifecycle() -> None:
    sock = FakeWebSocket()

    await ws_svc.manager.connect("session-x", sock)
    assert sock.accepted
    assert ws_svc.manager.get_connection_count("session-x") == 1

    await ws_svc.manager.disconnect("session-x", sock)
    assert ws_svc.manager.get_connection_count("session-x") == 0


@pytest.mark.asyncio
async def test_broadcast_sends_to_all_connections() -> None:
    a = FakeWebSocket()
    b = FakeWebSocket()
    await ws_svc.manager.connect("s", a)
    await ws_svc.manager.connect("s", b)

    await ws_svc.broadcast_node_status_changed(
        "s", "node-1", NodeStatus.IN_PROGRESS
    )

    assert len(a.sent) == 1
    assert len(b.sent) == 1
    assert "node_status_changed" in a.sent[0]
    assert "node-1" in a.sent[0]


@pytest.mark.asyncio
async def test_broadcast_skips_other_sessions() -> None:
    a = FakeWebSocket()
    b = FakeWebSocket()
    await ws_svc.manager.connect("s1", a)
    await ws_svc.manager.connect("s2", b)

    await ws_svc.broadcast_implementation_complete(
        "s1", success=True, nodes_implemented=3, nodes_failed=0
    )

    assert len(a.sent) == 1
    assert len(b.sent) == 0
