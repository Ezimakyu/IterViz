"""End-to-end tests for FastAPI routes (with the LLM mocked)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import architect as architect_svc
from app import compiler as compiler_svc
from app.main import create_app
from app.schemas import DecidedBy, NodeKind

from .conftest import make_sample_contract


@pytest.fixture
def client(temp_db, monkeypatch):
    """Build an isolated app + replace the Architect's LLM call."""

    def _fake_generate(prompt: str):
        c = make_sample_contract(prompt=prompt)
        # Mirror what the real architect does to prompt_history.
        c.meta.prompt_history[0].content = prompt
        return c

    monkeypatch.setattr(architect_svc, "generate_contract", _fake_generate)
    monkeypatch.setattr(
        architect_svc,
        "refine_contract",
        lambda contract, answers: contract,  # no-op for these tests
    )
    # Skip the optional LLM pass so verify is fully deterministic.
    monkeypatch.setattr(
        compiler_svc,
        "_call_llm_passes",
        lambda contract: ([], contract.meta.stated_intent or "", []),
    )

    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_post_sessions_returns_201_and_contract(client):
    resp = client.post(
        "/api/v1/sessions",
        json={"prompt": "Build a TODO app with auth"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "session_id" in body and body["session_id"]
    assert "contract" in body
    contract = body["contract"]

    assert len(contract["nodes"]) >= 3
    assert len(contract["edges"]) >= 2

    # Edges must reference real node ids.
    node_ids = {n["id"] for n in contract["nodes"]}
    for e in contract["edges"]:
        assert e["source"] in node_ids
        assert e["target"] in node_ids


def test_post_sessions_then_get(client):
    resp = client.post(
        "/api/v1/sessions",
        json={"prompt": "ship it"},
    )
    body = resp.json()
    sid = body["session_id"]

    fetched = client.get(f"/api/v1/sessions/{sid}")
    assert fetched.status_code == 200
    fb = fetched.json()
    assert fb["contract"]["meta"]["id"] == body["contract"]["meta"]["id"]
    assert fb["contract"]["meta"]["stated_intent"] == \
        body["contract"]["meta"]["stated_intent"]


def test_get_unknown_session_404(client):
    resp = client.get("/api/v1/sessions/does-not-exist")
    assert resp.status_code == 404


def test_post_sessions_rejects_missing_prompt(client):
    resp = client.post("/api/v1/sessions", json={})
    assert resp.status_code == 422


def test_post_sessions_rejects_empty_prompt(client):
    resp = client.post("/api/v1/sessions", json={"prompt": ""})
    assert resp.status_code == 422


def test_refine_endpoint_round_trip(client):
    created = client.post(
        "/api/v1/sessions",
        json={"prompt": "Build a TODO app with auth"},
    ).json()
    sid = created["session_id"]

    refined = client.post(
        f"/api/v1/sessions/{sid}/architect/refine",
        json={
            "answers": [
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "question": "Which DB?",
                    "answer": "Postgres",
                    "answered_at": "2025-01-01T00:00:00+00:00",
                    "affects": [],
                    "source_violation_id": None,
                }
            ]
        },
    )
    assert refined.status_code == 200, refined.text
    body = refined.json()
    assert body["contract"]["meta"]["id"] == sid


def test_refine_unknown_session_404(client):
    resp = client.post(
        "/api/v1/sessions/missing/architect/refine",
        json={"answers": []},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# M3: compiler / answers / refine endpoints
# ---------------------------------------------------------------------------

def _create_session(client, prompt: str = "Build a TODO app with auth") -> dict:
    resp = client.post("/api/v1/sessions", json={"prompt": prompt})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_verify_returns_violations_for_invalid_contract(client, monkeypatch):
    """A contract with an agent-decided UI node returns a non-empty violation set."""
    def _fake_generate(prompt: str):
        c = make_sample_contract(prompt=prompt)
        # Force at least one provenance/INV-007 issue.
        c.nodes[0].decided_by = DecidedBy.AGENT
        return c

    monkeypatch.setattr(architect_svc, "generate_contract", _fake_generate)
    body = _create_session(client)
    sid = body["session_id"]

    resp = client.post(f"/api/v1/sessions/{sid}/compiler/verify")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["verdict"] in ("pass", "fail")
    assert isinstance(data["violations"], list)
    assert isinstance(data["questions"], list)
    assert 0.0 <= data["uvdc_score"] <= 1.0


def test_verify_returns_empty_violations_for_valid_contract(client, monkeypatch):
    """A clean contract decided_by=user/prompt should pass with no errors."""
    def _fake_generate(prompt: str):
        c = make_sample_contract(prompt=prompt)
        for n in c.nodes:
            n.decided_by = DecidedBy.PROMPT
            n.confidence = 0.95
            n.assumptions = []
            n.open_questions = []
        for e in c.edges:
            e.decided_by = DecidedBy.PROMPT
            e.confidence = 0.95
            e.assumptions = []
        # Make sure the UI node reaches a store (already true here).
        return c

    monkeypatch.setattr(architect_svc, "generate_contract", _fake_generate)
    body = _create_session(client)
    sid = body["session_id"]
    resp = client.post(f"/api/v1/sessions/{sid}/compiler/verify")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    error_violations = [v for v in data["violations"] if v["severity"] == "error"]
    assert error_violations == []
    assert data["verdict"] == "pass"


def test_submit_answers_records_decisions(client):
    body = _create_session(client)
    sid = body["session_id"]
    payload = {
        "decisions": [
            {
                "id": "00000000-0000-0000-0000-000000000010",
                "question": "Which DB?",
                "answer": "Postgres",
                "answered_at": "2025-01-01T00:00:00+00:00",
                "affects": [],
                "source_violation_id": None,
            }
        ]
    }
    resp = client.post(f"/api/v1/sessions/{sid}/answers", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert any(
        d["question"] == "Which DB?" for d in data["contract"]["decisions"]
    )


def test_refine_updates_contract_with_answers(client):
    body = _create_session(client)
    sid = body["session_id"]
    payload = {
        "answers": [
            {
                "id": "00000000-0000-0000-0000-000000000020",
                "question": "Confirm DB?",
                "answer": "Postgres 16",
                "answered_at": "2025-01-01T00:00:00+00:00",
                "affects": [],
                "source_violation_id": None,
            }
        ]
    }
    resp = client.post(
        f"/api/v1/sessions/{sid}/architect/refine", json=payload
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["contract"]["meta"]["id"] == sid
    assert "diff" in data


def test_verification_log_persisted(client):
    body = _create_session(client)
    sid = body["session_id"]
    client.post(f"/api/v1/sessions/{sid}/compiler/verify")
    client.post(f"/api/v1/sessions/{sid}/compiler/verify")
    fetched = client.get(f"/api/v1/sessions/{sid}")
    log = fetched.json()["contract"]["verification_log"]
    assert len(log) == 2
    assert all("verdict" in entry for entry in log)


def test_verify_unknown_session_404(client):
    resp = client.post("/api/v1/sessions/missing/compiler/verify")
    assert resp.status_code == 404


def test_refine_with_empty_body_uses_existing_decisions(client):
    body = _create_session(client)
    sid = body["session_id"]
    # Submit an answer first.
    client.post(
        f"/api/v1/sessions/{sid}/answers",
        json={
            "decisions": [
                {
                    "id": "00000000-0000-0000-0000-000000000030",
                    "question": "DB choice?",
                    "answer": "Postgres 16",
                    "answered_at": "2025-01-01T00:00:00+00:00",
                    "affects": [],
                    "source_violation_id": None,
                }
            ]
        },
    )
    resp = client.post(
        f"/api/v1/sessions/{sid}/architect/refine", json={}
    )
    assert resp.status_code == 200, resp.text
