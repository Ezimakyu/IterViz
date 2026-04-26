"""Tests for app.architect with the LLM call mocked out."""

from __future__ import annotations

import uuid

import pytest

from app import architect as architect_svc
from app.schemas import Contract, Decision

from .conftest import make_sample_contract


def _new_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def mock_llm(monkeypatch):
    """Replace ``call_structured`` with a deterministic stub.

    The stub returns the contract stored on ``mock_llm.next_contract``,
    so each test sets the response and then asserts on the result.
    """

    class _Mock:
        def __init__(self) -> None:
            self.next_contract: Contract = make_sample_contract()
            self.calls: list[dict[str, str]] = []

        def __call__(self, *, response_model, system, user, **_kwargs):
            assert response_model is Contract
            self.calls.append({"system": system, "user": user})
            return self.next_contract.model_copy(deep=True)

    mock = _Mock()
    monkeypatch.setattr(architect_svc, "call_structured", mock)
    return mock


def test_generate_contract_basic(mock_llm):
    contract = architect_svc.generate_contract("Build a TODO app")
    assert isinstance(contract, Contract)
    assert len(contract.nodes) >= 3
    assert len(contract.edges) >= 2
    assert contract.meta.version == 1
    assert any(
        e.role == "user" and e.content == "Build a TODO app"
        for e in contract.meta.prompt_history
    )

    assert len(mock_llm.calls) == 1
    assert "TODO" in mock_llm.calls[0]["user"]


def test_generate_contract_rejects_empty():
    with pytest.raises(ValueError):
        architect_svc.generate_contract("")
    with pytest.raises(ValueError):
        architect_svc.generate_contract("   ")


def test_generate_contract_all_nodes_have_required_fields(mock_llm):
    contract = architect_svc.generate_contract("Build a thing")
    for node in contract.nodes:
        assert node.id
        assert node.name
        assert node.kind in {
            "service", "store", "external", "ui", "job", "interface"
        }
        assert 0.0 <= node.confidence <= 1.0
        assert node.decided_by in {"user", "agent", "prompt"}


def test_generate_contract_edges_reference_real_nodes(mock_llm):
    contract = architect_svc.generate_contract("Build a thing")
    node_ids = {n.id for n in contract.nodes}
    for edge in contract.edges:
        assert edge.source in node_ids
        assert edge.target in node_ids


def test_refine_contract_appends_answers_and_bumps_version(mock_llm):
    base = make_sample_contract()
    mock_llm.next_contract = base.model_copy(deep=True)

    answers = [
        Decision(
            id=_new_id(),
            question="Which database?",
            answer="Postgres 15",
            affects=[base.nodes[2].id],
        ),
        Decision(
            id=_new_id(),
            question="Auth strategy?",
            answer="JWT in httpOnly cookies",
            affects=[base.nodes[1].id],
        ),
    ]
    refined = architect_svc.refine_contract(base, answers)

    assert refined.meta.id == base.meta.id
    assert refined.meta.version == base.meta.version + 1
    assert refined.meta.created_at == base.meta.created_at
    assert refined.meta.updated_at != base.meta.updated_at
    assert {d.id for d in refined.decisions} >= {a.id for a in answers}


def test_refine_contract_does_not_drop_pre_existing_decisions(mock_llm):
    base = make_sample_contract()
    pre = Decision(id=_new_id(), question="Existing?", answer="yes")
    base.decisions.append(pre)

    response = base.model_copy(deep=True)
    mock_llm.next_contract = response

    new_answer = Decision(id=_new_id(), question="New?", answer="also yes")
    refined = architect_svc.refine_contract(base, [new_answer])

    ids = {d.id for d in refined.decisions}
    assert pre.id in ids
    assert new_answer.id in ids
