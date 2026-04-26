"""Shared pytest fixtures for the Glasshouse backend tests."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterator

import pytest

from app import contract as contract_svc
from app.schemas import (
    Assumption,
    Contract,
    ContractMeta,
    Edge,
    Node,
    PromptHistoryEntry,
)


def _new_id() -> str:
    return str(uuid.uuid4())


def make_sample_contract(prompt: str = "Build a TODO app with auth") -> Contract:
    """Return a minimally-valid contract: 3 nodes + 2 edges."""
    n_ui = Node(
        id=_new_id(),
        name="Web UI",
        kind="ui",
        description="Frontend SPA for the TODO app.",
        responsibilities=["render todos", "submit forms"],
        assumptions=[
            Assumption(
                text="React + Vite",
                confidence=0.7,
                decided_by="agent",
                load_bearing=True,
            )
        ],
        confidence=0.8,
        decided_by="prompt",
    )
    n_api = Node(
        id=_new_id(),
        name="API Server",
        kind="service",
        description="FastAPI HTTP server exposing CRUD + auth.",
        responsibilities=["routes", "auth", "validation"],
        assumptions=[
            Assumption(
                text="FastAPI + JWT",
                confidence=0.6,
                decided_by="agent",
                load_bearing=True,
            )
        ],
        confidence=0.75,
        decided_by="prompt",
    )
    n_db = Node(
        id=_new_id(),
        name="Database",
        kind="store",
        description="Relational store for users + todos.",
        responsibilities=["persist users", "persist todos"],
        assumptions=[
            Assumption(
                text="Postgres 15",
                confidence=0.5,
                decided_by="agent",
                load_bearing=True,
            )
        ],
        confidence=0.65,
        open_questions=["Which database engine?"],
        decided_by="agent",
    )
    edges = [
        Edge(
            id=_new_id(),
            source=n_ui.id,
            target=n_api.id,
            kind="data",
            payload_schema={
                "type": "object",
                "properties": {"action": {"type": "string"}},
                "required": ["action"],
            },
            confidence=0.8,
            decided_by="agent",
        ),
        Edge(
            id=_new_id(),
            source=n_api.id,
            target=n_db.id,
            kind="data",
            payload_schema={
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
            confidence=0.75,
            decided_by="agent",
        ),
    ]
    return Contract(
        meta=ContractMeta(
            stated_intent="A TODO app with user auth.",
            prompt_history=[PromptHistoryEntry(role="user", content=prompt)],
        ),
        nodes=[n_ui, n_api, n_db],
        edges=edges,
    )


@pytest.fixture
def sample_contract() -> Contract:
    return make_sample_contract()


@pytest.fixture
def temp_db(tmp_path: Path) -> Iterator[Path]:
    db = tmp_path / "test.db"
    contract_svc.set_db_path(db)
    contract_svc.init_db()
    try:
        yield db
    finally:
        contract_svc.set_db_path(None)
