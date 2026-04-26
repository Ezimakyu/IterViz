"""End-to-end tests for FastAPI routes (with the LLM mocked)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import architect as architect_svc
from app.main import create_app

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
