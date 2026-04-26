# 01 — Schemas (`backend/app/schemas.py`)

The schemas mirror `ARCHITECTURE.md §4` (Contract) and `SPEC.md §3`
(four verification passes that drive `CompilerOutput`). They are the
single source of truth shared between every M1+ agent.

## Posture: permissive about *missing* sections, strict about *values*

Seed fixtures need to be writable by hand. Forcing every fixture to carry
a `verification_log` array, a `decisions` array, a `frozen_at` timestamp,
etc., would either bloat the fixtures or push us toward a builder DSL.
Instead we treat every container as `Field(default_factory=list)` and
every optional metadata field as `Optional[...] = None`.

What we are strict about:

| Constraint | Where it lives | Why |
|---|---|---|
| Enum membership for `kind`, `decided_by`, `severity`, `verdict`, `failure_type` | Pydantic `Enum` types | Stops the LLM from inventing new taxonomy buckets. |
| `confidence ∈ [0, 1]` | `Field(ge=0, le=1)` on `Node`, `Edge`, `Assumption` | Catches off-by-one prompts that emit `confidence: 9` or negative numbers. |
| `questions: max_length=5` | `CompilerOutput.questions` | Hard cap from SPEC.md §3 question budget. |
| `extra="forbid"` on `CompilerOutput` | `model_config` | Blocks chain-of-thought leakage. The LLM cannot smuggle a `reasoning` field past `instructor`. |
| Verdict ↔ severity consistency | `_verdict_consistency` model validator | If any violation has `severity=error`, `verdict` MUST be `fail`. |
| Load-bearing assumption has `decided_by` | `_check_load_bearing_provenance` model validator | Defensive — Pydantic enum already catches missing values, but this gives a node-attributed message. |

## Enum types

Defined in lock-step with the prompt taxonomy:

- `NodeKind`: `service | store | external | ui | job | interface`
- `EdgeKind`: `data | control | event | dependency`
- `DecidedBy`: `user | agent | prompt`
- `Severity`: `error | warning`
- `Verdict`: `pass | fail`
- `ViolationType`: `invariant | failure_scenario | provenance | intent_mismatch`
- `FailureType`: `timeout | auth_failure | rate_limit | partial_data | schema_drift | unavailable`

`use_enum_values=True` is set on Pydantic configs so JSON dumps emit the
string values (e.g. `"error"`, not `"<Severity.ERROR>"`). Tests assert
both forms because instructor sometimes returns the enum and sometimes
returns the string depending on provider.

## Why an `is_terminal: bool` was added to `Node`

INV-001 (orphaned_node) flags any node with no incoming or outgoing
edges. Two of our seed fixtures legitimately have a terminal node:

- `unhandled_failure.json` — `n-store` (Postgres) is the sink.
- `valid_simple.json` — `n-stripe` is the source.

Adding `is_terminal: true` to those fixtures, and exempting it in the
prompt, removes a class of legitimate-but-flag-worthy false positives
without weakening the invariant for everyone else. The flag is **not**
in the SPEC's contract definition — it's an M1 ergonomics escape hatch,
and we documented it as such in the schema docstring.

## Why `payload_schema` is `Optional[dict[str, Any]]`

The architecture contract should reference *external* JSON Schemas (see
ARCHITECTURE.md §4); we're not in the business of validating arbitrary
JSON Schema structures recursively. Storing it as an opaque dict lets the
Compiler reason about presence/absence (INV-004) without us re-validating
user JSON Schemas — which would be a separate, much bigger problem.

## `CompilerOutput` — the type instructor enforces

```python
class CompilerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)
    verdict: Verdict
    violations: list[Violation] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list, max_length=5)
    intent_guess: str
```

This is the only shape `app/llm.py` accepts back from the LLM. Everything
else — the prompt, the matcher, the seed fixtures — is shaped around
producing instances of this class.

## `Violation` and the matcher contract

```python
class Violation(BaseModel):
    id: Optional[str] = None
    type: ViolationType
    severity: Severity
    message: str
    affects: list[str] = Field(default_factory=list)
    suggested_question: Optional[str] = None
```

Two non-obvious choices:

1. `id` is optional. The Compiler doesn't need to invent stable IDs for
   findings during M1 — that becomes useful when M2 starts persisting
   them and tracking resolution decisions.
2. `affects` is a flat `list[str]`, not a structured reference. The
   matcher in `eval_compiler.py` does set-overlap on this; richer
   structures (e.g. `{type: "node", id: "..."}`) would force the prompt
   to follow a more brittle output shape with no recall benefit on the
   M1 corpus.
