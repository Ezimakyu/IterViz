# 02 — Compiler module (`backend/app/compiler.py`)

The Compiler is the heart of M3. Its public entrypoint is
`verify_contract(contract, *, use_llm=True, pass_number=1)`, which
returns a `CompilerOutput`. Everything else in the module is a helper
that contributes either deterministic violations, an LLM-derived
violation set, ranking, the UVDC score, or already-answered
suppression.

## Module shape

```
compiler.py
├── INV-001..007   pure-Python invariant checks (one function each)
│   └── run_invariant_checks()  — runs all seven, logs per-invariant
├── compute_uvdc(contract)             — User-Visible Decision Coverage
├── rank_violations(violations, ctx)   — tiered + centrality
├── emit_top_questions(violations, ctx, cap=5)
├── _provenance_violations(contract)   — static "decided_by: agent" sweep
├── _failure_scenario_violations()     — edges that cross trust boundaries
├── _call_llm_passes(contract)         — wraps llm.call_compiler
├── _already_answered(violation)       — closure inside verify_contract
└── verify_contract(...)               — orchestrator
```

## Deterministic invariants

| ID | Function | Triggers when… |
| --- | --- | --- |
| INV-001 | `check_inv001_orphaned_nodes` | A node has no incoming **and** no outgoing edges, unless `is_terminal: true`. |
| INV-002 | `check_inv002_unconsumed_outputs` | A `data` edge has no target node. |
| INV-003 | `check_inv003_user_input_terminates` | A `ui` node never reaches a `store` or `external` node via reachability. |
| INV-004 | `check_inv004_missing_payload_schema` | A `data` or `event` edge has `payload_schema = null`. |
| INV-005 | `check_inv005_low_confidence_unflagged` | A node or edge has `confidence < 0.6` but `open_questions` is empty. |
| INV-006 | `check_inv006_cyclic_data_dependency` | A cycle exists among `kind: data` edges (DFS-based detection). |
| INV-007 | `check_inv007_dangling_assumptions` | An assumption has `decided_by: agent` and `load_bearing: true` but no question recorded. |

`run_invariant_checks` runs all seven and emits one
`compiler.invariant_check` log line per check, including
`violation_count` and `passed: bool` for easy log filtering.

The invariants are intentionally **pure**: each takes a `Contract`,
returns a list of `Violation`, and never raises. They are the M3
guarantee that the loop produces *something* meaningful even if the
LLM is unreachable or returns garbage.

## UVDC score

`compute_uvdc(contract)` is the user-visible coverage number rendered
in the ControlBar:

```
UVDC = (# load-bearing fields decided_by user/prompt)
       / (# total load-bearing fields)
```

Counted fields:
- every node's `decided_by` (the node itself is load-bearing),
- every load-bearing assumption attached to a node,
- every edge's `decided_by`,
- every load-bearing assumption attached to an edge.

When `total == 0` we return `1.0` (vacuously fully covered) so a
trivial Contract does not report 0% coverage.

## Ranking & question cap

`rank_violations(violations, contract)` sorts violations into five
tiers (lower = higher priority):

```
0  intent_mismatch
1  invariant errors
2  failure_scenario
3  provenance
4  invariant warnings
5  everything else (defensive)
```

Within each tier, violations affecting more-connected nodes/edges
sort first. `_violation_centrality` simply sums the appearance count
of `affects[]` ids in the contract's adjacency map and returns it
negated (so larger counts come first when sorted ascending).

`emit_top_questions(violations, contract, cap=5)` walks the ranked
list, deduplicates by `suggested_question`, and stops at `cap`. The
cap is exported as `MAX_QUESTIONS = 5` and locked in by
`tests/test_compiler.py::test_max_five_questions`. The matching
frontend invariant — that the QuestionPanel never renders more than
five cards — is locked in by the live E2E run (assertion A4).

## LLM passes

`_call_llm_passes(contract)` is the only path into a real LLM in this
module. It calls `llm.call_compiler(...)` (the M1 wrapper, configured
for `claude-opus-4-5`) which returns a `CompilerLLMOutput`:

```
{
    "extra_violations": [Violation],
    "intent_guess": "string",
    "confidence_updates": [NodeConfidenceUpdate]
}
```

`verify_contract` swaps the deterministic intent guess for the LLM's
guess if one is returned, and copies the LLM's per-node
`confidence_updates` straight into `CompilerOutput`.

When `use_llm=False` (offline tests, the `--no-llm` eval harness, or
when `ANTHROPIC_API_KEY` is unset) the LLM block is skipped entirely,
`extra_violations` is empty, and the deterministic
`_heuristic_intent_guess` is used.

## Already-answered suppression

This is the M3-defining behaviour: once the user answers a question,
the same question must never appear again, even if a later LLM pass
re-raises it. The implementation lives inside `verify_contract` as a
closure:

```python
answered_questions = {d.question for d in contract.decisions if d.question}
answered_affects   = {a for d in contract.decisions for a in (d.affects or [])}

def _already_answered(v: Violation) -> bool:
    if v.suggested_question in answered_questions:
        return True
    if (v.type == ViolationType.PROVENANCE
        and v.affects
        and all(a in answered_affects for a in v.affects)):
        return True
    return False
```

Three filter passes use this predicate:

1. `invariant_violations`, `failure_violations`, and
   `provenance_violations` are filtered immediately after the
   deterministic checks return.
2. `extra_violations` (from the LLM) is filtered **after**
   `_call_llm_passes` returns, before merging into `all_violations`.
   This is the second of the four bugs in `07-bugs-found-and-fixed.md`
   — without this filter the LLM can re-introduce a question the user
   has already answered.
3. Structural invariants (INV-001..006) are explicitly **not**
   suppressed by `affects` membership alone — only the provenance
   tier is, since that is the only tier where "the user weighed in"
   is sufficient to consider the issue resolved. INV-001..006 must
   stay visible until they are actually fixed in the contract.

## Logging

`verify_contract` emits the following structured log entries for each
session/pass:

| Event | Keys |
| --- | --- |
| `compiler.verify_start` | `agent_type`, `contract_id`, `pass_number`, `use_llm`, `n_nodes`, `n_edges` |
| `compiler.invariant_check` (×7) | `invariant`, `violation_count`, `passed` |
| `compiler.llm_pass` | `pass_name`, `duration_ms`, `model`, `extra_violation_count` |
| `compiler.verify_complete` | `pass_number`, `duration_ms`, `verdict`, `violation_count`, `question_count`, `uvdc_score` |

Acceptance assertion **A10** (live E2E test plan) is the existence of
exactly three `compiler.verify_complete` entries per session, paired
with three `architect.refine.complete` entries.
