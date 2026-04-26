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
