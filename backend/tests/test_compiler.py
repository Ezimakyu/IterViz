"""Unit tests for the deterministic Blind Compiler invariant checks (M3).

These tests run *only* the deterministic checks — `verify_contract` is
called with ``use_llm=False`` so no network access is required.
"""

from __future__ import annotations

import uuid

import pytest

from app.compiler import (
    INVARIANT_CHECKS,
    MAX_QUESTIONS,
    check_inv001_orphaned_nodes,
    check_inv002_unconsumed_outputs,
    check_inv003_user_input_terminates,
    check_inv004_missing_payload_schema,
    check_inv005_low_confidence_unflagged,
    check_inv006_cyclic_data_dependency,
    check_inv007_dangling_assumptions,
    compute_uvdc,
    emit_top_questions,
    rank_violations,
    run_invariant_checks,
    verify_contract,
)
from app.schemas import (
    Assumption,
    Contract,
    DecidedBy,
    Edge,
    EdgeKind,
    Meta,
    Node,
    NodeKind,
    Severity,
    Verdict,
    Violation,
    ViolationType,
)


def _id() -> str:
    return str(uuid.uuid4())


def _node(
    *,
    name: str,
    kind: NodeKind = NodeKind.SERVICE,
    confidence: float = 1.0,
    open_questions=None,
    assumptions=None,
    decided_by: DecidedBy = DecidedBy.PROMPT,
    is_terminal: bool = False,
) -> Node:
    return Node(
        id=_id(),
        name=name,
        kind=kind,
        responsibilities=[f"do {name}"],
        confidence=confidence,
        open_questions=open_questions or [],
        assumptions=assumptions or [],
        decided_by=decided_by,
        is_terminal=is_terminal,
    )


def _edge(
    src: Node,
    tgt: Node,
    *,
    kind: EdgeKind = EdgeKind.DATA,
    payload: dict | None = None,
    confidence: float = 1.0,
    decided_by: DecidedBy = DecidedBy.PROMPT,
) -> Edge:
    if payload is None and kind == EdgeKind.DATA:
        payload = {"type": "object"}
    return Edge(
        id=_id(),
        source=src.id,
        target=tgt.id,
        kind=kind,
        payload_schema=payload,
        confidence=confidence,
        decided_by=decided_by,
    )


def _contract(nodes: list[Node], edges: list[Edge], *, intent: str = "") -> Contract:
    return Contract(
        meta=Meta(id=_id(), stated_intent=intent),
        nodes=nodes,
        edges=edges,
    )


# ---------------------------------------------------------------------------
# Per-invariant tests
# ---------------------------------------------------------------------------

def test_inv001_orphaned_node_detected():
    a = _node(name="A")
    b = _node(name="B")
    orphan = _node(name="Orphan")
    contract = _contract([a, b, orphan], [_edge(a, b)])
    violations = check_inv001_orphaned_nodes(contract)
    assert len(violations) == 1
    assert violations[0].affects == [orphan.id]
    assert "INV-001" in violations[0].message


def test_inv001_terminal_and_external_exempt():
    sink = _node(name="Sink", is_terminal=True)
    ext = _node(name="External", kind=NodeKind.EXTERNAL)
    a = _node(name="A")
    contract = _contract([sink, ext, a], [])
    # Only `a` should be flagged.
    violations = check_inv001_orphaned_nodes(contract)
    assert {v.affects[0] for v in violations} == {a.id}


def test_inv002_unconsumed_output_detected():
    a = _node(name="A")
    b = _node(name="B")
    edge = _edge(a, b)
    edge.target = "missing-node-id"
    contract = _contract([a, b], [edge])
    violations = check_inv002_unconsumed_outputs(contract)
    assert len(violations) == 1
    assert "INV-002" in violations[0].message


def test_inv003_ui_must_reach_store_or_external():
    ui = _node(name="UI", kind=NodeKind.UI)
    svc = _node(name="Svc")
    isolated_ui = _node(name="OrphanUI", kind=NodeKind.UI)
    store = _node(name="DB", kind=NodeKind.STORE)
    contract = _contract(
        [ui, svc, isolated_ui, store],
        [_edge(ui, svc), _edge(svc, store)],
    )
    violations = check_inv003_user_input_terminates(contract)
    assert {v.affects[0] for v in violations} == {isolated_ui.id}


def test_inv004_missing_payload_schema_for_data_edge():
    a = _node(name="A")
    b = _node(name="B")
    edge = _edge(a, b)
    edge.payload_schema = None
    contract = _contract([a, b], [edge])
    violations = check_inv004_missing_payload_schema(contract)
    assert len(violations) == 1
    assert violations[0].affects == [edge.id]


def test_inv004_event_edge_also_requires_payload():
    a = _node(name="A")
    b = _node(name="B")
    edge = _edge(a, b, kind=EdgeKind.EVENT, payload=None)
    contract = _contract([a, b], [edge])
    violations = check_inv004_missing_payload_schema(contract)
    assert len(violations) == 1


def test_inv005_low_confidence_node_without_question():
    n = _node(name="Shaky", confidence=0.4)
    contract = _contract([n], [])
    violations = check_inv005_low_confidence_unflagged(contract)
    assert len(violations) == 1
    assert violations[0].severity == Severity.WARNING.value
    assert violations[0].affects == [n.id]


