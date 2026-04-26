"""Work assignments for Phase 2 implementation.

Assignments are created by the orchestrator after a contract is frozen.
External agents poll for and claim them; internal subagents are walked
through them sequentially by ``orchestrator.run_implementation_internal``.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Optional

from .logger import get_logger
from .schemas import (
    ActualInterface,
    Assignment,
    AssignmentPayload,
    AssignmentResult,
    AssignmentStatus,
    Contract,
    Implementation,
    NeighborInterface,
    Node,
)

log = get_logger(__name__)

# In-memory store: session_id -> assignment_id -> Assignment.
_assignments: dict[str, dict[str, Assignment]] = {}
_lock = threading.Lock()


def create_assignment(
    session_id: str,
    node: Node,
    contract_snapshot: Contract,
    incoming_interfaces: list[NeighborInterface],
    outgoing_interfaces: list[NeighborInterface],
) -> Assignment:
    """Create a new assignment for a node and store it."""
    assignment_id = str(uuid.uuid4())
    assignment = Assignment(
        id=assignment_id,
        session_id=session_id,
        node_id=node.id,
        created_at=datetime.utcnow(),
        status=AssignmentStatus.PENDING,
        payload=AssignmentPayload(
            contract_snapshot=contract_snapshot,
            node=node,
            neighbor_interfaces={
                "incoming": list(incoming_interfaces),
                "outgoing": list(outgoing_interfaces),
            },
        ),
    )

    with _lock:
        _assignments.setdefault(session_id, {})[assignment_id] = assignment

    log.info(
        "assignments.created",
        extra={
            "assignment_id": assignment_id,
            "session_id": session_id,
            "node_id": node.id,
            "node_name": node.name,
        },
    )
    return assignment


def get_assignment(
    session_id: str, assignment_id: str
) -> Optional[Assignment]:
    """Look up a specific assignment by id."""
    with _lock:
        return _assignments.get(session_id, {}).get(assignment_id)


def get_assignments_for_session(session_id: str) -> list[Assignment]:
    """Return every assignment associated with a session."""
    with _lock:
        return list(_assignments.get(session_id, {}).values())


def get_available_assignments(session_id: str) -> list[Assignment]:
    """Return unclaimed (status=pending) assignments for a session."""
    with _lock:
        return [
            a
            for a in _assignments.get(session_id, {}).values()
            if a.status == AssignmentStatus.PENDING
        ]


def get_assignment_for_node(
    session_id: str, node_id: str
) -> Optional[Assignment]:
    """Return the assignment whose ``node_id`` matches."""
    with _lock:
        for assignment in _assignments.get(session_id, {}).values():
            if assignment.node_id == node_id:
                return assignment
    return None


def _find_by_node_locked(
    session_id: str, node_id: str
) -> Optional[Assignment]:
    """Internal helper: look up an assignment by ``node_id``.

    Caller MUST be holding ``_lock``.
    """
    for assignment in _assignments.get(session_id, {}).values():
        if assignment.node_id == node_id:
            return assignment
    return None


def claim_assignment(
    session_id: str, node_id: str, agent_id: str
) -> Optional[Assignment]:
    """Claim a pending assignment for an agent.

    The lookup, status check, and mutation all happen under ``_lock``
    so two concurrent claimers cannot both observe a PENDING assignment
    and double-claim it.

    Returns ``None`` if the assignment doesn't exist or has already been
    claimed by another agent.
    """
    with _lock:
        assignment = _find_by_node_locked(session_id, node_id)
        if assignment is None:
            log.warning(
                "assignments.claim_failed_not_found",
                extra={"session_id": session_id, "node_id": node_id},
            )
            return None

        if assignment.status != AssignmentStatus.PENDING:
            log.warning(
                "assignments.claim_failed_not_available",
                extra={
                    "assignment_id": assignment.id,
                    "current_status": assignment.status,
                    "current_agent": assignment.assigned_to,
                },
            )
            return None

        assignment.assigned_to = agent_id
        assignment.assigned_at = datetime.utcnow()
        assignment.status = AssignmentStatus.IN_PROGRESS

    log.info(
        "assignments.claimed",
        extra={
            "assignment_id": assignment.id,
            "node_id": node_id,
            "agent_id": agent_id,
        },
    )
    return assignment


def complete_assignment(
    session_id: str,
    node_id: str,
    agent_id: str,
    file_paths: list[str],
    actual_interface: ActualInterface,
    notes: Optional[str] = None,
    duration_ms: int = 0,
) -> Optional[Assignment]:
    """Mark an assignment as completed and attach the implementation.

    Returns ``None`` when the assignment is missing or claimed by a
    different agent than the one submitting.
    """
    with _lock:
        assignment = _find_by_node_locked(session_id, node_id)
        if assignment is None:
            return None

        if assignment.assigned_to != agent_id:
            log.warning(
                "assignments.complete_wrong_agent",
                extra={
                    "assignment_id": assignment.id,
                    "expected_agent": assignment.assigned_to,
                    "actual_agent": agent_id,
                },
            )
            return None

        now = datetime.utcnow()
        assignment.status = AssignmentStatus.COMPLETED
        assignment.result = AssignmentResult(
            implementation=Implementation(
                file_paths=list(file_paths),
                notes=notes,
                actual_interface=actual_interface,
                completed_at=now,
            ),
            completed_at=now,
            duration_ms=duration_ms,
        )

    log.info(
        "assignments.completed",
        extra={
            "assignment_id": assignment.id,
            "node_id": node_id,
            "file_count": len(file_paths),
            "duration_ms": duration_ms,
        },
    )
    return assignment


def release_assignment(
    session_id: str, node_id: str, agent_id: str
) -> Optional[Assignment]:
    """Release a claimed assignment so other agents can pick it up."""
    with _lock:
        assignment = _find_by_node_locked(session_id, node_id)
        if assignment is None or assignment.assigned_to != agent_id:
            return None

        assignment.assigned_to = None
        assignment.assigned_at = None
        assignment.status = AssignmentStatus.PENDING

    log.info(
        "assignments.released",
        extra={
            "assignment_id": assignment.id,
            "node_id": node_id,
            "agent_id": agent_id,
        },
    )
    return assignment


def fail_assignment(
    session_id: str, node_id: str
) -> Optional[Assignment]:
    """Mark an assignment as failed (used by the internal orchestrator)."""
    with _lock:
        assignment = _find_by_node_locked(session_id, node_id)
        if assignment is not None:
            assignment.status = AssignmentStatus.FAILED
    if assignment is not None:
        log.warning(
            "assignments.failed",
            extra={"assignment_id": assignment.id, "node_id": node_id},
        )
    return assignment


def clear_session(session_id: str) -> None:
    """Drop all assignments for a session (test helper)."""
    with _lock:
        _assignments.pop(session_id, None)


def clear_all() -> None:
    """Drop all assignments across all sessions (test helper)."""
    with _lock:
        _assignments.clear()


__all__ = [
    "create_assignment",
    "get_assignment",
    "get_assignments_for_session",
    "get_available_assignments",
    "get_assignment_for_node",
    "claim_assignment",
    "complete_assignment",
    "release_assignment",
    "fail_assignment",
    "clear_session",
    "clear_all",
]
