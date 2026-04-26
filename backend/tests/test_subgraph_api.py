"""HTTP + WebSocket tests for the M6 implementation-subgraph endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import architect as architect_svc
from app import compiler as compiler_svc
from app import subgraph as subgraph_svc
from app import subgraphs as subgraphs_store
from app.main import create_app
from app.schemas import SubgraphNodeStatus

from .conftest import make_sample_contract


@pytest.fixture
def client(temp_db, monkeypatch):
    """TestClient with the architect/compiler stubbed and subgraph generation
    pinned to the deterministic fallback path (no LLM)."""

    def _fake_generate(prompt: str):
        c = make_sample_contract(prompt=prompt)
        c.meta.prompt_history[0].content = prompt
        return c

    monkeypatch.setattr(architect_svc, "generate_contract", _fake_generate)
    monkeypatch.setattr(
        architect_svc,
        "refine_contract",
        lambda contract, answers: contract,
    )
    monkeypatch.setattr(
        compiler_svc,
        "_call_llm_passes",
        lambda contract: ([], contract.meta.stated_intent or "", []),
    )

    real_generate = subgraph_svc.generate_subgraph

    def _no_llm_generate(node, contract, neighbor_interfaces=None, *, use_llm=True):
        return real_generate(
            node, contract, neighbor_interfaces, use_llm=False
        )

    monkeypatch.setattr(subgraph_svc, "generate_subgraph", _no_llm_generate)

    subgraphs_store.clear_all()

    app = create_app()
    with TestClient(app) as c:
        yield c

    subgraphs_store.clear_all()


def _start_session(client) -> tuple[str, list[dict]]:
    resp = client.post(
        "/api/v1/sessions",
        json={"prompt": "Build a TODO app with auth"},
    )
    assert resp.status_code == 201
    body = resp.json()
    return body["session_id"], body["contract"]["nodes"]


# ---------------------------------------------------------------------------
# Generate / get / get-all
# ---------------------------------------------------------------------------


def test_generate_subgraph_returns_subgraph_with_parent_id(client):
    sid, nodes = _start_session(client)
    node = nodes[1]

    resp = client.post(f"/api/v1/sessions/{sid}/nodes/{node['id']}/subgraph")
    assert resp.status_code == 200, resp.text

    data = resp.json()
    sg = data["subgraph"]
    assert sg["parent_node_id"] == node["id"]
    assert sg["parent_node_name"] == node["name"]
    assert sg["session_id"] == sid
    assert sg["nodes"], "subgraph should contain at least one node"


def test_generate_subgraph_unknown_node_returns_404(client):
    sid, _ = _start_session(client)
    resp = client.post(f"/api/v1/sessions/{sid}/nodes/does-not-exist/subgraph")
    assert resp.status_code == 404


def test_generate_subgraph_unknown_session_returns_404(client):
    resp = client.post("/api/v1/sessions/missing/nodes/x/subgraph")
    assert resp.status_code == 404


def test_get_subgraph_returns_null_before_generation(client):
    sid, nodes = _start_session(client)
    resp = client.get(f"/api/v1/sessions/{sid}/nodes/{nodes[0]['id']}/subgraph")
    assert resp.status_code == 200
    assert resp.json() == {"subgraph": None}


def test_get_subgraph_returns_stored_subgraph_after_generation(client):
    sid, nodes = _start_session(client)
    nid = nodes[0]["id"]
    client.post(f"/api/v1/sessions/{sid}/nodes/{nid}/subgraph")

    resp = client.get(f"/api/v1/sessions/{sid}/nodes/{nid}/subgraph")
    assert resp.status_code == 200
    sg = resp.json()["subgraph"]
    assert sg is not None
    assert sg["parent_node_id"] == nid


def test_get_all_subgraphs_returns_all_generated(client):
    sid, nodes = _start_session(client)
    for n in nodes[:2]:
        client.post(f"/api/v1/sessions/{sid}/nodes/{n['id']}/subgraph")

    resp = client.get(f"/api/v1/sessions/{sid}/subgraphs")
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) == 2
    assert {sg["parent_node_id"] for sg in payload} == {n["id"] for n in nodes[:2]}


# ---------------------------------------------------------------------------
# PATCH status updates
# ---------------------------------------------------------------------------


def test_update_subgraph_node_status_succeeds_and_updates_progress(client):
    sid, nodes = _start_session(client)
    nid = nodes[1]["id"]

    gen = client.post(f"/api/v1/sessions/{sid}/nodes/{nid}/subgraph").json()
    sg_node_id = gen["subgraph"]["nodes"][0]["id"]

    resp = client.patch(
        f"/api/v1/sessions/{sid}/nodes/{nid}/subgraph/nodes/{sg_node_id}",
        json={"status": SubgraphNodeStatus.COMPLETED.value},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["subgraph"]["progress"] > 0


def test_update_subgraph_node_status_no_subgraph_returns_success_false(client):
    sid, nodes = _start_session(client)
    nid = nodes[1]["id"]

    resp = client.patch(
        f"/api/v1/sessions/{sid}/nodes/{nid}/subgraph/nodes/whatever",
        json={"status": SubgraphNodeStatus.COMPLETED.value},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"success": False, "subgraph": None}


def test_update_subgraph_node_status_unknown_subnode_returns_404(client):
    sid, nodes = _start_session(client)
    nid = nodes[0]["id"]
    client.post(f"/api/v1/sessions/{sid}/nodes/{nid}/subgraph")

    resp = client.patch(
        f"/api/v1/sessions/{sid}/nodes/{nid}/subgraph/nodes/missing",
        json={"status": SubgraphNodeStatus.IN_PROGRESS.value},
    )
    assert resp.status_code == 404


def test_update_subgraph_node_status_rejects_extra_fields(client):
    sid, nodes = _start_session(client)
    nid = nodes[0]["id"]
    gen = client.post(f"/api/v1/sessions/{sid}/nodes/{nid}/subgraph").json()
    sg_node_id = gen["subgraph"]["nodes"][0]["id"]

    resp = client.patch(
        f"/api/v1/sessions/{sid}/nodes/{nid}/subgraph/nodes/{sg_node_id}",
        json={
            "status": SubgraphNodeStatus.COMPLETED.value,
            "subgraph_node_id": "stale",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# WebSocket fan-out
# ---------------------------------------------------------------------------


def test_ws_receives_subgraph_created_and_status_changed(client):
    sid, nodes = _start_session(client)
    nid = nodes[0]["id"]

    with client.websocket_connect(f"/api/v1/sessions/{sid}/stream") as ws:
        gen = client.post(
            f"/api/v1/sessions/{sid}/nodes/{nid}/subgraph"
        ).json()
        created = ws.receive_json()
        assert created["type"] == "subgraph_created"
        assert created["parent_node_id"] == nid
        assert created["subgraph"]["id"] == gen["subgraph"]["id"]

        sg_node_id = gen["subgraph"]["nodes"][0]["id"]
        client.patch(
            f"/api/v1/sessions/{sid}/nodes/{nid}/subgraph/nodes/{sg_node_id}",
            json={"status": SubgraphNodeStatus.IN_PROGRESS.value},
        )
        progress = ws.receive_json()
        assert progress["type"] == "subgraph_node_status_changed"
        assert progress["parent_node_id"] == nid
        assert progress["subgraph_node_id"] == sg_node_id
        assert progress["status"] == SubgraphNodeStatus.IN_PROGRESS.value
