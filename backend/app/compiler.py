"""Blind Compiler verification logic for Glasshouse (M3).

The compiler combines two layers:

1. **Deterministic invariant checks** (INV-001 .. INV-007) implemented in
   pure Python. These never call an LLM and are the source of truth for
   structural defects in the contract.
2. **LLM-driven semantic passes** for intent reconstruction, failure
   scenarios, and decision provenance. These add violations on top of
   the deterministic findings.

Public surface:

- :func:`run_invariant_checks(contract)` — pure-Python invariants.
- :func:`verify_contract(contract, ...)` — full pipeline.
- :func:`compute_uvdc(contract)` — User-Visible Decision Coverage score.
- :func:`rank_violations(violations)` — ranked top-N (default 5) order.

Test code monkeypatches :func:`_call_llm_passes` to avoid network calls.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable, Optional

from .logger import get_logger
from .schemas import (
    CompilerOutput,
    Contract,
    Edge,
    EdgeKind,
    NodeConfidenceUpdate,
    NodeKind,
    Severity,
    Verdict,
    Violation,
    ViolationType,
)

log = get_logger(__name__)


MAX_QUESTIONS = 5
LOW_CONFIDENCE_THRESHOLD = 0.6
LOAD_BEARING_NODE_FIELDS = ("kind", "responsibilities")
TRUST_BOUNDARY_FAILURE_TYPES = (
    "timeout",
    "auth_failure",
    "rate_limit",
    "partial_data",
    "schema_drift",
    "unavailable",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enum_value(v: object) -> str:
    """Return the string value of an enum-or-string field."""
    return v.value if hasattr(v, "value") else str(v)


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Deterministic invariant checks
# ---------------------------------------------------------------------------

def check_inv001_orphaned_nodes(contract: Contract) -> list[Violation]:
    """INV-001: nodes with no incoming AND no outgoing edges (unless terminal).

    External nodes are exempt because their counterparties live outside the
    modelled graph.
    """
    incoming: defaultdict[str, int] = defaultdict(int)
    outgoing: defaultdict[str, int] = defaultdict(int)
    for edge in contract.edges:
        outgoing[edge.source] += 1
        incoming[edge.target] += 1

    out: list[Violation] = []
    for node in contract.nodes:
        if _enum_value(node.kind) == NodeKind.EXTERNAL.value:
            continue
        if getattr(node, "is_terminal", False):
            continue
        if incoming[node.id] == 0 and outgoing[node.id] == 0:
            out.append(
                Violation(
                    id=_new_id(),
                    type=ViolationType.INVARIANT,
                    severity=Severity.ERROR,
                    message=(
                        f"Node {node.id} ({node.name}) has no incoming or "
                        "outgoing edges (INV-001)."
                    ),
                    affects=[node.id],
                    suggested_question=(
                        f"Should {node.name} be connected to another node, "
                        "or removed from the graph?"
                    ),
                )
            )
    return out


def check_inv002_unconsumed_outputs(contract: Contract) -> list[Violation]:
    """INV-002: a ``data`` edge has no target defined in nodes[]."""
    node_ids = {n.id for n in contract.nodes}
    out: list[Violation] = []
    for edge in contract.edges:
        if _enum_value(edge.kind) != EdgeKind.DATA.value:
            continue
        if not edge.target or edge.target not in node_ids:
            out.append(
                Violation(
                    id=_new_id(),
                    type=ViolationType.INVARIANT,
                    severity=Severity.ERROR,
                    message=(
                        f"Edge {edge.id} (kind=data) has no valid target "
                        "node (INV-002)."
                    ),
                    affects=[edge.id],
                    suggested_question=(
                        f"Where should the data on edge {edge.id} flow to?"
                    ),
                )
            )
    return out


def check_inv003_user_input_terminates(contract: Contract) -> list[Violation]:
    """INV-003: a ``ui`` node must transitively reach a ``store`` or ``external`` node."""
    by_id = {n.id: n for n in contract.nodes}
    adj: defaultdict[str, list[str]] = defaultdict(list)
    for edge in contract.edges:
        adj[edge.source].append(edge.target)

    def _reaches_terminal(start: str) -> bool:
        seen: set[str] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            node = by_id.get(cur)
            if node is None:
                continue
            kind = _enum_value(node.kind)
            if cur != start and kind in (
                NodeKind.STORE.value,
                NodeKind.EXTERNAL.value,
            ):
                return True
            for nxt in adj.get(cur, ()):
                if nxt not in seen:
                    stack.append(nxt)
        return False

    out: list[Violation] = []
    for node in contract.nodes:
        if _enum_value(node.kind) != NodeKind.UI.value:
            continue
        if not _reaches_terminal(node.id):
            out.append(
                Violation(
                    id=_new_id(),
                    type=ViolationType.INVARIANT,
                    severity=Severity.ERROR,
                    message=(
                        f"UI node {node.id} ({node.name}) does not reach any "
                        "store/external sink (INV-003)."
                    ),
                    affects=[node.id],
                    suggested_question=(
                        f"What persistent store or external system should "
                        f"{node.name}'s input ultimately reach?"
                    ),
                )
            )
    return out


def check_inv004_missing_payload_schema(contract: Contract) -> list[Violation]:
    """INV-004: ``data`` or ``event`` edges must have ``payload_schema`` set."""
    out: list[Violation] = []
    for edge in contract.edges:
        kind = _enum_value(edge.kind)
        if kind not in (EdgeKind.DATA.value, EdgeKind.EVENT.value):
            continue
        if not edge.payload_schema:
            out.append(
                Violation(
                    id=_new_id(),
                    type=ViolationType.INVARIANT,
                    severity=Severity.ERROR,
                    message=(
                        f"Edge {edge.id} is kind={kind} but has no "
                        "payload_schema (INV-004)."
                    ),
                    affects=[edge.id],
                    suggested_question=(
                        f"What is the JSON shape of the payload flowing "
                        f"across edge {edge.id}?"
                    ),
                )
            )
    return out


def check_inv005_low_confidence_unflagged(contract: Contract) -> list[Violation]:
    """INV-005: nodes/edges below the confidence threshold need open_questions."""
    out: list[Violation] = []
    for node in contract.nodes:
        if node.confidence < LOW_CONFIDENCE_THRESHOLD and not node.open_questions:
            out.append(
                Violation(
                    id=_new_id(),
                    type=ViolationType.INVARIANT,
                    severity=Severity.WARNING,
                    message=(
                        f"Node {node.id} has confidence {node.confidence:.2f} "
                        "but no open_questions (INV-005)."
                    ),
                    affects=[node.id],
                    suggested_question=(
                        f"What is uncertain about {node.name} that lowered "
                        "its confidence?"
                    ),
                )
            )
    by_id = {n.id: n for n in contract.nodes}
    for edge in contract.edges:
        if edge.confidence >= LOW_CONFIDENCE_THRESHOLD:
            continue
        endpoint_questions: list[str] = []
        for endpoint in (edge.source, edge.target):
            n = by_id.get(endpoint)
            if n is not None:
                endpoint_questions.extend(n.open_questions or [])
        if endpoint_questions:
            continue
        out.append(
            Violation(
                id=_new_id(),
                type=ViolationType.INVARIANT,
                severity=Severity.WARNING,
                message=(
                    f"Edge {edge.id} has confidence {edge.confidence:.2f} "
                    "and neither endpoint has open_questions (INV-005)."
                ),
                affects=[edge.id],
                suggested_question=(
                    f"What detail of edge {edge.id} is uncertain?"
                ),
            )
        )
    return out


def check_inv006_cyclic_data_dependency(contract: Contract) -> list[Violation]:
    """INV-006: no directed cycle restricted to ``kind: data`` edges."""
    adj: defaultdict[str, list[str]] = defaultdict(list)
    for edge in contract.edges:
        if _enum_value(edge.kind) == EdgeKind.DATA.value:
            adj[edge.source].append(edge.target)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(lambda: WHITE)
    parent: dict[str, str] = {}
    cycles: list[list[str]] = []

    def _dfs(start: str) -> None:
        stack: list[tuple[str, int]] = [(start, 0)]
        color[start] = GRAY
        while stack:
            node, idx = stack[-1]
            children = adj.get(node, [])
            if idx < len(children):
                stack[-1] = (node, idx + 1)
                child = children[idx]
                if color[child] == WHITE:
                    color[child] = GRAY
                    parent[child] = node
                    stack.append((child, 0))
                elif color[child] == GRAY:
                    # reconstruct cycle from `node` back up to `child`
                    cycle = [child, node]
                    cur = node
                    while cur != child and cur in parent:
                        cur = parent[cur]
                        cycle.append(cur)
                    cycles.append(list(dict.fromkeys(cycle)))
            else:
                color[node] = BLACK
                stack.pop()

    for n in contract.nodes:
        if color[n.id] == WHITE:
            _dfs(n.id)

    seen_keys: set[frozenset[str]] = set()
    out: list[Violation] = []
    for cycle in cycles:
        key = frozenset(cycle)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(
            Violation(
                id=_new_id(),
                type=ViolationType.INVARIANT,
                severity=Severity.ERROR,
                message=(
                    "Cyclic data dependency detected among nodes: "
                    + ", ".join(cycle)
                    + " (INV-006)."
                ),
                affects=list(cycle),
                suggested_question=(
                    "Which node should break the data cycle "
                    f"{ ' -> '.join(cycle) }?"
                ),
            )
        )
    return out


def check_inv007_dangling_assumptions(contract: Contract) -> list[Violation]:
    """INV-007: load_bearing & decided_by=agent assumptions must surface a question."""
    out: list[Violation] = []

    def _check(element_id: str, element_name: str, assumptions, open_questions):
        for a in assumptions or []:
            if not a.load_bearing:
                continue
            if _enum_value(a.decided_by) != "agent":
                continue
            if open_questions:
                continue
            out.append(
                Violation(
                    id=_new_id(),
                    type=ViolationType.INVARIANT,
                    severity=Severity.ERROR,
                    message=(
                        f"{element_name} ({element_id}) has load-bearing "
                        f"assumption \"{a.text}\" decided by agent but no "
                        "open_questions (INV-007)."
                    ),
                    affects=[element_id],
                    suggested_question=(
                        f'Did you intend "{a.text}" to be the chosen approach '
                        f"for {element_name}, or is there an alternative?"
                    ),
                )
            )

    for node in contract.nodes:
        _check(node.id, node.name, node.assumptions, node.open_questions)
    by_id = {n.id: n for n in contract.nodes}
    for edge in contract.edges:
        # Edges have no open_questions; consider their endpoints'.
        endpoint_questions = []
        for endpoint in (edge.source, edge.target):
            n = by_id.get(endpoint)
            if n is not None:
                endpoint_questions.extend(n.open_questions or [])
        edge_label = f"Edge {edge.label}" if edge.label else f"Edge {edge.id}"
        _check(edge.id, edge_label, edge.assumptions, endpoint_questions)
    return out


INVARIANT_CHECKS: tuple[tuple[str, Callable[[Contract], list[Violation]]], ...] = (
    ("INV-001", check_inv001_orphaned_nodes),
    ("INV-002", check_inv002_unconsumed_outputs),
    ("INV-003", check_inv003_user_input_terminates),
    ("INV-004", check_inv004_missing_payload_schema),
    ("INV-005", check_inv005_low_confidence_unflagged),
    ("INV-006", check_inv006_cyclic_data_dependency),
    ("INV-007", check_inv007_dangling_assumptions),
)


def run_invariant_checks(contract: Contract) -> list[Violation]:
    """Run every deterministic invariant and return the merged violation list."""
    out: list[Violation] = []
    for name, fn in INVARIANT_CHECKS:
        violations = fn(contract)
        log.debug(
            "compiler.invariant_check",
            extra={
                "invariant": name,
                "violation_count": len(violations),
                "passed": not violations,
            },
        )
        out.extend(violations)
    return out


# ---------------------------------------------------------------------------
# UVDC + ranking
# ---------------------------------------------------------------------------

def compute_uvdc(contract: Contract) -> float:
    """User-Visible Decision Coverage score.

    Defined as ``(# load-bearing fields decided_by user/prompt) / (# total
    load-bearing fields)``. Returns 1.0 when there are no load-bearing
    fields (vacuously fully covered).
    """
    total = 0
    user_or_prompt = 0

    def _bump(decided_by: object) -> None:
        nonlocal total, user_or_prompt
        total += 1
        if _enum_value(decided_by) in ("user", "prompt"):
            user_or_prompt += 1

    for node in contract.nodes:
        # Load-bearing node fields: kind + (responsibilities is implicitly
        # decided alongside the node).
        _bump(node.decided_by)
        for assumption in node.assumptions:
            if assumption.load_bearing:
                _bump(assumption.decided_by)
    for edge in contract.edges:
        _bump(edge.decided_by)
        for assumption in edge.assumptions:
            if assumption.load_bearing:
                _bump(assumption.decided_by)

    if total == 0:
        return 1.0
    return round(user_or_prompt / total, 4)


_VIOLATION_TYPE_RANK = {
    ViolationType.INTENT_MISMATCH.value: 0,
    ViolationType.INVARIANT.value: 1,
    ViolationType.FAILURE_SCENARIO.value: 2,
    ViolationType.PROVENANCE.value: 3,
}


def _violation_centrality(v: Violation, edge_count: dict[str, int]) -> int:
    return -sum(edge_count.get(eid, 0) for eid in (v.affects or []))


def rank_violations(
    violations: list[Violation],
    contract: Optional[Contract] = None,
) -> list[Violation]:
    """Return a ranked copy of *violations*.

    Tier order:
      1. intent_mismatch
      2. invariant errors
      3. failure_scenario
      4. provenance
      5. invariant warnings

    Within a tier, items affecting more-connected nodes/edges sort first.
    """
    edge_count: dict[str, int] = defaultdict(int)
    if contract is not None:
        for e in contract.edges:
            edge_count[e.source] += 1
            edge_count[e.target] += 1
            edge_count[e.id] += 1
        for n in contract.nodes:
            edge_count.setdefault(n.id, 0)

    def _tier(v: Violation) -> int:
        t = _enum_value(v.type)
        sev = _enum_value(v.severity)
        if t == ViolationType.INTENT_MISMATCH.value:
            return 0
        if t == ViolationType.INVARIANT.value and sev == Severity.ERROR.value:
            return 1
        if t == ViolationType.FAILURE_SCENARIO.value:
            return 2
        if t == ViolationType.PROVENANCE.value:
            return 3
        if t == ViolationType.INVARIANT.value and sev == Severity.WARNING.value:
            return 4
        return 5

    return sorted(
        violations,
        key=lambda v: (_tier(v), _violation_centrality(v, edge_count)),
    )


def emit_top_questions(
    violations: list[Violation],
    contract: Optional[Contract] = None,
    *,
    cap: int = MAX_QUESTIONS,
) -> list[str]:
    """Pick at most ``cap`` ranked, deduplicated questions."""
    out: list[str] = []
    seen: set[str] = set()
    for v in rank_violations(violations, contract):
        q = v.suggested_question
        if not q:
            continue
        if q in seen:
            continue
        seen.add(q)
        out.append(q)
        if len(out) >= cap:
            break
    return out


# ---------------------------------------------------------------------------
# LLM passes (intent / failure / provenance)
# ---------------------------------------------------------------------------

def _trust_boundary_edges(contract: Contract) -> list[Edge]:
    """Edges where source or target is an ``external`` node."""
    by_id = {n.id: n for n in contract.nodes}

    def _is_external(node_id: str) -> bool:
        n = by_id.get(node_id)
        return n is not None and _enum_value(n.kind) == NodeKind.EXTERNAL.value

    return [
        e
        for e in contract.edges
        if _is_external(e.source) or _is_external(e.target)
    ]


def _provenance_violations(contract: Contract) -> list[Violation]:
    """Static provenance check: load-bearing fields decided_by=agent."""
    out: list[Violation] = []
    for node in contract.nodes:
        if _enum_value(node.decided_by) == "agent":
            out.append(
                Violation(
                    id=_new_id(),
                    type=ViolationType.PROVENANCE,
                    severity=Severity.ERROR,
                    message=(
                        f"Node {node.id} ({node.name}) was decided by the "
                        "agent without user input."
                    ),
                    affects=[node.id],
                    suggested_question=(
                        f"Did you mean for {node.name} to be a "
                        f"{_enum_value(node.kind)}, or is there a different "
                        "choice you had in mind?"
                    ),
                )
            )
        for assumption in node.assumptions:
            if assumption.load_bearing and _enum_value(assumption.decided_by) == "agent":
                out.append(
                    Violation(
                        id=_new_id(),
                        type=ViolationType.PROVENANCE,
                        severity=Severity.ERROR,
                        message=(
                            f"Load-bearing assumption \"{assumption.text}\" "
                            f"on node {node.id} was decided by the agent."
                        ),
                        affects=[node.id],
                        suggested_question=(
                            f'Is "{assumption.text}" the right assumption for '
                            f"{node.name}, or do you have a different choice?"
                        ),
                    )
                )
    for edge in contract.edges:
        if _enum_value(edge.decided_by) == "agent":
            out.append(
                Violation(
                    id=_new_id(),
                    type=ViolationType.PROVENANCE,
                    severity=Severity.ERROR,
                    message=(
                        f"Edge {edge.id} kind/payload was decided by the "
                        "agent without user input."
                    ),
                    affects=[edge.id],
                    suggested_question=(
                        f"Did you intend edge {edge.id} to be a "
                        f"{_enum_value(edge.kind)} edge, or is there a "
                        "different relationship you had in mind?"
                    ),
                )
            )
    return out


def _failure_scenario_violations(contract: Contract) -> list[Violation]:
    """For each trust-boundary edge, surface a single failure-handling question.

    Pure-Python fallback; the LLM pass can refine these but this gives us
    deterministic coverage for tests and the no-LLM mode.
    """
    out: list[Violation] = []
    for edge in _trust_boundary_edges(contract):
        # Skip if there is already a resolved failure scenario for this edge.
        already = any(
            fs.affected_edge == edge.id and fs.resolved
            for fs in contract.failure_scenarios
        )
        if already:
            continue
        label = edge.label or edge.id
        out.append(
            Violation(
                id=_new_id(),
                type=ViolationType.FAILURE_SCENARIO,
                severity=Severity.ERROR,
                message=(
                    f"Edge {edge.id} ({label}) crosses a trust boundary but "
                    "has no documented failure handler for "
                    + ", ".join(TRUST_BOUNDARY_FAILURE_TYPES)
                    + "."
                ),
                affects=[edge.id],
                suggested_question=(
                    f"What should happen when {label} fails with a "
                    "timeout, auth_failure, or rate_limit?"
                ),
            )
        )
    return out


def _call_llm_passes(
    contract: Contract,
) -> tuple[list[Violation], str, list[NodeConfidenceUpdate]]:
    """Optional LLM passes (intent / failure / provenance + confidence update).

    Wraps :func:`app.llm.call_compiler`. Tests monkeypatch this function so
    they never hit the network.

    Returns a triple ``(extra_violations, intent_guess, confidence_updates)``.
    """
    # Local import to avoid hard dependency on the LLM stack at import time
    # (e.g. when pytest collection runs without API keys configured).
    from . import llm as llm_svc  # noqa: WPS433

    try:
        result: CompilerOutput = llm_svc.call_compiler(contract)
    except Exception as exc:  # pragma: no cover - network-only path
        log.warning(
            "compiler.llm_pass_failed",
            extra={
                "agent_type": "compiler",
                "error": str(exc),
                "contract_id": contract.meta.id,
            },
        )
        return [], "", []

    # Tag LLM-provided violations as semantic so the ranker treats them
    # alongside our deterministic ones, but use the LLM's intent_guess
    # directly.
    return (
        list(result.violations),
        result.intent_guess,
        list(result.confidence_updates),
    )


# ---------------------------------------------------------------------------
# Top-level verification
# ---------------------------------------------------------------------------

def verify_contract(
    contract: Contract,
    *,
    use_llm: bool = True,
    pass_number: int = 1,
) -> CompilerOutput:
    """Full Blind Compiler pipeline.

    Args:
        contract: contract to verify.
        use_llm: when False, skip the LLM passes — useful for tests and the
            offline ``--no-llm`` eval harness.
        pass_number: 1-indexed iteration number, propagated into logs so we
            can correlate the same session's repeated verifications.

    Returns:
        A :class:`CompilerOutput` populated from the deterministic checks
        and (optionally) the LLM passes.
    """
    log.info(
        "compiler.verify_start",
        extra={
            "agent_type": "compiler",
            "contract_id": contract.meta.id,
            "pass_number": pass_number,
            "use_llm": use_llm,
            "n_nodes": len(contract.nodes),
            "n_edges": len(contract.edges),
        },
    )
    started = time.perf_counter()

    invariant_violations = run_invariant_checks(contract)
    failure_violations = _failure_scenario_violations(contract)
    provenance_violations = _provenance_violations(contract)

    # Drop any violation whose suggested_question has already been answered
    # in a previous pass — once the user has spoken on a topic the Compiler
    # should not keep nagging.
    answered_questions = {d.question for d in contract.decisions if d.question}
    answered_affects = {
        target
        for d in contract.decisions
        for target in (d.affects or [])
    }

    def _already_answered(v: Violation) -> bool:
        if v.suggested_question and v.suggested_question in answered_questions:
            return True
        # Provenance / invariant questions tied to a specific node/edge that
        # the user has explicitly weighed in on are also considered answered.
        if (
            _enum_value(v.type) in (
                ViolationType.PROVENANCE.value,
                ViolationType.INVARIANT.value,
            )
            and v.affects
            and answered_affects
            and all(a in answered_affects for a in v.affects)
        ):
            # Only suppress provenance once the affected node/edge is now
            # decided_by user/prompt — INV-001..006 are structural and must
            # remain visible until they're actually fixed.
            if _enum_value(v.type) == ViolationType.PROVENANCE.value:
                return True
        return False

    invariant_violations = [v for v in invariant_violations if not _already_answered(v)]
    failure_violations = [v for v in failure_violations if not _already_answered(v)]
    provenance_violations = [v for v in provenance_violations if not _already_answered(v)]

    # Local intent guess as a deterministic fallback (in case the LLM is off).
    intent_guess = _heuristic_intent_guess(contract)
    confidence_updates: list[NodeConfidenceUpdate] = []

    extra_violations: list[Violation] = []
    if use_llm:
        llm_started = time.perf_counter()
        try:
            extra_violations, llm_intent, confidence_updates = _call_llm_passes(
                contract
            )
            if llm_intent:
                intent_guess = llm_intent
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "compiler.llm_pass_unexpected_error",
                extra={"error": str(exc)},
            )
        log.info(
            "compiler.llm_pass",
            extra={
                "agent_type": "compiler",
                "pass_name": "semantic_passes",
                "duration_ms": int((time.perf_counter() - llm_started) * 1000),
                "model": "claude-opus-4-5",
                "extra_violation_count": len(extra_violations),
            },
        )

    all_violations = (
        invariant_violations
        + failure_violations
        + provenance_violations
        + extra_violations
    )
    questions = emit_top_questions(all_violations, contract, cap=MAX_QUESTIONS)
    uvdc = compute_uvdc(contract)
    has_error = any(_enum_value(v.severity) == Severity.ERROR.value for v in all_violations)
    verdict = Verdict.FAIL if has_error else Verdict.PASS

    output = CompilerOutput(
        verdict=verdict,
        violations=rank_violations(all_violations, contract),
        questions=questions,
        intent_guess=intent_guess,
        uvdc_score=uvdc,
        confidence_updates=confidence_updates,
    )

    log.info(
        "compiler.verify_complete",
        extra={
            "agent_type": "compiler",
            "contract_id": contract.meta.id,
            "pass_number": pass_number,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "verdict": _enum_value(output.verdict),
            "violation_count": len(output.violations),
            "question_count": len(output.questions),
            "uvdc_score": uvdc,
        },
    )
    return output


def _heuristic_intent_guess(contract: Contract) -> str:
    """One-sentence guess at the system intent based on node names.

    Used when the LLM pass is unavailable. Not a substitute for the real
    intent reconstruction pass.
    """
    if contract.meta.stated_intent:
        # If the user/Architect already provided one, mirror it as our
        # best guess so we don't false-positive on intent_mismatch.
        return contract.meta.stated_intent
    names = ", ".join(n.name for n in contract.nodes[:4]) or "an unspecified system"
    return f"A system composed of: {names}."


__all__ = [
    "MAX_QUESTIONS",
    "LOW_CONFIDENCE_THRESHOLD",
    "INVARIANT_CHECKS",
    "check_inv001_orphaned_nodes",
    "check_inv002_unconsumed_outputs",
    "check_inv003_user_input_terminates",
    "check_inv004_missing_payload_schema",
    "check_inv005_low_confidence_unflagged",
    "check_inv006_cyclic_data_dependency",
    "check_inv007_dangling_assumptions",
    "run_invariant_checks",
    "compute_uvdc",
    "rank_violations",
    "emit_top_questions",
    "verify_contract",
]