def test_inv005_low_confidence_with_question_passes():
    n = _node(
        name="Shaky",
        confidence=0.4,
        open_questions=["Are we sure?"],
    )
    contract = _contract([n], [])
    assert check_inv005_low_confidence_unflagged(contract) == []


def test_inv006_cyclic_data_dependency():
    a = _node(name="A")
    b = _node(name="B")
    c = _node(name="C")
    contract = _contract(
        [a, b, c],
        [_edge(a, b), _edge(b, c), _edge(c, a)],
    )
    violations = check_inv006_cyclic_data_dependency(contract)
    assert len(violations) >= 1
    cycle_nodes = set(violations[0].affects)
    assert {a.id, b.id, c.id} <= cycle_nodes


def test_inv007_dangling_assumption():
    n = _node(
        name="Mystery",
        assumptions=[
            Assumption(
                text="Stripe will be the payments processor",
                confidence=0.8,
                decided_by=DecidedBy.AGENT,
                load_bearing=True,
            )
        ],
    )
    contract = _contract([n, _node(name="B")], [_edge(n, _node(name="B"))])
    violations = check_inv007_dangling_assumptions(contract)
    assert len(violations) >= 1


# ---------------------------------------------------------------------------
# Aggregate / ranking / UVDC
# ---------------------------------------------------------------------------

def test_valid_contract_passes_all_invariants():
    a = _node(name="A")
    b = _node(name="B")
    store = _node(name="DB", kind=NodeKind.STORE)
    contract = _contract([a, b, store], [_edge(a, b), _edge(b, store)])
    assert run_invariant_checks(contract) == []


def test_inv_check_registry_covers_inv001_through_inv007():
    ids = {name for name, _ in INVARIANT_CHECKS}
    assert ids == {f"INV-00{i}" for i in range(1, 8)}


def test_violations_ranked_by_severity():
    invariant_warning = Violation(
        type=ViolationType.INVARIANT,
        severity=Severity.WARNING,
        message="warn",
        affects=[],
        suggested_question="warn?",
    )
    invariant_error = Violation(
        type=ViolationType.INVARIANT,
        severity=Severity.ERROR,
        message="err",
        affects=[],
        suggested_question="err?",
    )
    intent = Violation(
        type=ViolationType.INTENT_MISMATCH,
        severity=Severity.ERROR,
        message="intent",
        affects=[],
        suggested_question="intent?",
    )
    ranked = rank_violations([invariant_warning, invariant_error, intent])
    assert ranked[0].type == ViolationType.INTENT_MISMATCH.value
    assert ranked[1].type == ViolationType.INVARIANT.value
    assert ranked[1].severity == Severity.ERROR.value
    assert ranked[-1].severity == Severity.WARNING.value


def test_emit_top_questions_caps_at_five():
    violations = [
        Violation(
            type=ViolationType.INVARIANT,
            severity=Severity.ERROR,
            message=f"v{i}",
            affects=[],
            suggested_question=f"q{i}?",
        )
        for i in range(10)
    ]
    qs = emit_top_questions(violations)
    assert len(qs) == MAX_QUESTIONS == 5
    # Deduplicates.
    duped = violations + violations
    assert len(emit_top_questions(duped)) == 5


def test_uvdc_score_calculation_all_user():
    n = _node(name="A", decided_by=DecidedBy.USER)
    contract = _contract([n], [])
    assert compute_uvdc(contract) == 1.0


def test_uvdc_score_calculation_partial():
    a = _node(name="A", decided_by=DecidedBy.PROMPT)
    b = _node(name="B", decided_by=DecidedBy.AGENT)
    edge = _edge(a, b, decided_by=DecidedBy.AGENT)
    contract = _contract([a, b], [edge])
    score = compute_uvdc(contract)
    # 1 of 3 load-bearing decisions came from prompt/user.
    assert 0.0 < score < 1.0
    assert score == pytest.approx(1 / 3, rel=1e-2)


def test_uvdc_score_no_load_bearing_returns_one():
    contract = _contract([], [])
    assert compute_uvdc(contract) == 1.0


# ---------------------------------------------------------------------------
# verify_contract integration (no LLM)
# ---------------------------------------------------------------------------

def test_verify_contract_no_llm_clean_contract_passes():
    a = _node(name="A")
    b = _node(name="B")
    store = _node(name="DB", kind=NodeKind.STORE)
    contract = _contract(
        [a, b, store],
        [_edge(a, b), _edge(b, store)],
        intent="A simple pipeline.",
    )
    out = verify_contract(contract, use_llm=False)
    # Provenance violations may still exist if any node is decided_by=agent;
    # our nodes default to PROMPT so it should be clean.
    error_violations = [
        v for v in out.violations
        if v.severity == Severity.ERROR.value
    ]
    assert error_violations == []
    assert out.verdict == Verdict.PASS.value


def test_verify_contract_no_llm_dirty_contract_fails():
    a = _node(name="A")
    b = _node(name="B", decided_by=DecidedBy.AGENT)
    contract = _contract([a, b, _node(name="C")], [_edge(a, b)])
    out = verify_contract(contract, use_llm=False)
    assert out.verdict == Verdict.FAIL.value
    assert any(
        v.type == ViolationType.INVARIANT.value
        and "INV-001" in v.message
        for v in out.violations
    )
    assert len(out.questions) <= MAX_QUESTIONS
