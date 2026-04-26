"""Schema validation tests.

Covers:
- Valid contract JSON (every seeded contract that is *structurally* valid).
- Invalid JSON raises pydantic.ValidationError with a useful message.
- Load-bearing assumptions still require `decided_by`.
- Edge cases: empty nodes list, missing required fields, invalid enums.
- CompilerOutput verdict consistency check.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import (
    Assumption,
    CompilerOutput,
    Contract,
    DecidedBy,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    Severity,
    Verdict,
    Violation,
    ViolationType,
)


# --- Loading the seed fixtures ---------------------------------------------

def test_every_seed_contract_parses(seed_contracts_dir: Path) -> None:
    """All seed contracts (except the sidecar) must parse with our schema.

    Even the *invalid-by-design* fixtures should parse — invalidity is
    semantic (e.g. INV-001 violation) not schema-level.
    """
    files = [p for p in seed_contracts_dir.glob("*.json") if p.name != "_expected.json"]
    assert files, "expected seed contracts on disk"
    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        Contract.model_validate(raw)  # raises if shape is wrong


def test_sample_valid_contract_has_expected_shape(sample_valid_contract: Contract) -> None:
    assert sample_valid_contract.meta.id == "c-valid-simple"
    assert len(sample_valid_contract.nodes) >= 3
    assert any(n.kind == NodeKind.STORE.value for n in sample_valid_contract.nodes)
    assert any(e.kind == EdgeKind.DATA.value for e in sample_valid_contract.edges)


# --- Negative cases --------------------------------------------------------

def test_missing_required_meta_id_raises() -> None:
    with pytest.raises(ValidationError) as exc:
        Contract.model_validate({"meta": {}, "nodes": [], "edges": []})
    assert "meta" in str(exc.value)


def test_invalid_node_kind_raises() -> None:
    bad = {
        "meta": {"id": "c1"},
        "nodes": [
            {"id": "n1", "name": "n1", "kind": "not_a_kind"}
        ],
        "edges": [],
    }
    with pytest.raises(ValidationError):
        Contract.model_validate(bad)


def test_invalid_decided_by_raises() -> None:
    with pytest.raises(ValidationError):
        Assumption(text="t", confidence=0.5, decided_by="moon", load_bearing=False)


def test_confidence_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        Node(id="n1", name="x", kind=NodeKind.SERVICE, confidence=1.5)
    with pytest.raises(ValidationError):
        Edge(id="e1", source="a", target="b", kind=EdgeKind.DATA, confidence=-0.1)


def test_empty_nodes_list_is_allowed() -> None:
    """A bare contract (e.g. immediately after submission) should parse."""
    c = Contract.model_validate({"meta": {"id": "c1"}, "nodes": [], "edges": []})
    assert c.nodes == []


def test_load_bearing_assumption_requires_decided_by() -> None:
    """`decided_by` is required by the field's enum; absent -> ValidationError."""
    bad_assumption = {
        "text": "S3 is the right backing store.",
        "confidence": 0.6,
        "load_bearing": True,
        # decided_by intentionally missing
    }
    with pytest.raises(ValidationError):
        Assumption.model_validate(bad_assumption)


# --- CompilerOutput contract ----------------------------------------------

def test_compiler_output_pass_with_no_violations() -> None:
    out = CompilerOutput(verdict=Verdict.PASS, violations=[], questions=[], intent_guess="x")
    assert out.verdict in (Verdict.PASS, Verdict.PASS.value)


def test_compiler_output_pass_with_error_violation_raises() -> None:
    """If any violation is severity=error, verdict cannot be `pass`."""
    with pytest.raises(ValidationError):
        CompilerOutput(
            verdict=Verdict.PASS,
            violations=[
                Violation(
                    type=ViolationType.INVARIANT,
                    severity=Severity.ERROR,
                    message="bad",
                    affects=["n1"],
                )
            ],
            questions=[],
            intent_guess="x",
        )


def test_compiler_output_fail_with_error_violation_ok() -> None:
    out = CompilerOutput(
        verdict=Verdict.FAIL,
        violations=[
            Violation(
                type=ViolationType.INVARIANT,
                severity=Severity.ERROR,
                message="bad",
                affects=["n1"],
            )
        ],
        questions=["fix?"],
        intent_guess="x",
    )
    assert out.verdict in (Verdict.FAIL, Verdict.FAIL.value)
    assert len(out.violations) == 1


def test_compiler_output_question_budget_enforced() -> None:
    """At most 5 questions per run (SPEC.md §4)."""
    with pytest.raises(ValidationError):
        CompilerOutput(
            verdict=Verdict.PASS,
            violations=[],
            questions=[f"q{i}?" for i in range(6)],
            intent_guess="x",
        )


def test_compiler_output_rejects_unknown_keys() -> None:
    """`extra=forbid` on CompilerOutput keeps the LLM honest."""
    with pytest.raises(ValidationError):
        CompilerOutput.model_validate(
            {
                "verdict": "pass",
                "violations": [],
                "questions": [],
                "intent_guess": "x",
                "phantom_field": True,
            }
        )


def test_violation_invalid_type_raises() -> None:
    with pytest.raises(ValidationError):
        Violation.model_validate(
            {"type": "made_up_type", "severity": "error", "message": "m"}
        )


# --- Round-tripping --------------------------------------------------------

def test_contract_round_trip_preserves_ids(sample_valid_contract: Contract) -> None:
    serialized = sample_valid_contract.model_dump_json()
    reloaded = Contract.model_validate(json.loads(serialized))
    assert {n.id for n in reloaded.nodes} == {n.id for n in sample_valid_contract.nodes}
    assert {e.id for e in reloaded.edges} == {e.id for e in sample_valid_contract.edges}


# --- Helper: ensure ValidationError messages are useful --------------------

def test_validation_error_message_mentions_field() -> None:
    try:
        Contract.model_validate({"meta": {"id": "c1"}, "nodes": [{"id": "n1"}], "edges": []})
    except ValidationError as exc:
        msg = str(exc)
        # Should mention which field on the node is missing/invalid.
        assert re.search(r"\bname\b|\bkind\b", msg), msg
    else:
        pytest.fail("expected ValidationError")
