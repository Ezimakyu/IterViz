"""Implementation subgraph generation.

Given a *verified* big-picture node, produce an
:class:`~app.schemas.ImplementationSubgraph` that breaks the work into
concrete implementation tasks (functions, tests, types, etc.).

This module deliberately bypasses the verification loop: by the time
implementation starts, the parent node has UVDC = 1.0 and load-bearing
assumptions have been decided. The subgraph is a planning artifact, not
an architecture document.

Generation strategy:

1. Build a context dict from the parent node + neighbor edges.
2. Ask the LLM (via :func:`app.llm.call_structured`) to produce a list
   of subgraph nodes + edges, validated against ``_PlannerOutput``.
3. On any LLM failure, fall back to a minimal deterministic subgraph
   derived from the node's responsibilities so the API always returns
   *something* the UI can render.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from . import llm as llm_svc
from .logger import get_logger
from .schemas import (
    Contract,
    Edge,
    ImplementationSubgraph,
    Node,
    SubgraphEdge,
    SubgraphNode,
    SubgraphNodeKind,
    SubgraphNodeStatus,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# LLM I/O models
# ---------------------------------------------------------------------------


class _PlannerNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    kind: str = "function"
    description: str = ""
    signature: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)
    estimated_lines: Optional[int] = None


class _PlannerEdge(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str
    target: str
    label: Optional[str] = None


class _PlannerOutput(BaseModel):
    """Structured output the planner LLM is constrained to emit."""

    model_config = ConfigDict(extra="allow")

    nodes: list[_PlannerNode] = Field(default_factory=list)
    edges: list[_PlannerEdge] = Field(default_factory=list)
    total_lines: Optional[int] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


NeighborInterfaces = dict[str, list[dict[str, Any]]]


def get_neighbor_interfaces(node: Node, contract: Contract) -> NeighborInterfaces:
    """Collect incoming/outgoing edge metadata for a node.

    Each side is a list of ``{node_id, node_name, edge_kind,
    payload_schema}`` dicts. The shape mirrors what the M5 orchestrator
    is expected to pass into the planner once it exists.
    """

    by_id = {n.id: n for n in contract.nodes}

    def _entry(other: Optional[Node], edge: Edge) -> dict[str, Any]:
        return {
            "node_id": other.id if other else "",
            "node_name": other.name if other else "(unknown)",
            "edge_kind": edge.kind.value if hasattr(edge.kind, "value") else edge.kind,
            "edge_label": edge.label,
            "payload_schema": edge.payload_schema,
        }

    incoming = [
        _entry(by_id.get(e.source), e) for e in contract.edges if e.target == node.id
    ]
    outgoing = [
        _entry(by_id.get(e.target), e) for e in contract.edges if e.source == node.id
    ]
    return {"incoming": incoming, "outgoing": outgoing}


def generate_subgraph(
    node: Node,
    contract: Contract,
    neighbor_interfaces: Optional[NeighborInterfaces] = None,
    *,
    use_llm: bool = True,
) -> ImplementationSubgraph:
    """Produce an :class:`ImplementationSubgraph` for ``node``.

    Args:
        node: the verified big-picture node to break down.
        contract: the full contract (used for session id + neighbor lookup).
        neighbor_interfaces: optional pre-computed neighbor metadata.
            Falls back to :func:`get_neighbor_interfaces` when omitted.
        use_llm: when ``False``, skip the LLM call entirely and use the
            deterministic fallback. Tests pin this to ``False`` to avoid
            hitting the network.

    Returns:
        A populated :class:`ImplementationSubgraph`. Aggregate
        ``status`` and ``progress`` are recomputed before returning.
    """

    if neighbor_interfaces is None:
        neighbor_interfaces = get_neighbor_interfaces(node, contract)

    log.info(
        "subgraph.generating",
        extra={
            "node_id": node.id,
            "node_name": node.name,
            "responsibilities_count": len(node.responsibilities),
            "incoming_count": len(neighbor_interfaces.get("incoming", [])),
            "outgoing_count": len(neighbor_interfaces.get("outgoing", [])),
        },
    )

    nodes: list[SubgraphNode] = []
    edges: list[SubgraphEdge] = []
    total_lines: Optional[int] = None
    used_fallback = False

    if use_llm:
        try:
            nodes, edges, total_lines = _call_planner_llm(node, neighbor_interfaces, contract)
        except Exception as exc:  # pragma: no cover - depends on network/env
            log.warning(
                "subgraph.llm_failed",
                extra={"node_id": node.id, "error": str(exc)},
            )
            nodes, edges, total_lines = _fallback_subgraph(node)
            used_fallback = True
    else:
        nodes, edges, total_lines = _fallback_subgraph(node)
        used_fallback = True

    if not nodes:
        # LLM returned an empty plan. Don't ship an empty subgraph -- fall
        # back to the deterministic decomposition so the UI always has
        # something to show.
        nodes, edges, total_lines = _fallback_subgraph(node)
        used_fallback = True

    subgraph = ImplementationSubgraph(
        id=str(uuid.uuid4()),
        parent_node_id=node.id,
        parent_node_name=node.name,
        session_id=contract.meta.id,
        created_at=datetime.now(timezone.utc),
        nodes=nodes,
        edges=edges,
        total_estimated_lines=total_lines,
    )
    _recompute_aggregate(subgraph)

    log.info(
        "subgraph.generated",
        extra={
            "subgraph_id": subgraph.id,
            "parent_node_id": node.id,
            "subgraph_node_count": len(subgraph.nodes),
            "subgraph_edge_count": len(subgraph.edges),
            "used_fallback": used_fallback,
        },
    )
    return subgraph


def update_subgraph_node_status(
    subgraph: ImplementationSubgraph,
    subgraph_node_id: str,
    status: SubgraphNodeStatus,
    error_message: Optional[str] = None,
) -> ImplementationSubgraph:
    """Mutate ``subgraph`` to reflect a node-level status change.

    The aggregate ``progress`` and ``status`` fields are recomputed in
    place. The same instance is returned so callers can chain updates
    or hand the object straight to a broadcaster.

    Raises:
        KeyError: if ``subgraph_node_id`` does not exist in the subgraph.
    """

    now = datetime.now(timezone.utc)

    target: Optional[SubgraphNode] = next(
        (n for n in subgraph.nodes if n.id == subgraph_node_id), None
    )
    if target is None:
        raise KeyError(
            f"subgraph node {subgraph_node_id!r} not found in {subgraph.id}"
        )

    old_status = target.status
    target.status = status

    if status == SubgraphNodeStatus.IN_PROGRESS and target.started_at is None:
        target.started_at = now
    elif status in (SubgraphNodeStatus.COMPLETED, SubgraphNodeStatus.FAILED):
        target.completed_at = now

    if error_message is not None:
        target.error_message = error_message
    elif status != SubgraphNodeStatus.FAILED:
        # Clear stale error when a node recovers.
        target.error_message = None

    log.info(
        "subgraph.node_status_changed",
        extra={
            "subgraph_id": subgraph.id,
            "subgraph_node_id": subgraph_node_id,
            "old_status": _enum_value(old_status),
            "new_status": _enum_value(status),
        },
    )

    _recompute_aggregate(subgraph)
    return subgraph


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


_PROMPT_NAME = "planner"


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _recompute_aggregate(subgraph: ImplementationSubgraph) -> None:
    """Recompute ``progress`` and aggregate ``status`` from node states."""

    total = len(subgraph.nodes)
    if total == 0:
        subgraph.progress = 0.0
        subgraph.status = SubgraphNodeStatus.PENDING
        return

    statuses = [_enum_value(n.status) for n in subgraph.nodes]
    completed = sum(1 for s in statuses if s == SubgraphNodeStatus.COMPLETED.value)
    subgraph.progress = completed / total

    if all(s == SubgraphNodeStatus.COMPLETED.value for s in statuses):
        subgraph.status = SubgraphNodeStatus.COMPLETED
    elif any(s == SubgraphNodeStatus.FAILED.value for s in statuses):
        subgraph.status = SubgraphNodeStatus.FAILED
    elif any(s == SubgraphNodeStatus.IN_PROGRESS.value for s in statuses):
        subgraph.status = SubgraphNodeStatus.IN_PROGRESS
    else:
        subgraph.status = SubgraphNodeStatus.PENDING


def _call_planner_llm(
    node: Node,
    neighbor_interfaces: NeighborInterfaces,
    contract: Contract,
) -> tuple[list[SubgraphNode], list[SubgraphEdge], Optional[int]]:
    """Invoke the planner LLM and convert its output to subgraph models."""

    system = llm_svc.load_prompt(_PROMPT_NAME)
    user = _build_user_prompt(node, neighbor_interfaces, contract)

    raw = llm_svc.call_structured(
        response_model=_PlannerOutput,
        system=system,
        user=user,
        temperature=0.2,
    )
    return _convert_planner_output(raw)


def _build_user_prompt(
    node: Node,
    neighbor_interfaces: NeighborInterfaces,
    contract: Contract,
) -> str:
    """Build the user prompt body for the planner LLM."""

    responsibilities = "\n".join(f"- {r}" for r in node.responsibilities) or "(none)"
    incoming = neighbor_interfaces.get("incoming", [])
    outgoing = neighbor_interfaces.get("outgoing", [])

    return (
        f"Break down this verified architecture node into implementation tasks.\n\n"
        f"Node: {node.name}\n"
        f"Kind: {_enum_value(node.kind)}\n"
        f"Description: {node.description}\n\n"
        f"Responsibilities:\n{responsibilities}\n\n"
        f"Incoming edges (data the node receives):\n"
        f"{json.dumps(incoming, indent=2, default=str)}\n\n"
        f"Outgoing edges (data the node produces):\n"
        f"{json.dumps(outgoing, indent=2, default=str)}\n\n"
        f"Stated system intent: {contract.meta.stated_intent}\n\n"
        "Return a practical implementation subgraph with concrete functions, "
        "tests, types, and error handling. Do NOT introduce new architectural "
        "assumptions."
    )


def _convert_planner_output(
    raw: _PlannerOutput,
) -> tuple[list[SubgraphNode], list[SubgraphEdge], Optional[int]]:
    """Translate the LLM's loose structured output into validated models."""

    seen_ids: set[str] = set()
    nodes: list[SubgraphNode] = []
    for raw_node in raw.nodes:
        kind = _coerce_kind(raw_node.kind)
        sg_id = _ensure_unique_id(raw_node.id, seen_ids)
        nodes.append(
            SubgraphNode(
                id=sg_id,
                name=raw_node.name or sg_id,
                kind=kind,
                description=raw_node.description,
                signature=raw_node.signature,
                dependencies=list(dict.fromkeys(raw_node.dependencies)),
                estimated_lines=raw_node.estimated_lines,
            )
        )

    valid_ids = {n.id for n in nodes}
    edges: list[SubgraphEdge] = []
    for raw_edge in raw.edges:
        if raw_edge.source not in valid_ids or raw_edge.target not in valid_ids:
            continue
        edges.append(
            SubgraphEdge(
                id=str(uuid.uuid4()),
                source=raw_edge.source,
                target=raw_edge.target,
                label=raw_edge.label,
            )
        )

    return nodes, edges, raw.total_lines


