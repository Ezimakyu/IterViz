# 06 — Tests + logger

## Tests (`backend/tests/`)

```
tests/
├── __init__.py
├── conftest.py        # fixtures, sys.path injection, CannedLLMClient
└── test_schemas.py    # 16 schema validation tests
```

`pytest tests/test_schemas.py` → 16/16 passing on this branch.

### `conftest.py`

Provides shared fixtures and ensures `backend/` is on `sys.path` so
tests can `from app.schemas import ...` regardless of where pytest is
invoked from.

Fixtures:

- `seed_contracts_dir` → `Path` to `backend/scripts/seed_contracts/`.
- `sample_valid_contract` → parsed `valid_simple.json` as a `Contract`.
- `sample_invalid_contracts` → dict of `{filename: Contract}` for the
  seven invalid fixtures.
- `mock_llm_client` → `CannedLLMClient`, a deterministic stand-in that
  returns a pre-recorded `CompilerOutput` per contract. Lets future
  M2/M3 tests exercise the orchestrator without spending API budget.

### `test_schemas.py` — what's tested

The 16 tests cover three concerns:

**Loading the corpus**
1. `test_every_seed_contract_parses` — every fixture parses with
   `Contract.model_validate(...)`. Even invalid-by-design fixtures
   parse; invalidity is *semantic*, not schema-level.
2. `test_sample_valid_contract_has_expected_shape` — sanity check on
   the anchor fixture.

**Negative cases**
3. `test_missing_required_meta_id_raises`
4. `test_invalid_node_kind_raises`
5. `test_invalid_decided_by_raises`
6. `test_confidence_out_of_range_raises` (both Node and Edge sides)
7. `test_empty_nodes_list_is_allowed` (positive — bare contract OK)
8. `test_load_bearing_assumption_requires_decided_by`

**`CompilerOutput` contract**
9. `test_compiler_output_pass_with_no_violations`
10. `test_compiler_output_pass_with_error_violation_raises`
    (verdict↔severity validator)
11. `test_compiler_output_fail_with_error_violation_ok`
12. `test_compiler_output_question_budget_enforced` (max 5)
13. `test_compiler_output_extra_field_rejected` (`extra="forbid"`)

**Round-trip + invariants on Violation**
14. `test_compiler_output_round_trips_via_json`
15. `test_violation_requires_message_and_type`
16. `test_violation_severity_enum_strict`

The breakdown roughly mirrors the constraints listed in
[`01-schemas.md`](./01-schemas.md). Every Pydantic constraint we rely
on at runtime has at least one test asserting it fails on bad input.

### What the tests don't cover

- **Live LLM behaviour.** That's what `eval_compiler.py` is for; pytest
  is the offline lane.
- **Prompt content.** The prompt is a markdown file; testing its
  exact text is brittle and unhelpful. We exercise its semantics via
  the eval harness against the seed corpus instead.
- **Question prioritization.** SPEC.md's priority ladder is enforced
  in the prompt only. Verifying it requires multi-tier fixtures that
  don't exist yet — a M2 follow-up.

## Logger (`backend/app/logger.py`)

Eighty lines, exposes one function: `get_logger(name: str)`.

### Behaviour

- One JSON object per line on stderr.
- Default level: `INFO`. `DEBUG=1` env var bumps to `DEBUG`.
- `extra={"key": value, ...}` on the call site is hoisted to top-level
  keys in the JSON record (after filtering reserved `LogRecord` attrs).
- Idempotent: re-importing the logger doesn't double-attach handlers.
  We tag our handler with `_glasshouse_handler = True` and skip if one
  is already present.
- `propagate = False` so records don't bubble up to the root logger
  and double-print.

### Record shape

```json
{
  "timestamp": "2026-04-26T00:08:55.123456+00:00",
  "level":     "INFO",
  "module":    "app.llm",
  "message":   "compiler call completed",
  "agent_type":      "compiler",
  "provider":        "anthropic",
  "model":           "claude-opus-4-5",
  "duration_ms":     14211,
  "verdict":         "pass",
  "violation_count": 0,
  "question_count":  0
}
```

The `extra` dict is the contract between caller and downstream tools —
field names mirror what M2's structured logs will need
(`session_id`, `agent_type`, etc., per ARCHITECTURE.md §9).

### Why JSON-per-line?

ARCHITECTURE.md §9 specifies it explicitly. Practical implications:

- `jq` works directly: `python scripts/eval_compiler.py 2>logs.jsonl;
  jq 'select(.level=="ERROR")' logs.jsonl`.
- Cloud log shippers (Datadog, Logstash, GCP Logging) auto-parse
  single-line JSON without custom regex parsers.
- DEBUG mode just changes the level filter — record shape is identical
  between INFO and DEBUG, so dashboards work in both.
