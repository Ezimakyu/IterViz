"""Pydantic models that mirror the ``architecture_contract.json`` schema.

See ARCHITECTURE.md §4 for the canonical structure.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums (kept as Literal types for cleaner JSON schema)
# ---------------------------------------------------------------------------

DecidedBy = Literal["user", "agent", "prompt"]
NodeKind = Literal["service", "store", "external", "ui", "job", "interface"]
NodeStatus = Literal["drafted", "in_progress", "implemented", "failed"]
EdgeKind = Literal["data", "control", "event", "dependency"]
ContractStatus = Literal["drafting", "verified", "implementing", "complete"]
Severity = Literal["error", "warning"]
ViolationType = Literal[
    "invariant", "failure_scenario", "provenance", "intent_mismatch"
]
FailureType = Literal[
    "timeout", "auth_failure", "rate_limit", "partial_data",
    "schema_drift", "unavailable",
]
Verdict = Literal["pass", "fail"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Shared fragments
# ---------------------------------------------------------------------------


class Assumption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    decided_by: DecidedBy
    load_bearing: bool


# ---------------------------------------------------------------------------
# Node + edge
# ---------------------------------------------------------------------------


class PublicFunction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    signature: str


class ActualInterface(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exports: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    public_functions: list[PublicFunction] = Field(default_factory=list)


class Implementation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_paths: list[str] = Field(default_factory=list)
    notes: str = ""
    actual_interface: ActualInterface = Field(default_factory=ActualInterface)
    completed_at: Optional[str] = None


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_uuid)
    name: str
    kind: NodeKind
    description: str
    responsibilities: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    open_questions: list[str] = Field(default_factory=list)
    decided_by: DecidedBy
    status: NodeStatus = "drafted"
    sub_graph_ref: Optional[str] = None
    implementation: Optional[Implementation] = None


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_uuid)
    source: str
    target: str
    kind: EdgeKind
    label: Optional[str] = None
    payload_schema: Optional[dict[str, Any]] = None
    assumptions: list[Assumption] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    decided_by: DecidedBy


# ---------------------------------------------------------------------------
# Top-level fragments
# ---------------------------------------------------------------------------


class PromptHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: str = Field(default_factory=_now_iso)


class IntentReconstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guess: str
    match: bool
    diff_notes: Optional[str] = None


class ContractMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_uuid)
    version: int = 1
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    frozen_at: Optional[str] = None
    frozen_hash: Optional[str] = None
    status: ContractStatus = "drafting"
    prompt_history: list[PromptHistoryEntry] = Field(default_factory=list)
    stated_intent: str
    intent_reconstruction: Optional[IntentReconstruction] = None


class Invariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    rule: str
    severity: Severity
    applies_to: list[Literal["nodes", "edges"]]
    check_fn: str


class FailureScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_uuid)
    trigger: str
    affected_edge: str
    failure_type: FailureType
    expected_handler: str
    simulated_outcome: str
    resolved: bool = False
    resolution_decision_id: Optional[str] = None


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_uuid)
    question: str
    answer: str
    answered_at: str = Field(default_factory=_now_iso)
    affects: list[str] = Field(default_factory=list)
    source_violation_id: Optional[str] = None


class Violation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_uuid)
    type: ViolationType
    severity: Severity
    message: str
    affects: list[str] = Field(default_factory=list)
    suggested_question: Optional[str] = None


class VerificationLogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_uuid)
    run_at: str = Field(default_factory=_now_iso)
    verdict: Verdict
    violations: list[Violation] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    intent_guess: str = ""
    uvdc_score: float = Field(ge=0.0, le=1.0, default=0.0)


# ---------------------------------------------------------------------------
# Top-level Contract
# ---------------------------------------------------------------------------


class Contract(BaseModel):
    """Full architecture contract. Centerpiece of the system."""

    model_config = ConfigDict(extra="forbid")

    meta: ContractMeta
    nodes: list[Node] = Field(default_factory=list, min_length=1)
    edges: list[Edge] = Field(default_factory=list)
    invariants: list[Invariant] = Field(default_factory=list)
    failure_scenarios: list[FailureScenario] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    verification_log: list[VerificationLogEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API request/response models
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1)


class CreateSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    contract: Contract


class GetSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: Contract


class RefineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[Decision]


class RefineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: Contract
    diff: dict[str, Any] = Field(default_factory=dict)