def _coerce_kind(value: str) -> SubgraphNodeKind:
    """Loosely map an LLM-emitted kind string to a known enum value."""

    if not value:
        return SubgraphNodeKind.FUNCTION
    normalized = value.strip().lower().replace("-", "_")
    try:
        return SubgraphNodeKind(normalized)
    except ValueError:
        # Pick a sensible default rather than refusing the whole subgraph.
        if "test" in normalized:
            return SubgraphNodeKind.TEST_UNIT
        if "type" in normalized or "schema" in normalized:
            return SubgraphNodeKind.TYPE_DEF
        if "config" in normalized:
            return SubgraphNodeKind.CONFIG
        if "error" in normalized or "exception" in normalized:
            return SubgraphNodeKind.ERROR_HANDLER
        if "module" in normalized or "file" in normalized:
            return SubgraphNodeKind.MODULE
        if "util" in normalized or "helper" in normalized:
            return SubgraphNodeKind.UTIL
        return SubgraphNodeKind.FUNCTION


def _ensure_unique_id(candidate: str, seen: set[str]) -> str:
    """Return a unique id based on ``candidate``, registering it in ``seen``."""

    base = candidate.strip() if candidate else f"sg-{uuid.uuid4().hex[:8]}"
    if base not in seen:
        seen.add(base)
        return base
    suffix = 2
    while f"{base}-{suffix}" in seen:
        suffix += 1
    new_id = f"{base}-{suffix}"
    seen.add(new_id)
    return new_id


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or f"task-{uuid.uuid4().hex[:6]}"


