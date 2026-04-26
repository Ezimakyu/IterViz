"""Tests for ``app.subgraph`` -- generation, fallback, and progress."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas import (
    Contract,
    ImplementationSubgraph,
    Meta,
    Node,
    NodeKind,
    SubgraphEdge,
    SubgraphNode,
    SubgraphNodeKind,
    SubgraphNodeStatus,
)
from app.subgraph import (
    generate_subgraph,
    get_neighbor_interfaces,
    update_subgraph_node_status,
)


# ---------------------------------------------------------------------------
# generate_subgraph (no-LLM fallback path)
# ---------------------------------------------------------------------------


def test_generate_subgraph_uses_fallback_for_each_responsibility(
    sample_contract: Contract,
) -> None:
    """Without an LLM, every responsibility yields one FUNCTION node + 1 test."""

    node = sample_contract.nodes[1]  # API Server (3 responsibilities)
    sg = generate_subgraph(node, sample_contract, use_llm=False)

    assert isinstance(sg, ImplementationSubgraph)
    assert sg.parent_node_id == node.id
    assert sg.parent_node_name == node.name
    assert sg.session_id == sample_contract.meta.id

    func_nodes = [n for n in sg.nodes if n.kind == SubgraphNodeKind.FUNCTION.value]
    test_nodes = [n for n in sg.nodes if n.kind == SubgraphNodeKind.TEST_UNIT.value]

    assert len(func_nodes) == len(node.responsibilities)
    assert len(test_nodes) == 1
    assert all(n.status == SubgraphNodeStatus.PENDING.value for n in sg.nodes)


def test_generate_subgraph_fallback_for_node_without_responsibilities(
    sample_contract: Contract,
) -> None:
    """A bare node still gets a single FUNCTION + a TEST_UNIT placeholder."""

    bare = Node(id="bare", name="Bare", kind=NodeKind.SERVICE)
    contract = sample_contract.model_copy(update={"nodes": [bare]})

    sg = generate_subgraph(bare, contract, use_llm=False)

    func_nodes = [n for n in sg.nodes if n.kind == SubgraphNodeKind.FUNCTION.value]
    test_nodes = [n for n in sg.nodes if n.kind == SubgraphNodeKind.TEST_UNIT.value]
    assert len(func_nodes) == 1
    assert len(test_nodes) == 1


def test_generate_subgraph_creates_dependency_edges(
    sample_contract: Contract,
) -> None:
    """Test node depends on every function node; edges encode that."""

    node = sample_contract.nodes[1]
    sg = generate_subgraph(node, sample_contract, use_llm=False)

    func_ids = {n.id for n in sg.nodes if n.kind == SubgraphNodeKind.FUNCTION.value}
    test_ids = {n.id for n in sg.nodes if n.kind == SubgraphNodeKind.TEST_UNIT.value}

    assert func_ids and test_ids
    for edge in sg.edges:
        assert isinstance(edge, SubgraphEdge)
        assert edge.source in test_ids
        assert edge.target in func_ids
        assert edge.kind == "dependency"

    # One edge per function -- the test depends on every function.
    assert len(sg.edges) == len(func_ids)


def test_generate_subgraph_estimates_total_lines(
    sample_contract: Contract,
) -> None:
    node = sample_contract.nodes[1]
    sg = generate_subgraph(node, sample_contract, use_llm=False)

    summed = sum((n.estimated_lines or 0) for n in sg.nodes)
    assert sg.total_estimated_lines == summed


def test_generate_subgraph_initial_aggregate_status_pending(
    sample_contract: Contract,
) -> None:
    sg = generate_subgraph(sample_contract.nodes[0], sample_contract, use_llm=False)
    assert sg.status == SubgraphNodeStatus.PENDING.value
    assert sg.progress == 0.0


def test_generate_subgraph_falls_back_when_llm_returns_empty(
    monkeypatch: pytest.MonkeyPatch, sample_contract: Contract
) -> None:
    """If the planner LLM produces no nodes we still ship a usable subgraph."""

    from app import subgraph as subgraph_module

    def _empty(*_args, **_kwargs):  # noqa: ANN401, ANN001
        return [], [], None

    monkeypatch.setattr(subgraph_module, "_call_planner_llm", _empty)

    node = sample_contract.nodes[0]
    sg = generate_subgraph(node, sample_contract)
    assert sg.nodes, "fallback should populate nodes even when the LLM is empty"


def test_convert_planner_output_remaps_duplicate_ids_for_edges_and_deps(
    sample_contract: Contract,
) -> None:
    """Duplicate LLM ids are renamed; edges/deps to the original id resolve to
    the first node with that id (no orphans, no broken references)."""

    from app import subgraph as subgraph_module
    from app.subgraph import _PlannerEdge, _PlannerNode, _PlannerOutput

    raw = _PlannerOutput(
        nodes=[
            _PlannerNode(id="x", name="X1", kind="function", dependencies=[]),
            # Duplicate id -- _ensure_unique_id should rename this to e.g. x-2.
            # Its dependency on "x" should remap to the first "x" (not stay
            # as a stale string), and an edge sourced at "x" should connect
            # to the first node with that id.
            _PlannerNode(id="x", name="X2", kind="function", dependencies=["x"]),
            _PlannerNode(id="y", name="Y", kind="test_unit", dependencies=["x"]),
        ],
        edges=[
            _PlannerEdge(source="y", target="x"),
        ],
    )

    nodes, edges, _ = subgraph_module._convert_planner_output(raw)

    assert len(nodes) == 3
    ids = [n.id for n in nodes]
    assert ids[0] == "x"
    assert ids[1] != "x" and ids[1].startswith("x")
    # The renamed node's dependencies should not contain a stale "x" reference
    # (it should resolve to the first "x" id, which is unchanged here).
    assert all(dep in {n.id for n in nodes} for dep in nodes[1].dependencies)
    # Edge target "x" stays valid because the first node kept that id.
    assert any(e.source == "y" and e.target == "x" for e in edges)


def test_generate_subgraph_falls_back_when_llm_raises(
    monkeypatch: pytest.MonkeyPatch, sample_contract: Contract
) -> None:
    from app import subgraph as subgraph_module

    def _boom(*_args, **_kwargs):  # noqa: ANN401, ANN001
        raise RuntimeError("no key")

    monkeypatch.setattr(subgraph_module, "_call_planner_llm", _boom)

    sg = generate_subgraph(sample_contract.nodes[0], sample_contract)
    assert sg.nodes, "LLM failure must not produce an empty subgraph"


# ---------------------------------------------------------------------------
# get_neighbor_interfaces
# ---------------------------------------------------------------------------


def test_get_neighbor_interfaces_partitions_edges(
    sample_contract: Contract,
) -> None:
    api_node = sample_contract.nodes[1]  # api server -- both incoming + outgoing
    interfaces = get_neighbor_interfaces(api_node, sample_contract)

    assert {entry["node_name"] for entry in interfaces["incoming"]} == {"Web UI"}
    assert {entry["node_name"] for entry in interfaces["outgoing"]} == {"Database"}


# ---------------------------------------------------------------------------
# update_subgraph_node_status
# ---------------------------------------------------------------------------


def _make_subgraph(node_id: str = "n-x") -> ImplementationSubgraph:
    return ImplementationSubgraph(
        id="sg-test",
        parent_node_id=node_id,
        parent_node_name="Parent",
        session_id="sess-1",
        created_at=datetime.now(timezone.utc),
        nodes=[
            SubgraphNode(id="a", name="A", kind=SubgraphNodeKind.FUNCTION),
            SubgraphNode(id="b", name="B", kind=SubgraphNodeKind.FUNCTION),
            SubgraphNode(id="c", name="C", kind=SubgraphNodeKind.FUNCTION),
            SubgraphNode(id="t", name="Tests", kind=SubgraphNodeKind.TEST_UNIT),
        ],
    )


def test_update_status_records_started_at_for_in_progress() -> None:
    sg = _make_subgraph()
    update_subgraph_node_status(sg, "a", SubgraphNodeStatus.IN_PROGRESS)
    a = next(n for n in sg.nodes if n.id == "a")
    assert a.status == SubgraphNodeStatus.IN_PROGRESS.value
    assert a.started_at is not None
    assert a.completed_at is None


def test_update_status_records_completed_at_for_completed() -> None:
    sg = _make_subgraph()
    update_subgraph_node_status(sg, "a", SubgraphNodeStatus.COMPLETED)
    a = next(n for n in sg.nodes if n.id == "a")
    assert a.completed_at is not None


def test_update_status_attaches_error_message_on_failure() -> None:
    sg = _make_subgraph()
    update_subgraph_node_status(
        sg, "a", SubgraphNodeStatus.FAILED, error_message="boom"
    )
    a = next(n for n in sg.nodes if n.id == "a")
    assert a.error_message == "boom"
    assert a.status == SubgraphNodeStatus.FAILED.value


def test_update_status_recalculates_progress() -> None:
    sg = _make_subgraph()
    assert sg.progress == 0.0  # not yet recomputed

    update_subgraph_node_status(sg, "a", SubgraphNodeStatus.COMPLETED)
    update_subgraph_node_status(sg, "b", SubgraphNodeStatus.COMPLETED)
    assert sg.progress == pytest.approx(0.5)


def test_update_status_aggregate_completed_when_all_done() -> None:
    sg = _make_subgraph()
    for nid in ("a", "b", "c", "t"):
        update_subgraph_node_status(sg, nid, SubgraphNodeStatus.COMPLETED)
    assert sg.status == SubgraphNodeStatus.COMPLETED.value
    assert sg.progress == pytest.approx(1.0)


def test_update_status_aggregate_failed_when_any_failure() -> None:
    sg = _make_subgraph()
    update_subgraph_node_status(sg, "a", SubgraphNodeStatus.COMPLETED)
    update_subgraph_node_status(sg, "b", SubgraphNodeStatus.FAILED, "x")
    assert sg.status == SubgraphNodeStatus.FAILED.value


def test_update_status_aggregate_in_progress_when_any_running() -> None:
    sg = _make_subgraph()
    update_subgraph_node_status(sg, "a", SubgraphNodeStatus.IN_PROGRESS)
    assert sg.status == SubgraphNodeStatus.IN_PROGRESS.value


def test_update_status_unknown_node_raises() -> None:
    sg = _make_subgraph()
    with pytest.raises(KeyError):
        update_subgraph_node_status(sg, "missing", SubgraphNodeStatus.COMPLETED)
