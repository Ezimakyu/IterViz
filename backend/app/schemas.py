"""Pydantic models for the architecture contract and Compiler I/O.

The shapes mirror ARCHITECTURE.md §4 (Contract) and §3 of SPEC.md
(four verification passes that drive `CompilerOutput`).

Design notes:
- Models are permissive about *missing* optional sections so seed fixtures
  in `scripts/seed_contracts/` can omit `verification_log`, `decisions`, etc.
- Models are *strict* about enum values, load-bearing decided_by, and
  required identifiers -- those are exercised by `tests/test_schemas.py`.
- We intentionally do not model deep JSON Schema for `payload_schema`;
  it is stored as an opaque dict so the Compiler can reason about its
  presence/absence without us re-validating arbitrary user JSON Schemas.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NodeKind(str, Enum):
    SERVICE = "service"
    STORE = "store"
    EXTERNAL = "external"
    UI = "ui"
    JOB = "job"
    INTERFACE = "interface"


class EdgeKind(str, Enum):
    DATA = "data"
    CONTROL = "control"
    EVENT = "event"
    DEPENDENCY = "dependency"


class DecidedBy(str, Enum):
    USER = "user"
    AGENT = "agent"
    PROMPT = "prompt"


class NodeStatus(str, Enum):
    DRAFTED = "drafted"
    IN_PROGRESS = "in_progress"
    IMPLEMENTED = "implemented"
    FAILED = "failed"


class ContractStatus(str, Enum):
    DRAFTING = "drafting"
    VERIFIED = "verified"
    IMPLEMENTING = "implementing"
    COMPLETE = "complete"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class ViolationType(str, Enum):
    INVARIANT = "invariant"
    FAILURE_SCENARIO = "failure_scenario"
    PROVENANCE = "provenance"
    INTENT_MISMATCH = "intent_mismatch"


class FailureType(str, Enum):
    TIMEOUT = "timeout"
    AUTH_FAILURE = "auth_failure"
    RATE_LIMIT = "rate_limit"
    PARTIAL_DATA = "partial_data"
    SCHEMA_DRIFT = "schema_drift"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

class Assumption(BaseModel):
    """A single belief held by a node or edge.

    Load-bearing assumptions must surface as questions when `decided_by:agent`
    (see SPEC.md §3.4).
    """

    model_config = ConfigDict(extra="allow")

    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    decided_by: DecidedBy
    load_bearing: bool = False


# ---------------------------------------------------------------------------
# Nodes / edges
# ---------------------------------------------------------------------------

class ActualInterface(BaseModel):
    model_config = ConfigDict(extra="allow")

    exports: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    public_functions: list[dict[str, Any]] = Field(default_factory=list)


class Implementation(BaseModel):
    model_config = ConfigDict(extra="allow")

    file_paths: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    actual_interface: Optional[ActualInterface] = None
    completed_at: Optional[datetime] = None


class Node(BaseModel):
    model_config = ConfigDict(extra="allow", use_enum_values=True)

    id: str
    name: str
    kind: NodeKind
    description: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    open_questions: list[str] = Field(default_factory=list)
    decided_by: DecidedBy = DecidedBy.AGENT
    status: NodeStatus = NodeStatus.DRAFTED
    sub_graph_ref: Optional[str] = None
    implementation: Optional[Implementation] = None
    # Optional flag in some fixtures for terminal nodes (sources/sinks).
    is_terminal: bool = False


class Edge(BaseModel):
    model_config = ConfigDict(extra="allow", use_enum_values=True)

    id: str
    source: str
    target: str
    kind: EdgeKind
    label: Optional[str] = None
    payload_schema: Optional[dict[str, Any]] = None
    assumptions: list[Assumption] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    decided_by: DecidedBy = DecidedBy.AGENT


# ---------------------------------------------------------------------------
# Other contract sections
# ---------------------------------------------------------------------------

class Invariant(BaseModel):
    model_config = ConfigDict(extra="allow", use_enum_values=True)

    id: str
    rule: str
    severity: Severity
    applies_to: list[str] = Field(default_factory=list)
    check_fn: Optional[str] = None


class FailureScenario(BaseModel):
    model_config = ConfigDict(extra="allow", use_enum_values=True)

    id: str
    trigger: str
    affected_edge: str
    failure_type: FailureType
    expected_handler: str  # node_id or the literal "unhandled"
    simulated_outcome: str = ""
    resolved: bool = False
    resolution_decision_id: Optional[str] = None


class Decision(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    question: str
    answer: str
    answered_at: Optional[datetime] = None
    affects: list[str] = Field(default_factory=list)
    source_violation_id: Optional[str] = None


class IntentReconstruction(BaseModel):
    model_config = ConfigDict(extra="allow")

    guess: Optional[str] = None
    match: Optional[bool] = None
    diff_notes: Optional[str] = None


class PromptHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str
    timestamp: Optional[datetime] = None


class Meta(BaseModel):
    model_config = ConfigDict(extra="allow", use_enum_values=True)

    id: str
    version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    frozen_at: Optional[datetime] = None
    frozen_hash: Optional[str] = None
    status: ContractStatus = ContractStatus.DRAFTING
    prompt_history: list[PromptHistoryEntry] = Field(default_factory=list)
    stated_intent: str = ""
    intent_reconstruction: Optional[IntentReconstruction] = None


class Violation(BaseModel):
    """A single Compiler-detected issue in a contract."""

    model_config = ConfigDict(extra="allow", use_enum_values=True)

    id: Optional[str] = None
    type: ViolationType
    severity: Severity
    message: str
    affects: list[str] = Field(default_factory=list)
    suggested_question: Optional[str] = None


class VerificationLogEntry(BaseModel):
    model_config = ConfigDict(extra="allow", use_enum_values=True)

    id: str
    run_at: datetime
    verdict: Verdict
    violations: list[Violation] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    intent_guess: str = ""
    uvdc_score: float = Field(default=0.0, ge=0.0, le=1.0)


class Contract(BaseModel):
    """Full architecture contract -- the shared source of truth."""

    model_config = ConfigDict(extra="allow")

    meta: Meta
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    invariants: list[Invariant] = Field(default_factory=list)
    failure_scenarios: list[FailureScenario] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    verification_log: list[VerificationLogEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_load_bearing_provenance(self) -> "Contract":
        """Load-bearing assumptions must declare `decided_by`.

        Pydantic already enforces the enum on the field; this validator only
        guards against assumptions whose load_bearing flag is set without an
        accompanying decision source coming from a non-default value.
        """
        for node in self.nodes:
            for assumption in node.assumptions:
                if assumption.load_bearing and not assumption.decided_by:
                    raise ValueError(
                        f"Node {node.id}: load-bearing assumption missing decided_by"
                    )
        for edge in self.edges:
            for assumption in edge.assumptions:
                if assumption.load_bearing and not assumption.decided_by:
                    raise ValueError(
                        f"Edge {edge.id}: load-bearing assumption missing decided_by"
                    )
        return self


# ---------------------------------------------------------------------------
# Compiler I/O
# ---------------------------------------------------------------------------

class CompilerOutput(BaseModel):
    """What the Blind Compiler returns for a single run.

    See SPEC.md §3 (four verification passes) and §4 (question budget = 5).
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    verdict: Verdict
    violations: list[Violation] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list, max_length=5)
    intent_guess: str

    @model_validator(mode="after")
    def _verdict_consistency(self) -> "CompilerOutput":
        # `use_enum_values=True` stores enums as their string values.
        verdict = self.verdict.value if isinstance(self.verdict, Verdict) else self.verdict
        has_error = any(
            (v.severity.value if isinstance(v.severity, Severity) else v.severity)
            == Severity.ERROR.value
            for v in self.violations
        )
        if has_error and verdict == Verdict.PASS.value:
            raise ValueError("verdict=pass but violations contain a severity=error item")
        return self


__all__ = [
    "Assumption",
    "ActualInterface",
    "Implementation",
    "Node",
    "NodeKind",
    "NodeStatus",
    "Edge",
    "EdgeKind",
    "DecidedBy",
    "Invariant",
    "FailureScenario",
    "FailureType",
    "Decision",
    "Meta",
    "ContractStatus",
    "IntentReconstruction",
    "PromptHistoryEntry",
    "Severity",
    "Violation",
    "ViolationType",
    "Verdict",
    "VerificationLogEntry",
    "Contract",
    "CompilerOutput",
]
