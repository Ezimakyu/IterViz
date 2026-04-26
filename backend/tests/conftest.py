"""Shared pytest fixtures for the Glasshouse backend tests.

Adds `backend/` to sys.path so `import app...` works when pytest is
launched from anywhere. Exposes:

Compiler / schema fixtures (M1):
- ``seed_contracts_dir`` — Path to ``scripts/seed_contracts``.
- ``sample_valid_contract`` — parsed ``valid_simple.json``.
- ``sample_invalid_contracts`` — every other seeded contract.
- ``mock_llm_client`` / ``mock_llm_client_failing`` — canned Compiler
  stubs, no network.

Architect / persistence fixtures (M2):
- ``sample_contract`` — a hand-built Contract with ≥3 nodes and ≥2 edges
  suitable for exercising CRUD without a live LLM.
- ``temp_db`` — points ``app.contract`` at a per-test SQLite file.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Iterator

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas import (  # noqa: E402
    Assumption,
    CompilerOutput,
    Contract,
    DecidedBy,
    Edge,
    EdgeKind,
    Meta,
    Node,
    NodeKind,
    PromptHistoryEntry,
    Severity,
    Verdict,
    Violation,
    ViolationType,
)


# ---------------------------------------------------------------------------
# Seed contracts (used by M1 compiler tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def seed_contracts_dir() -> Path:
    return BACKEND / "scripts" / "seed_contracts"


def _load(p: Path) -> Contract:
    return Contract.model_validate(json.loads(p.read_text(encoding="utf-8")))


@pytest.fixture
def sample_valid_contract(seed_contracts_dir: Path) -> Contract:
    return _load(seed_contracts_dir / "valid_simple.json")


@pytest.fixture
def sample_invalid_contracts(seed_contracts_dir: Path) -> dict[str, Contract]:
    contracts: dict[str, Contract] = {}
    for path in sorted(seed_contracts_dir.glob("*.json")):
        if path.name in {"_expected.json", "valid_simple.json"}:
            continue
        contracts[path.stem] = _load(path)
    return contracts


# ---------------------------------------------------------------------------
# Canned LLM client (M1)
# ---------------------------------------------------------------------------

class _CannedCompletions:
    def __init__(self, response: CompilerOutput) -> None:
        self._response = response

    def create(self, **_: Any) -> CompilerOutput:  # noqa: ANN401
        return self._response


class _CannedChat:
    def __init__(self, response: CompilerOutput) -> None:
        self.completions = _CannedCompletions(response)


class CannedLLMClient:
    """Stand-in for an ``instructor``-patched chat client."""

    def __init__(self, response: CompilerOutput | None = None) -> None:
        if response is None:
            response = CompilerOutput(
                verdict=Verdict.PASS,
                violations=[],
                questions=[],
                intent_guess="A pipeline that processes data end to end.",
            )
        self.chat = _CannedChat(response)


@pytest.fixture
def mock_llm_client() -> CannedLLMClient:
    return CannedLLMClient()


@pytest.fixture
def mock_llm_client_failing() -> CannedLLMClient:
    response = CompilerOutput(
        verdict=Verdict.FAIL,
        violations=[
            Violation(
                type=ViolationType.INVARIANT,
                severity=Severity.ERROR,
                message="Node n-orphan has no edges (INV-001).",
                affects=["n-orphan"],
                suggested_question="Should n-orphan be connected, or removed?",
            )
        ],
        questions=["Should n-orphan be connected, or removed?"],
        intent_guess="A graph with a disconnected node.",
    )
    return CannedLLMClient(response)


# ---------------------------------------------------------------------------
# Architect / persistence fixtures (M2)
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return str(uuid.uuid4())


def make_sample_contract(prompt: str = "Build a TODO app with auth") -> Contract:
    """Return a minimally-valid contract: 3 nodes + 2 edges."""
    n_ui = Node(
        id=_new_id(),
        name="Web UI",
        kind=NodeKind.UI,
        description="Frontend SPA for the TODO app.",
        responsibilities=["render todos", "submit forms"],
        assumptions=[
            Assumption(
                text="React + Vite",
                confidence=0.7,
                decided_by=DecidedBy.AGENT,
                load_bearing=True,
            )
        ],
        confidence=0.8,
        decided_by=DecidedBy.PROMPT,
    )
    n_api = Node(
        id=_new_id(),
        name="API Server",
        kind=NodeKind.SERVICE,
        description="FastAPI HTTP server exposing CRUD + auth.",
        responsibilities=["routes", "auth", "validation"],
        assumptions=[
            Assumption(
                text="FastAPI + JWT",
                confidence=0.6,
                decided_by=DecidedBy.AGENT,
                load_bearing=True,
            )
        ],
        confidence=0.75,
        decided_by=DecidedBy.PROMPT,
    )
    n_db = Node(
        id=_new_id(),
        name="Database",
        kind=NodeKind.STORE,
        description="Relational store for users + todos.",
        responsibilities=["persist users", "persist todos"],
        assumptions=[
            Assumption(
                text="Postgres 15",
                confidence=0.5,
                decided_by=DecidedBy.AGENT,
                load_bearing=True,
            )
        ],
        confidence=0.65,
        open_questions=["Which database engine?"],
        decided_by=DecidedBy.AGENT,
    )
    edges = [
        Edge(
            id=_new_id(),
            source=n_ui.id,
            target=n_api.id,
            kind=EdgeKind.DATA,
            payload_schema={
                "type": "object",
                "properties": {"action": {"type": "string"}},
                "required": ["action"],
            },
            confidence=0.8,
            decided_by=DecidedBy.AGENT,
        ),
        Edge(
            id=_new_id(),
            source=n_api.id,
            target=n_db.id,
            kind=EdgeKind.DATA,
            payload_schema={
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
            confidence=0.75,
            decided_by=DecidedBy.AGENT,
        ),
    ]
    return Contract(
        meta=Meta(
            id=_new_id(),
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
    from app import contract as contract_svc

    db = tmp_path / "test.db"
    contract_svc.set_db_path(db)
    contract_svc.init_db()
    try:
        yield db
    finally:
        contract_svc.set_db_path(None)
