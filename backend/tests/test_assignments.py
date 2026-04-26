"""Tests for the in-memory work-assignments store."""

from __future__ import annotations

import pytest

from app import assignments as assignments_svc
from app.schemas import (
    ActualInterface,
    AssignmentStatus,
    Contract,
)

from .conftest import make_sample_contract


@pytest.fixture(autouse=True)
def _clear() -> None:
    assignments_svc.clear_all()
    yield
    assignments_svc.clear_all()


def _new_assignment(contract: Contract, idx: int = 0):
    node = contract.nodes[idx]
    return assignments_svc.create_assignment(
        session_id="session-1",
        node=node,
        contract_snapshot=contract,
        incoming_interfaces=[],
        outgoing_interfaces=[],
    )


def test_create_assignment_starts_pending(sample_contract: Contract) -> None:
    a = _new_assignment(sample_contract)

    assert a.status == AssignmentStatus.PENDING.value
    assert a.assigned_to is None


def test_get_available_filters_by_status(sample_contract: Contract) -> None:
    _new_assignment(sample_contract, 0)
    _new_assignment(sample_contract, 1)

    available = assignments_svc.get_available_assignments("session-1")

    assert len(available) == 2


def test_claim_marks_in_progress(sample_contract: Contract) -> None:
    a = _new_assignment(sample_contract)

    claimed = assignments_svc.claim_assignment(
        "session-1", a.node_id, "agent-1"
    )

    assert claimed is not None
    assert claimed.status == AssignmentStatus.IN_PROGRESS.value
    assert claimed.assigned_to == "agent-1"


def test_double_claim_returns_none(sample_contract: Contract) -> None:
    a = _new_assignment(sample_contract)

    assignments_svc.claim_assignment("session-1", a.node_id, "agent-1")
    second = assignments_svc.claim_assignment(
        "session-1", a.node_id, "agent-2"
    )

    assert second is None


def test_complete_records_implementation(sample_contract: Contract) -> None:
    a = _new_assignment(sample_contract)
    assignments_svc.claim_assignment("session-1", a.node_id, "agent-1")

    completed = assignments_svc.complete_assignment(
        session_id="session-1",
        node_id=a.node_id,
        agent_id="agent-1",
        file_paths=["foo.py"],
        actual_interface=ActualInterface(exports=["main"]),
    )

    assert completed is not None
    assert completed.status == AssignmentStatus.COMPLETED.value
    assert completed.result is not None
    assert completed.result.implementation.file_paths == ["foo.py"]


def test_complete_wrong_agent_fails(sample_contract: Contract) -> None:
    a = _new_assignment(sample_contract)
    assignments_svc.claim_assignment("session-1", a.node_id, "agent-1")

    result = assignments_svc.complete_assignment(
        session_id="session-1",
        node_id=a.node_id,
        agent_id="agent-2",
        file_paths=["foo.py"],
        actual_interface=ActualInterface(),
    )

    assert result is None


def test_release_resets_to_pending(sample_contract: Contract) -> None:
    a = _new_assignment(sample_contract)
    assignments_svc.claim_assignment("session-1", a.node_id, "agent-1")

    released = assignments_svc.release_assignment(
        "session-1", a.node_id, "agent-1"
    )

    assert released is not None
    assert released.status == AssignmentStatus.PENDING.value
    assert released.assigned_to is None
