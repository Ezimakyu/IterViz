"""External agent registry for Phase 2 coordination.

Agents (Devin, Cursor, Claude Code, etc.) register via the API and can
claim nodes to implement. The registry tracks agent status and
heartbeats.

This is intentionally an in-memory store -- M5 is a hackathon-shaped
slim demo path. A production deployment would back this with SQLite
(see ``app.contract`` for the persistence pattern).
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional

from .logger import get_logger
from .schemas import Agent, AgentStatus, AgentType

log = get_logger(__name__)

# In-memory registry. Keyed by agent_id.
_agents: dict[str, Agent] = {}
_lock = threading.Lock()

DISCONNECT_THRESHOLD = timedelta(seconds=60)


def register_agent(name: str, agent_type: AgentType = AgentType.CUSTOM) -> Agent:
    """Register a new external agent."""
    agent_id = str(uuid.uuid4())
    now = datetime.utcnow()
    agent = Agent(
        id=agent_id,
        name=name,
        type=agent_type,
        registered_at=now,
        last_seen_at=now,
        status=AgentStatus.IDLE,
    )
    with _lock:
        _agents[agent_id] = agent
    log.info(
        "agents.registered",
        extra={
            "agent_id": agent_id,
            "agent_name": name,
            "type": agent_type.value if isinstance(agent_type, AgentType) else agent_type,
        },
    )
    return agent


def get_agent(agent_id: str) -> Optional[Agent]:
    """Get an agent by ID, updating ``last_seen_at`` (heartbeat)."""
    with _lock:
        agent = _agents.get(agent_id)
        if agent is None:
            return None
        agent.last_seen_at = datetime.utcnow()
        _check_status(agent)
        return agent


def list_agents() -> list[Agent]:
    """List all registered agents (with stale ones marked disconnected)."""
    with _lock:
        for agent in _agents.values():
            _check_status(agent)
        return list(_agents.values())


def heartbeat(agent_id: str) -> Optional[Agent]:
    """Update an agent's ``last_seen_at`` timestamp."""
    return get_agent(agent_id)


def set_agent_status(
    agent_id: str, status: AgentStatus
) -> Optional[Agent]:
    """Update an agent's high-level status (active/idle)."""
    with _lock:
        agent = _agents.get(agent_id)
        if agent is None:
            return None
        agent.status = status
        agent.last_seen_at = datetime.utcnow()
    log.info(
        "agents.status_changed",
        extra={
            "agent_id": agent_id,
            "status": status.value if isinstance(status, AgentStatus) else status,
        },
    )
    return agent


def set_agent_assignment(
    agent_id: str, assignment_id: Optional[str]
) -> Optional[Agent]:
    """Bind an assignment id (or clear it) on the given agent."""
    with _lock:
        agent = _agents.get(agent_id)
        if agent is None:
            return None
        agent.current_assignment = assignment_id
        agent.status = (
            AgentStatus.ACTIVE if assignment_id else AgentStatus.IDLE
        )
        agent.last_seen_at = datetime.utcnow()
    return agent


def clear_registry() -> None:
    """Test-only helper: drop all registered agents."""
    with _lock:
        _agents.clear()


def _check_status(agent: Agent) -> None:
    """Mark an agent disconnected if it has not heartbeat'd recently."""
    if datetime.utcnow() - agent.last_seen_at > DISCONNECT_THRESHOLD:
        if agent.status != AgentStatus.DISCONNECTED:
            agent.status = AgentStatus.DISCONNECTED
            log.warning(
                "agents.disconnected",
                extra={
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "last_seen": agent.last_seen_at.isoformat(),
                },
            )


__all__ = [
    "register_agent",
    "get_agent",
    "list_agents",
    "heartbeat",
    "set_agent_status",
    "set_agent_assignment",
    "clear_registry",
    "DISCONNECT_THRESHOLD",
]
