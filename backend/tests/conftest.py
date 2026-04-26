"""Shared pytest fixtures for the Glasshouse backend tests.

Adds `backend/` to sys.path so `import app...` works when pytest is
launched from anywhere. Also exposes:

- `seed_contracts_dir`  — Path to the canonical seed-contract directory.
- `sample_valid_contract` — parsed `valid_simple.json` as a `Contract`.
- `sample_invalid_contracts` — dict of contract-name -> parsed `Contract`
  for every other seeded fixture.
- `mock_llm_client` — a thin object whose `.chat.completions.create`
  returns canned `CompilerOutput` instances (no network).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas import (  # noqa: E402
    CompilerOutput,
    Contract,
    Severity,
    Verdict,
    Violation,
    ViolationType,
)


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


class _CannedCompletions:
    def __init__(self, response: CompilerOutput) -> None:
        self._response = response

    def create(self, **_: Any) -> CompilerOutput:  # noqa: ANN401
        return self._response


class _CannedChat:
    def __init__(self, response: CompilerOutput) -> None:
        self.completions = _CannedCompletions(response)


class CannedLLMClient:
    """Stand-in for an `instructor`-patched chat client.

    Tests can construct one with a custom CompilerOutput, or use the default
    pass-through response for `valid_simple` smoke tests.
    """

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
    """A canned client that always returns a verdict=pass response."""
    return CannedLLMClient()


@pytest.fixture
def mock_llm_client_failing() -> CannedLLMClient:
    """A canned client that returns one invariant violation."""
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
