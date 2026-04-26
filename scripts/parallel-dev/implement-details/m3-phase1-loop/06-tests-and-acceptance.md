# 06 — Tests + acceptance criteria

M3 ships **31 new tests** on top of M1 + M2's 38, for a total of
**69 backend tests** all passing locally and in CI. The tests are
organised into three layers — Compiler unit tests, integration tests
that drive the full Phase 1 loop, and API tests that exercise the
HTTP surface end-to-end.

## `tests/test_compiler.py` (19 unit tests)

One pure-Python test per invariant plus the supporting infrastructure:

| Test | Locks in… |
| --- | --- |
| `test_inv001_orphaned_node_detected` | INV-001 fires for orphan nodes. |
| `test_inv001_terminal_and_external_exempt` | `is_terminal: true` and `kind: external` are excluded from INV-001. |
| `test_inv002_unconsumed_output_detected` | INV-002 fires when a `data` edge has no target. |
| `test_inv003_ui_must_reach_store_or_external` | `ui` nodes that don't reach a `store`/`external` are flagged. |
| `test_inv004_missing_payload_schema_for_data_edge` + `..._event_edge_also_requires_payload` | INV-004 covers both `data` and `event` kinds. |
| `test_inv005_low_confidence_node_without_question` + `..._with_question_passes` | INV-005 only fires when there is no question recorded. |
| `test_inv006_cyclic_data_dependency` | DFS cycle detection fires only on `kind: data` cycles. |
| `test_inv007_dangling_assumption` | Load-bearing assumption decided by agent without a question is flagged. |
| `test_valid_contract_passes_all_invariants` | Golden-path contract produces zero violations. |
| `test_inv_check_registry_covers_inv001_through_inv007` | Catches a regression where someone forgets to add a new INV-008 to the registry. |
| `test_violations_ranked_by_severity` | The five-tier ranking is preserved across the public `rank_violations()` API. |
| `test_emit_top_questions_caps_at_five` | The 5-question cap is enforced. |
| `test_uvdc_score_calculation_*` (×3) | UVDC math: all-user, partial, and the vacuous-1.0 case. |
| `test_verify_contract_no_llm_clean_contract_passes` + `..._dirty_contract_fails` | `use_llm=False` mode runs cleanly without a network. |

These tests do not need a network and run in milliseconds — they are
the cheap regression net for the deterministic core.

## `tests/test_phase1_loop.py` (4 integration tests)

These run a *simulated* full loop: a fixture builds an initial
contract, the test calls `verify_contract` with a monkeypatched
`_call_llm_passes` that returns synthetic violations + confidence
updates, applies decisions, and re-runs.

### `test_three_pass_confidence_improvement(looped_session, caplog)`

The headliner. Runs **exactly 3 fixed iterations**:

```
for i in range(3):
    output = verify_contract(contract, pass_number=i+1)
    record per-node confidences after pass i
    apply Decisions for every question returned
    contract = refine_contract(contract, decisions)
```

After the third pass it constructs a `ConfidenceReport`:

```python
{
    "session_id": "...",
    "total_passes": 3,
    "summary": {
        "nodes_improved":  4,
        "nodes_unchanged": 1,
        "nodes_degraded":  0,
        "average_delta":   0.15
    },
    "nodes": [ /* per-node deltas + critic reasoning per pass */ ]
}
```

Asserts:
- `summary.nodes_degraded == 0` (no node should regress).
- `summary.nodes_improved >= 1`.
- The structured `compiler.confidence_report` log entry is emitted
  with the same shape.
- Per-pass `compiler.confidence_snapshot` log lines exist (caplog
  asserts presence keyed on `pass_number`).

### `test_answered_questions_dont_reappear(looped_session, monkeypatch)`

Drives the same loop but, on pass 2, replays pass 1's exact
violations through the LLM monkeypatch. Asserts that none of those
already-answered questions show up in the `questions` list returned
by pass 2 — i.e., the `_already_answered` filter actually fires for
LLM-emitted violations as well as deterministic ones. This is the
test that would have failed before commit `4dbac4f`.

### `test_verification_log_grows_per_verify`

Sanity check: each Verify pass appends a `VerificationRun` to
`contract.verification_log[]` and never mutates the previous entries.

### `test_confidence_report_flags_degraded_nodes`

Constructs a synthetic report where one node's confidence decreases.
Asserts `summary.nodes_degraded == 1` and that a `WARN`-level log
entry (`compiler.confidence_degraded`) is emitted with the offending
`node_id` and `reasoning`.

## `tests/test_api.py` (8 new tests, 15 total)

Run via FastAPI's `TestClient` against an in-memory SQLite. The new
M3-specific tests:

| Test | Asserts |
| --- | --- |
| `test_verify_returns_violations_for_invalid_contract` | Verify on a contract with INV-001..006 problems returns `verdict=fail`, non-empty `violations`, and ≤ 5 `questions`. |
| `test_verify_returns_empty_violations_for_valid_contract` | Verify on a clean fixture returns `verdict=pass`, empty `violations`. |
| `test_submit_answers_records_decisions` | `POST /answers` round-trips `Decision` objects through the contract. |
| `test_refine_updates_contract_with_answers` | `POST /architect/refine` produces a new contract version where the answered question is now `decided_by: user`. |
| `test_verification_log_persisted` | `verification_log[]` is populated and survives a `GET /sessions/{id}` round-trip. |
| `test_verify_unknown_session_404` | Unknown session id ⇒ 404. |
| `test_refine_with_empty_body_uses_existing_decisions` | Body-optional contract: `RefineRequest()` is valid; the API uses `contract.decisions[]`. |
| `test_refine_unknown_session_404` | Unknown session id ⇒ 404. |

All use a monkeypatched `compiler._call_llm_passes` and
`architect.refine_contract` so no network is required.

## Acceptance criteria mapping

The acceptance criteria from the M3 spec map to these tests as
follows:

| Spec criterion | Where it's locked in |
| --- | --- |
| Run exactly 3 fixed iterations | `test_three_pass_confidence_improvement` |
| Confidence report logged with deltas + summary | Same test (asserts `compiler.confidence_report` log + structure) |
| Nodes improved ≥ 1 / nodes degraded == 0 | Same test |
| Question cap = 5 | `test_emit_top_questions_caps_at_five` + frontend live A4 |
| Already-answered suppression | `test_answered_questions_dont_reappear` + live A8 |
| API has Verify / Answers / Refine routes | `test_api.py` (8 tests) |
| Verify persists a verification run | `test_verification_log_persisted` |
| Frontend shows graph with ≥ 4 nodes | live A3 |
| Frontend shows yellow ring + NEW badge after refine | live A7 |
| Iteration counter reaches 3/3 | live A9 |
| Backend logs 3× verify_complete + 3× refine.complete | live A10 |

## Live E2E test plan

`test-plan.md` (working doc, not committed) describes 10 assertions
for the live recording. They are all reflected in the headers of
this document and the PR description. The recording, the per-iteration
metric table (Coverage 12% → 28% → 35%), and the confirmatory backend
log excerpt are attached to the test report message on the Devin
session, and a condensed version was posted as a PR comment.
