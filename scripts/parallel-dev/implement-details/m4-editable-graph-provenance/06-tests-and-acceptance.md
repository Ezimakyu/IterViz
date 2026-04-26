# 06 — Tests and acceptance

## Suite layout

| File | New tests added in M4 | What they cover |
| --- | --- | --- |
| `backend/tests/test_contract.py` | 7 (in a `class TestUpdateNode`) | `update_node` semantics: per-field edits, no-op, structural-field rejection (via API layer), assumption replacement, missing session/node, multi-field updates |
| `backend/tests/test_api.py` | 5 (in a `class TestPatchNode` plus 1 follow-up) | PATCH route happy path, unknown node/session 404s, structural-field 422, multi-field round-trip, UVDC monotonicity through HTTP |
| `backend/tests/test_compiler.py` | 8 (in `class TestProvenanceAware…` blocks) | User-decided node skips provenance violations, agent-decided still triggers, INV-007 exemption, UVDC counts user/prompt/mixed, the DEBUG-level regression test, "no questions for user-decided load-bearing assumption" |

Total **20 new tests**. With M0/M1/M2/M3 the full backend suite is
**90 tests**, all green.

```
$ cd backend && pytest tests/ -v
=========================== test session starts ===========================
...
tests/test_compiler.py::TestProvenanceAwareVerification::test_user_decided_node_skips_provenance_violations PASSED
tests/test_compiler.py::TestProvenanceAwareVerification::test_agent_decided_node_still_generates_provenance_violation PASSED
tests/test_compiler.py::TestProvenanceAwareVerification::test_user_decided_node_silences_inv007_for_agent_assumptions PASSED
tests/test_compiler.py::TestProvenanceAwareVerification::test_uvdc_user_decided_counts_as_covered PASSED
tests/test_compiler.py::TestProvenanceAwareVerification::test_uvdc_increases_when_node_flips_to_user PASSED
tests/test_compiler.py::TestProvenanceAwareVerification::test_uvdc_mixed_user_prompt_agent PASSED
tests/test_compiler.py::TestProvenanceAwareVerification::test_verify_contract_works_at_debug_log_level PASSED
tests/test_compiler.py::TestProvenanceAwareVerification::test_no_questions_for_user_decided_load_bearing_assumption PASSED
tests/test_contract.py::TestUpdateNode::test_description_edit_sets_user_provenance PASSED
tests/test_contract.py::TestUpdateNode::test_unchanged_fields_keep_their_values PASSED
tests/test_contract.py::TestUpdateNode::test_assumption_replacement_marks_each_user_decided PASSED
tests/test_contract.py::TestUpdateNode::test_invalid_node_id_raises_value_error PASSED
tests/test_contract.py::TestUpdateNode::test_invalid_session_id_raises_session_not_found PASSED
tests/test_contract.py::TestUpdateNode::test_no_op_update_does_not_flip_provenance PASSED
tests/test_contract.py::TestUpdateNode::test_multi_field_update_reports_all_changed PASSED
tests/test_api.py::TestPatchNode::test_patch_node_updates_field_and_provenance PASSED
tests/test_api.py::TestPatchNode::test_patch_node_unknown_node_returns_404 PASSED
tests/test_api.py::TestPatchNode::test_patch_node_unknown_session_returns_404 PASSED
tests/test_api.py::TestPatchNode::test_patch_node_rejects_structural_fields PASSED
tests/test_api.py::TestPatchNode::test_patch_node_multi_field_update PASSED
tests/test_api.py::TestPatchNode::test_verify_after_user_edit_does_not_decrease_uvdc PASSED
============================ 90 passed in ...s ============================
```

## Fixture strategy

All M4 backend tests reuse the existing `temp_db` and `client`
fixtures from M0/M2. There is no new harness:

- `temp_db` (in `conftest.py`) mounts an isolated SQLite database in
  a temp directory and rebinds `contract.STORAGE` to it for the
  duration of the test.
- `client` (in `test_api.py`) is the `TestClient(app)` over the
  FastAPI factory.
- `_node` / `_edge` / `_contract` helpers in `test_compiler.py` are
  small literal builders that skip the architect and let the test
  pin every `decided_by` value explicitly.

This keeps the M4 tests honest: they don't depend on any LLM call,
they don't depend on Architect output, they only care about the
provenance state on the contract that goes into `verify_contract`
and the contract that comes out of `update_node`.

## Highlight tests

### `test_uvdc_increases_when_node_flips_to_user`

Constructs a contract with two `decided_by: agent` nodes, runs
`compute_uvdc` to capture the baseline, flips one node to
`decided_by: user`, runs `compute_uvdc` again, asserts the second
call returns a strictly greater value. This is the unit-level proof
of the M4 monotonicity guarantee.