def _fallback_subgraph(
    node: Node,
) -> tuple[list[SubgraphNode], list[SubgraphEdge], Optional[int]]:
    """Minimal deterministic subgraph used when the LLM is unavailable.

    Strategy:

    - One ``FUNCTION`` node per responsibility (or a single placeholder
      when the parent has no responsibilities listed).
    - One ``TEST_UNIT`` node depending on every function.
    - Edges encode the test -> function dependencies.
    """

    func_nodes: list[SubgraphNode] = []
    if node.responsibilities:
        for idx, responsibility in enumerate(node.responsibilities):
            slug = _slug(responsibility)[:32] or f"task-{idx}"
            func_nodes.append(
                SubgraphNode(
                    id=f"sg-func-{idx}-{slug}",
                    name=f"Implement: {responsibility[:60]}",
                    kind=SubgraphNodeKind.FUNCTION,
                    description=responsibility,
                    estimated_lines=40,
                )
            )
    else:
        func_nodes.append(
            SubgraphNode(
                id="sg-func-0",
                name=f"Implement {node.name}",
                kind=SubgraphNodeKind.FUNCTION,
                description=node.description or f"Implement {node.name}.",
                estimated_lines=60,
            )
        )

    test_node = SubgraphNode(
        id="sg-test-unit",
        name="Unit Tests",
        kind=SubgraphNodeKind.TEST_UNIT,
        description=f"Unit tests for {node.name}",
        dependencies=[fn.id for fn in func_nodes],
        estimated_lines=40,
    )

    edges = [
        SubgraphEdge(
            id=str(uuid.uuid4()),
            source=test_node.id,
            target=fn.id,
        )
        for fn in func_nodes
    ]

    nodes = func_nodes + [test_node]
    total = sum((n.estimated_lines or 0) for n in nodes) or None
    return nodes, edges, total


__all__ = [
    "generate_subgraph",
    "update_subgraph_node_status",
    "get_neighbor_interfaces",
]
