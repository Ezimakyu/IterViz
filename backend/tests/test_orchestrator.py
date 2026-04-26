"""Tests for the Phase 2 orchestrator (freeze + leaf detection)."""

from __future__ import annotations

import pytest

from app import assignments as assignments_svc
from app import contract as contract_svc
from app import orchestrator
from app.schemas import (
    Contract,
    ContractStatus,
    DecidedBy,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
)

from .conftest import make_sample_contract


@pytest.fixture
def session(temp_db, sample_contract: Contract) -> str:
    contract_svc.init_db()
    created = contract_svc.create_session(sample_contract)
    return created.id


@pytest.fixture(autouse=True)
def _clear_assignments() -> None:
    assignments_svc.clear_all()
    yield
    assignments_svc.clear_all()


def test_freeze_sets_status_and_hash(session: str) -> None:
    contract = orchestrator.freeze_contract(session)

    assert contract.meta.status == ContractStatus.VERIFIED.value
    assert contract.meta.frozen_hash
    assert contract.meta.frozen_at is not None


def test_freeze_twice_is_idempotent(session: str) -> None:
    first = orchestrator.freeze_contract(session)
    second = orchestrator.freeze_contract(session)

    assert second.meta.frozen_hash == first.meta.frozen_hash


def test_identify_leaf_nodes_returns_terminal(
    sample_contract: Contract,
) -> None:
    leaves = orchestrator.identify_leaf_nodes(sample_contract)

    leaf_ids = {n.id for n in leaves}
    # The fixture wires UI -> API -> DB; only DB is a leaf.
    db_node = next(n for n in sample_contract.nodes if n.name == "Database")
    assert db_node.id in leaf_ids


def test_identify_leaf_nodes_handles_isolated() -> None:
    n_a = Node(
        id="a",
        name="A",
        kind=NodeKind.SERVICE,
        description="",
        responsibilities=["x"],
        confidence=0.5,
        decided_by=DecidedBy.PROMPT,
    )
    n_b = Node(
        id="b",
        name="B",
        kind=NodeKind.SERVICE,
        description="",
        responsibilities=["y"],
        confidence=0.5,
        decided_by=DecidedBy.PROMPT,
    )
    contract = sample_with_nodes([n_a, n_b], edges=[])

    leaves = orchestrator.identify_leaf_nodes(contract)

    assert {n.id for n in leaves} == {"a", "b"}


def test_get_neighbor_interfaces_returns_in_and_out(
    sample_contract: Contract,
) -> None:
    api = next(n for n in sample_contract.nodes if n.name == "API Server")

    incoming, outgoing = orchestrator.get_neighbor_interfaces(
        api, sample_contract
    )

    assert len(incoming) == 1
    assert incoming[0].node_name == "Web UI"
    assert len(outgoing) == 1
    assert outgoing[0].node_name == "Database"


def test_create_assignments_requires_frozen(session: str) -> None:
    with pytest.raises(ValueError):
        orchestrator.create_assignments(session)


def test_create_assignments_after_freeze(session: str) -> None:
    orchestrator.freeze_contract(session)
    created = orchestrator.create_assignments(session)

    assert len(created) == 3  # one per node in the fixture


def sample_with_nodes(
    nodes: list[Node], edges: list[Edge]
) -> Contract:
    """Helper: build a tiny contract from raw nodes/edges."""
    contract = make_sample_contract()
    contract.nodes = nodes
    contract.edges = edges
    return contract


def test_identify_leaf_nodes_ignores_event_edges() -> None:
    n_a = Node(
        id="a",
        name="A",
        kind=NodeKind.SERVICE,
        description="",
        responsibilities=["x"],
        confidence=0.5,
        decided_by=DecidedBy.PROMPT,
    )
    n_b = Node(
        id="b",
        name="B",
        kind=NodeKind.SERVICE,
        description="",
        responsibilities=["y"],
        confidence=0.5,
        decided_by=DecidedBy.PROMPT,
    )
    edge = Edge(
        id="e",
        source="a",
        target="b",
        kind=EdgeKind.EVENT,
        confidence=0.5,
        decided_by=DecidedBy.AGENT,
    )

    contract = sample_with_nodes([n_a, n_b], edges=[edge])
    leaves = orchestrator.identify_leaf_nodes(contract)

    # Event-only outflows should not disqualify ``a`` from being a leaf.
    assert {n.id for n in leaves} == {"a", "b"}


# ---------------------------------------------------------------------------
# M5 review-driven regression tests
# ---------------------------------------------------------------------------


import asyncio
from pathlib import Path

import pytest as _pt

from app import assignments as _assignments_svc
from app.schemas import AssignmentStatus


def test_internal_run_marks_assignments_completed(
    session: str, tmp_path, monkeypatch
) -> None:
    """run_implementation_internal must claim before completing.

    Regression: previously the orchestrator never claimed assignments,
    so complete_assignment silently failed and assignments stayed in
    PENDING forever (and get_available_assignments kept returning
    already-implemented nodes).
    """
    orchestrator.set_generated_dir(tmp_path / "gen")

    # Mock the subagent to avoid LLM calls; return a malicious filename
    # to simultaneously regress the path-traversal fix.
    async def _fake_subagent(assignment):
        return {
            "files": [
                {"filename": "../../etc/evil.py", "content": "x"},
                {"filename": "ok.py", "content": "y"},
            ],
            "exports": [],
            "imports": [],
            "public_functions": [],
            "notes": "test",
        }

    monkeypatch.setattr(orchestrator, "_run_subagent", _fake_subagent)

    orchestrator.freeze_contract(session)
    orchestrator.create_assignments(session)

    asyncio.get_event_loop().run_until_complete(
        orchestrator.run_implementation_internal(session)
    )

    after = _assignments_svc.get_assignments_for_session(session)
    assert all(
        a.status == AssignmentStatus.COMPLETED.value for a in after
    ), [a.status for a in after]

    # Path-traversal regression: every written file must live under the
    # configured generated dir; the malicious "../../" path must have
    # been stripped to "evil.py" and stayed inside the session/node dir.
    gen_root = (tmp_path / "gen").resolve()
    for a in after:
        for fp in a.result.implementation.file_paths:
            resolved = Path(fp).resolve()
            assert str(resolved).startswith(str(gen_root)), resolved

    orchestrator.set_generated_dir(None)


def test_get_generated_files_dir_rejects_traversal(tmp_path) -> None:
    """A crafted session_id like ``..`` must not escape the gen root."""
    orchestrator.set_generated_dir(tmp_path / "gen")
    (tmp_path / "gen").mkdir()
    try:
        for bad in ["..", "../sibling", "../../etc", "/etc"]:
            with pytest.raises(ValueError):
                orchestrator.get_generated_files_dir(bad)
    finally:
        orchestrator.set_generated_dir(None)


def test_create_assignments_is_idempotent(session: str) -> None:
    """Repeated /implement calls must not duplicate assignments."""
    orchestrator.freeze_contract(session)
    first = orchestrator.create_assignments(session)
    second = orchestrator.create_assignments(session)

    assert len(first) == len(second)
    assert {a.id for a in first} == {a.id for a in second}
    stored = assignments_svc.get_assignments_for_session(session)
    assert len(stored) == len(first)