### `test_user_decided_node_silences_inv007_for_agent_assumptions`

Builds a node with `decided_by: user` whose `assumptions[0]` still
carries `decided_by: agent` and `load_bearing: true`. Calls
`run_invariant_checks(contract)` and asserts INV-007 produces zero
violations for that node. The same scenario with the node set to
`decided_by: agent` returns a violation, so the test pins both sides
of the conditional.

### `test_verify_contract_works_at_debug_log_level`

The bug-fix regression test. Forces `compiler.log` to `DEBUG`, calls
`verify_contract(contract, use_llm=False)`, and asserts the result
is non-`None`. The original buggy code raised
`KeyError: "Attempt to overwrite 'name' in LogRecord"` here. With
the rename in `04-compiler-provenance.md`, this passes cleanly.
See `07-bugs-found-and-fixed.md` for the full story.

### `test_patch_node_rejects_structural_fields`

```python
def test_patch_node_rejects_structural_fields(self, client):
    sid = _bootstrap_session(client)
    nid = _first_node_id(client, sid)
    resp = client.patch(
        f"/api/v1/sessions/{sid}/nodes/{nid}",
        json={"name": "Renamed"},
    )
    assert resp.status_code == 422
    assert "name" in resp.text
```

The `extra="forbid"` config on `NodeUpdateRequest` does the work; the
test is a guard against someone accidentally relaxing it later.

### `test_verify_after_user_edit_does_not_decrease_uvdc`

The integration-level companion to
`test_uvdc_increases_when_node_flips_to_user`: create a session,
call `/compiler/verify` to capture baseline UVDC, PATCH a node's
description, call `/compiler/verify` again, assert the new UVDC is
`>= baseline`. The pure-unit version pins `>`, this one pins `>=`
because the baseline scenario uses a synthetic contract where
nothing changes structurally on PATCH.

## End-to-end acceptance run

A live recording was captured during testing — see
`.devin/test-report-m4.md` (in the M4 PR) and PR #10's main test-run
comment. The run executed the canonical M4 flow against a real
Anthropic Claude `claude-opus-4-5` Architect:

1. **Generate contract** from prompt
   *"Build a Slack bot that summarizes unread DMs daily."*
2. **Verify (baseline)** → coverage **16%**, `34E / 1W`, 5 questions
   (all about edges; UVDC components `4/25`).
3. **Inline edit** of a single node's description in the popup. The
   blue left border on the description appears, the popup header
   gains a `USER-EDITED` badge, and the `NodeCard` on the graph
   gains a blue ring + `USER` badge. Footer flips to
   `decided by · user`.
4. **Verify (re-run)** → coverage **20%**, no question on the panel
   references the edited node. `compiler.uvdc_breakdown` log line
   reads `total=25 user_or_prompt=5 uvdc=0.20`.
5. **Provenance view toggle on**: legend `User-edited (1) / Other`,
   only the edited node remains at full opacity, all other cards
   visibly dim. Toggle off: opacity restored.

| Acceptance criterion | Result |
| --- | --- |
| `PATCH /sessions/{id}/nodes/{node_id}` returns `fields_updated:["description"]` and `provenance_set:{"description":"user"}` | PASSED |
| Edited node card has blue ring + `USER` badge | PASSED |
| Popup shows `USER-EDITED` header badge and blue left border on description | PASSED |
| Footer says `decided by · user` | PASSED |
| Coverage % strictly increased after edit (16% → 20%) | PASSED |
| No question on the panel references the edited node post-edit | PASSED |
| Backend logs include `contract.node_updated` | PASSED |
| Backend logs include `compiler.provenance_check_start` | PASSED |
| Backend logs include `compiler.uvdc_breakdown` | PASSED |
| Provenance view toggle dims non-user-edited nodes; legend appears | PASSED |
| All 90 backend tests pass | PASSED |
| `tsc --noEmit`, `eslint`, `npm run build` all green | PASSED |

The full report (with screenshots and the recording link) lives at
`.devin/test-report-m4.md` on the M4 PR.

## What is **not** covered by automated tests

- **Edge-level user provenance.** `_provenance_violations` and
  INV-007 already short-circuit when `edge.decided_by == "user"`,
  but there is no UI path yet that flips an edge to `user`. The
  unit tests cover the compiler behavior; the wire is in place for
  M5 to expose it.
- **Assumption-list editing through the popup.** The schema and
  service support it, but the popup currently only exposes
  description and responsibilities. A new test under
  `TestUpdateNode` covers the service-level call directly.
- **Provenance view toggle interaction with selected node.** The
  toggle is purely visual; there is no automated regression that
  asserts the dim class is applied. The end-to-end recording is
  the documented evidence.
