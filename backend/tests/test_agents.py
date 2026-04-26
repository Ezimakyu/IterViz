"""Tests for the in-memory external-agent registry."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app import agents as agents_svc
from app.schemas import AgentStatus, AgentType


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    agents_svc.clear_registry()
    yield
    agents_svc.clear_registry()


def test_register_agent_assigns_id_and_idle_status() -> None:
    agent = agents_svc.register_agent("Devin", AgentType.DEVIN)

    assert agent.id
    assert agent.name == "Devin"
    assert agent.type == AgentType.DEVIN.value
    assert agent.status == AgentStatus.IDLE.value
    assert agent.current_assignment is None


def test_get_agent_updates_last_seen() -> None:
    agent = agents_svc.register_agent("Cursor", AgentType.CURSOR)

    fetched = agents_svc.get_agent(agent.id)
    assert fetched is not None
    assert fetched.last_seen_at >= agent.registered_at


def test_get_agent_unknown_returns_none() -> None:
    assert agents_svc.get_agent("nope") is None


def test_list_agents_returns_all() -> None:
    a1 = agents_svc.register_agent("a")
    a2 = agents_svc.register_agent("b")

    listed = agents_svc.list_agents()

    ids = {a.id for a in listed}
    assert {a1.id, a2.id} <= ids
    assert len(listed) == 2


def test_disconnect_after_threshold() -> None:
    agent = agents_svc.register_agent("a")
    # Simulate a stale agent by rewinding ``last_seen_at``.
    agent.last_seen_at = datetime.utcnow() - timedelta(seconds=120)

    refreshed = agents_svc.list_agents()[0]
    assert refreshed.status == AgentStatus.DISCONNECTED.value


def test_set_agent_status_changes_status() -> None:
    agent = agents_svc.register_agent("a")

    updated = agents_svc.set_agent_status(agent.id, AgentStatus.ACTIVE)

    assert updated is not None
    assert updated.status == AgentStatus.ACTIVE.value


def test_set_agent_assignment_marks_active() -> None:
    agent = agents_svc.register_agent("a")

    updated = agents_svc.set_agent_assignment(agent.id, "task-1")

    assert updated is not None
    assert updated.current_assignment == "task-1"
    assert updated.status == AgentStatus.ACTIVE.value

    cleared = agents_svc.set_agent_assignment(agent.id, None)
    assert cleared is not None
    assert cleared.current_assignment is None
    assert cleared.status == AgentStatus.IDLE.value
