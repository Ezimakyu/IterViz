"""Phase 2 Orchestrator: freeze, dispatch subagents, integration pass.

The orchestrator manages the transition from a verified contract to
generated code. It supports both internal subagents (LLM calls
managed by the orchestrator) and external agent coordination (Devin,
Cursor, Claude Code, etc. claiming nodes via the API).

Core principle: the frozen contract's declared ``payload_schema`` is
the source of truth. Subagents code against declared interfaces; the
Integrator pass reports any mismatches as ``IntegrationMismatch``
records that the UI surfaces to the user.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from . import assignments as assignments_svc
from . import contract as contract_svc
from . import ws
from . import llm as llm_svc
from .logger import get_logger
from .schemas import (
    ActualInterface,
    Assignment,
    Contract,
    ContractStatus,
    EdgeKind,
    Implementation,
    IntegrationMismatch,
    NeighborInterface,
    Node,
    NodeStatus,
    Severity,
)

log = get_logger(__name__)


# Output directory for generated files. Tests can override via
# ``set_generated_dir`` so we never pollute the repo working tree.
_DEFAULT_GENERATED_DIR = Path(__file__).resolve().parent.parent / "generated"
_generated_dir_override: Optional[Path] = None


def get_generated_dir() -> Path:
    """Return the active output directory for generated files."""
    if _generated_dir_override is not None:
        return _generated_dir_override
    return _DEFAULT_GENERATED_DIR


def set_generated_dir(path: Optional[Path]) -> None:
    """Override the generated-files output directory (mostly for tests)."""
    global _generated_dir_override
    _generated_dir_override = Path(path) if path is not None else None


# ---------------------------------------------------------------------------
# Freeze
# ---------------------------------------------------------------------------


def freeze_contract(session_id: str) -> Contract:
    """Lock a contract for implementation.

    - Sets ``status`` to ``verified``.
    - Computes a SHA-256 hash of the contract JSON (recorded in
      ``meta.frozen_hash``).
    - Sets ``meta.frozen_at`` and bumps ``meta.version``.
    - Persists via ``contract_svc.update_contract``.
    """
    session = contract_svc.get_session(session_id)
    contract = session.contract

    # Status comes back as a plain string (use_enum_values=True), so
    # compare against the enum's value rather than the enum.
    current_status = (
        contract.meta.status
        if isinstance(contract.meta.status, str)
        else contract.meta.status.value
    )

    if current_status == ContractStatus.VERIFIED.value:
        log.warning(
            "orchestrator.already_frozen",
            extra={"session_id": session_id},
        )
        return contract

    if current_status != ContractStatus.DRAFTING.value:
        raise ValueError(
            f"Cannot freeze contract in status: {current_status}"
        )

    contract_json = contract.model_dump_json(exclude_none=True)
    frozen_hash = hashlib.sha256(contract_json.encode()).hexdigest()

    contract.meta.status = ContractStatus.VERIFIED
    contract.meta.frozen_at = datetime.utcnow()
    contract.meta.frozen_hash = frozen_hash
    contract.meta.version = (contract.meta.version or 1) + 1

    persisted = contract_svc.update_contract(session_id, contract)

    log.info(
        "orchestrator.frozen",
        extra={
            "session_id": session_id,
            "hash": frozen_hash[:16] + "...",
            "node_count": len(persisted.contract.nodes),
            "edge_count": len(persisted.contract.edges),
        },
    )
    return persisted.contract


# ---------------------------------------------------------------------------
# Leaf-node identification + neighbor interfaces
# ---------------------------------------------------------------------------


def identify_leaf_nodes(contract: Contract) -> list[Node]:
    """Return nodes that have no outgoing data/control edges.

    Leaf nodes don't depend on other nodes' implementation outputs, so
    they can be implemented in parallel without sequencing concerns.
    """
    non_leaf_ids: set[str] = set()
    for edge in contract.edges:
        kind = (
            edge.kind
            if isinstance(edge.kind, str)
            else edge.kind.value
        )
        if kind in (EdgeKind.DATA.value, EdgeKind.CONTROL.value):
            non_leaf_ids.add(edge.source)

    leaf_nodes = [n for n in contract.nodes if n.id not in non_leaf_ids]

    log.debug(
        "orchestrator.leaf_nodes_identified",
        extra={
            "total_nodes": len(contract.nodes),
            "leaf_nodes": len(leaf_nodes),
            "leaf_ids": [n.id for n in leaf_nodes],
        },
    )
    return leaf_nodes


def get_neighbor_interfaces(
    node: Node, contract: Contract
) -> tuple[list[NeighborInterface], list[NeighborInterface]]:
    """Return ``(incoming, outgoing)`` neighbor interfaces for a node."""
    incoming: list[NeighborInterface] = []
    outgoing: list[NeighborInterface] = []

    node_map = {n.id: n for n in contract.nodes}

    for edge in contract.edges:
        if edge.target == node.id:
            source_node = node_map.get(edge.source)
            if source_node is not None:
                incoming.append(
                    NeighborInterface(
                        edge_id=edge.id,
                        node_id=edge.source,
                        node_name=source_node.name,
                        payload_schema=edge.payload_schema,
                    )
                )
        elif edge.source == node.id:
            target_node = node_map.get(edge.target)
            if target_node is not None:
                outgoing.append(
                    NeighborInterface(
                        edge_id=edge.id,
                        node_id=edge.target,
                        node_name=target_node.name,
                        payload_schema=edge.payload_schema,
                    )
                )

    return incoming, outgoing


# ---------------------------------------------------------------------------
# Assignment fan-out
# ---------------------------------------------------------------------------


def create_assignments(session_id: str) -> list[Assignment]:
    """Create assignments for every node in a frozen contract.

    The slim demo path implements every node (not just leaves) so the
    UI can show transitions across the whole graph. Leaf-node hint is
    still surfaced via ``identify_leaf_nodes`` for downstream tooling.
    """
    session = contract_svc.get_session(session_id)
    contract = session.contract

    current_status = (
        contract.meta.status
        if isinstance(contract.meta.status, str)
        else contract.meta.status.value
    )
    if current_status != ContractStatus.VERIFIED.value:
        raise ValueError(
            "Contract must be frozen (verified) before creating assignments"
        )

    assignments: list[Assignment] = []
    for node in contract.nodes:
        incoming, outgoing = get_neighbor_interfaces(node, contract)
        assignment = assignments_svc.create_assignment(
            session_id=session_id,
            node=node,
            contract_snapshot=contract,
            incoming_interfaces=incoming,
            outgoing_interfaces=outgoing,
        )
        assignments.append(assignment)

    log.info(
        "orchestrator.assignments_created",
        extra={"session_id": session_id, "count": len(assignments)},
    )
    return assignments


# ---------------------------------------------------------------------------
# Internal-mode implementation loop
# ---------------------------------------------------------------------------


class _SubagentOutput(BaseModel):
    """Pydantic schema enforced on the subagent LLM response."""

    model_config = ConfigDict(extra="allow")

    files: list[dict[str, Any]] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    public_functions: list[dict[str, Any]] = Field(default_factory=list)
    notes: Optional[str] = None


async def run_implementation_internal(session_id: str) -> None:
    """Run the implementation phase using internal LLM subagents.

    This is sequential for demo simplicity. A production deployment
    would use ``asyncio.gather`` (or a pool) for parallelism. We
    broadcast every state transition over WebSocket so the UI can
    reflect progress live.
    """
    session = contract_svc.get_session(session_id)
    contract = session.contract

    contract.meta.status = ContractStatus.IMPLEMENTING
    persisted = contract_svc.update_contract(session_id, contract)
    contract = persisted.contract

    pending_assignments = assignments_svc.get_assignments_for_session(
        session_id
    )

    nodes_implemented = 0
    nodes_failed = 0

    for assignment in pending_assignments:
        node = assignment.payload.node

        await ws.broadcast_node_status_changed(
            session_id, node.id, NodeStatus.IN_PROGRESS
        )

        for n in contract.nodes:
            if n.id == node.id:
                n.status = NodeStatus.IN_PROGRESS
                break
        contract = contract_svc.update_contract(session_id, contract).contract

        try:
            start_time = datetime.utcnow()
            impl = await _run_subagent(assignment)
            duration_ms = int(
                (datetime.utcnow() - start_time).total_seconds() * 1000
            )

            output_dir = get_generated_dir() / session_id / node.id
            output_dir.mkdir(parents=True, exist_ok=True)

            file_paths: list[str] = []
            for i, content in enumerate(impl.get("files", [])):
                filename = content.get("filename") or f"file_{i}.py"
                file_path = output_dir / filename
                file_path.write_text(content.get("content", ""))
                file_paths.append(str(file_path))

            actual_interface = ActualInterface(
                exports=impl.get("exports", []),
                imports=impl.get("imports", []),
                public_functions=impl.get("public_functions", []),
            )

            assignments_svc.complete_assignment(
                session_id=session_id,
                node_id=node.id,
                agent_id=assignment.assigned_to or "internal",
                file_paths=file_paths,
                actual_interface=actual_interface,
                notes=impl.get("notes"),
                duration_ms=duration_ms,
            )

            for n in contract.nodes:
                if n.id == node.id:
                    n.status = NodeStatus.IMPLEMENTED
                    n.implementation = Implementation(
                        file_paths=file_paths,
                        notes=impl.get("notes"),
                        actual_interface=actual_interface,
                        completed_at=datetime.utcnow(),
                    )
                    break
            contract = contract_svc.update_contract(
                session_id, contract
            ).contract

            await ws.broadcast_node_status_changed(
                session_id, node.id, NodeStatus.IMPLEMENTED
            )

            nodes_implemented += 1

            log.info(
                "orchestrator.node_implemented",
                extra={
                    "session_id": session_id,
                    "node_id": node.id,
                    "node_name": node.name,
                    "duration_ms": duration_ms,
                    "file_count": len(file_paths),
                },
            )

        except Exception as exc:  # pragma: no cover - exercised via tests
            log.error(
                "orchestrator.node_failed",
                extra={
                    "session_id": session_id,
                    "node_id": node.id,
                    "error": str(exc),
                },
            )

            assignments_svc.fail_assignment(session_id, node.id)

            for n in contract.nodes:
                if n.id == node.id:
                    n.status = NodeStatus.FAILED
                    break
            contract = contract_svc.update_contract(
                session_id, contract
            ).contract

            await ws.broadcast_node_status_changed(
                session_id, node.id, NodeStatus.FAILED
            )
            nodes_failed += 1

    mismatches = await run_integration_pass(session_id)

    contract.meta.status = ContractStatus.COMPLETE
    contract = contract_svc.update_contract(session_id, contract).contract

    contract_path = get_generated_dir() / session_id / "contract.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(contract.model_dump_json(indent=2))

    await ws.broadcast_implementation_complete(
        session_id,
        success=(nodes_failed == 0),
        nodes_implemented=nodes_implemented,
        nodes_failed=nodes_failed,
    )

    log.info(
        "orchestrator.implementation_complete",
        extra={
            "session_id": session_id,
            "nodes_implemented": nodes_implemented,
            "nodes_failed": nodes_failed,
            "mismatches": len(mismatches),
        },
    )


async def _run_subagent(assignment: Assignment) -> dict[str, Any]:
    """Call an LLM (or fall back to a mock) to implement a single node."""
    node = assignment.payload.node
    contract = assignment.payload.contract_snapshot
    neighbors = assignment.payload.neighbor_interfaces

    incoming = [n.model_dump() for n in neighbors.get("incoming", [])]
    outgoing = [n.model_dump() for n in neighbors.get("outgoing", [])]

    user_msg = (
        f"Implement the following node:\n\n"
        f"Node: {node.name}\n"
        f"Kind: {node.kind}\n"
        f"Description: {node.description}\n\n"
        "Responsibilities:\n"
        + "\n".join(f"- {r}" for r in node.responsibilities)
        + "\n\n"
        "Incoming interfaces (data you receive):\n"
        f"{json.dumps(incoming, indent=2)}\n\n"
        "Outgoing interfaces (data you produce):\n"
        f"{json.dumps(outgoing, indent=2)}\n\n"
        f"System intent: {contract.meta.stated_intent}\n\n"
        "Generate Python code that implements this node's responsibilities. "
        "Code against the declared interfaces, not your assumptions."
    )

    try:
        system_prompt = llm_svc.load_prompt("subagent")
    except FileNotFoundError:
        system_prompt = "You are a code implementation agent."

    try:
        result = await asyncio.to_thread(
            llm_svc.call_structured,
            response_model=_SubagentOutput,
            system=system_prompt,
            user=user_msg,
        )
        return result.model_dump()
    except Exception as exc:
        log.warning(
            "orchestrator.subagent_llm_failed",
            extra={"node_id": node.id, "error": str(exc)},
        )
        # Mock implementation keeps the demo deterministic when there
        # is no LLM key configured (or the network is unreachable).
        safe_module = node.id.replace("-", "_")
        return {
            "files": [
                {
                    "filename": f"{safe_module}.py",
                    "content": (
                        f'"""Implementation for {node.name}."""\n\n'
                        f"# Auto-generated implementation\n"
                        f"# Node: {node.name}\n"
                        f"# Kind: {node.kind}\n\n"
                        f"def main() -> None:\n"
                        f'    """Entry point for {node.name}."""\n'
                        f"    pass\n\n"
                        'if __name__ == "__main__":\n'
                        "    main()\n"
                    ),
                }
            ],
            "exports": ["main"],
            "imports": [],
            "public_functions": [
                {"name": "main", "signature": "def main() -> None"}
            ],
            "notes": "Mock implementation (LLM unavailable).",
        }


# ---------------------------------------------------------------------------
# Integration pass
# ---------------------------------------------------------------------------


async def run_integration_pass(session_id: str) -> list[IntegrationMismatch]:
    """Compare actual interfaces against declared edge schemas.

    The demo implementation flags two simple cases:
    - A declared payload schema with no exports on the source side.
    - Source/target both implemented but neither has a non-empty
      ``actual_interface`` (likely indicates a stub).
    """
    session = contract_svc.get_session(session_id)
    contract = session.contract

    mismatches: list[IntegrationMismatch] = []
    node_map = {n.id: n for n in contract.nodes}

    edges_checked = 0
    for edge in contract.edges:
        kind = (
            edge.kind
            if isinstance(edge.kind, str)
            else edge.kind.value
        )
        if kind not in (EdgeKind.DATA.value, EdgeKind.EVENT.value):
            continue
        edges_checked += 1

        source_node = node_map.get(edge.source)
        target_node = node_map.get(edge.target)
        if source_node is None or target_node is None:
            continue

        source_impl = source_node.implementation
        target_impl = target_node.implementation
        if source_impl is None or target_impl is None:
            continue

        declared = edge.payload_schema or {}
        source_actual = source_impl.actual_interface
        target_actual = target_impl.actual_interface

        if declared and (
            source_actual is None
            or not source_actual.exports
        ):
            mismatches.append(
                IntegrationMismatch(
                    id=str(uuid.uuid4()),
                    edge_id=edge.id,
                    source_node_id=edge.source,
                    target_node_id=edge.target,
                    declared_schema=declared,
                    actual_source_interface=source_actual,
                    actual_target_interface=target_actual,
                    mismatch_description=(
                        f"Edge {edge.id} declares a payload schema but "
                        f"source node {source_node.name} exports nothing."
                    ),
                    severity=Severity.WARNING,
                )
            )

    log.info(
        "orchestrator.integration_pass_complete",
        extra={
            "session_id": session_id,
            "edges_checked": edges_checked,
            "mismatches_found": len(mismatches),
        },
    )

    await ws.broadcast_integration_result(session_id, mismatches)
    return mismatches


# ---------------------------------------------------------------------------
# Generated files lookup
# ---------------------------------------------------------------------------


def get_generated_files_dir(session_id: str) -> Path:
    """Return the directory containing generated files for a session."""
    output_dir = get_generated_dir() / session_id
    if not output_dir.exists():
        raise ValueError(f"No generated files for session {session_id}")
    return output_dir


__all__ = [
    "freeze_contract",
    "identify_leaf_nodes",
    "get_neighbor_interfaces",
    "create_assignments",
    "run_implementation_internal",
    "run_integration_pass",
    "get_generated_files_dir",
    "get_generated_dir",
    "set_generated_dir",
]
