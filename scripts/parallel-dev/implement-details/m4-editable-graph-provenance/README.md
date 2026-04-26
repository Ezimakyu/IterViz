# M4 — Editable Graph + Decision Provenance — Implementation Details

This directory documents how Milestone **M4** was actually built. It is the
working reference for the new node-update API, the provenance-aware
Compiler pipeline, the inline-edit UI in the graph popup, and the tests +
end-to-end run that lock M4's behavior in place.

> Source PR:
> [#10](https://github.com/Ezimakyu/IterViz/pull/10) — merged on top of M3
> (PR #8) so the Phase 1 verify → answers → refine loop, the Architect
> agent, and contract persistence from M2/M3 remain the canonical versions.

## What landed

| Path | Purpose |
| --- | --- |
| `backend/app/schemas.py` *(extension)* | `NodeUpdateRequest` (with `extra="forbid"`) and `NodeUpdateResponse` carrying `fields_updated` + `provenance_set` |
| `backend/app/contract.py` *(extension)* | `update_node()` — patches editable fields, flips `decided_by` to `user`, and emits `contract.node_updated` |
| `backend/app/api.py` *(extension)* | `PATCH /api/v1/sessions/{session_id}/nodes/{node_id}` wired through to `contract.update_node`, with 404s for unknown sessions/nodes |
| `backend/app/compiler.py` *(extension)* | Provenance-aware INV-007 + `_provenance_violations`: nodes/edges with `decided_by: user` are skipped entirely. New `compiler.provenance_check_start`, `compiler.uvdc_breakdown`, and `compiler.node_provenance_detail` log lines |
| `backend/tests/test_contract.py` *(extension)* | 8 new tests for `update_node`: fields, no-op, structural rejection, assumption replacement, missing session/node |
| `backend/tests/test_api.py` *(extension)* | 4 new tests for the PATCH route — happy path, 404s, structural-field rejection (422), provenance round-trip |
| `backend/tests/test_compiler.py` *(extension)* | 8 new tests covering provenance skip, INV-007 exemption, UVDC monotonicity under user edits, and the `DEBUG=1` logging regression test |
| `frontend/src/api/client.ts` *(extension)* | `updateNode(sessionId, nodeId, NodeUpdateRequest)` typed wrapper |
| `frontend/src/state/contract.ts` *(extension)* | `userEditedFields` map, `provenanceView` flag, `updateNodeField` thunk that PATCHes the backend and treats the prior contract as the diff baseline |
| `frontend/src/components/NodeDetailsPopup.tsx` *(rewrite)* | Click-to-edit description and responsibilities, blur-to-save, `Cmd/Ctrl+Enter` to commit, `Esc` to cancel, blue left border on edited fields, `USER-EDITED` header badge |
| `frontend/src/components/NodeCard.tsx` *(extension)* | Blue ring + `USER` badge when the node is user-edited, opacity-dim for non-user-edited cards while provenance view is on |
| `frontend/src/components/Graph.tsx` *(extension)* | Top-left `Provenance view on/off` toggle and legend (`User-edited (n) / Other`) |

## File guide in this directory

| File | What it covers |
| --- | --- |
| `01-overview.md` | High-level picture: where M4 fits, the flow, design choices |
| `02-schemas-and-contract.md` | `NodeUpdateRequest`/`Response`, `update_node` semantics, structured logs |
| `03-api.md` | The PATCH route, request/response shape, error mapping |
| `04-compiler-provenance.md` | INV-007 exemption, `_provenance_violations` skip, `compute_uvdc` behavior under user edits, the three new log lines |
| `05-frontend.md` | API client, store additions, `NodeDetailsPopup` editing UX, `NodeCard` highlights, provenance view toggle in `Graph` |
| `06-tests-and-acceptance.md` | Test layout, fixture strategy, end-to-end recording, acceptance-criteria mapping |
| `07-bugs-found-and-fixed.md` | The `LogRecord.name` collision caught during testing, plus the regression test that now guards it |

## Acceptance summary

- `pytest backend/tests/ -v` → **90 passed** (M1 + M2 + M3 + 20 new M4 tests).
- Frontend `tsc --noEmit` + `npm run lint` + `npm run build` all green.
- Live end-to-end run (Anthropic Claude `claude-opus-4-5`, backend in
  `DEBUG=1`):
  - Architect generates a contract → baseline `Verify` → coverage `16%`
    (`34E / 1W`, 5 questions, all about edges).
  - Inline edit of a single node's description: popup gains the
    `USER-EDITED` badge, the description gets a blue left border, the
    node card on the graph gets a blue ring + `USER` badge, footer
    flips to `decided by · user`.
  - Re-`Verify`: coverage rises monotonically from `16% → 20%` (one
    `agent` node became `user` so UVDC went from `4/25` to `5/25`).
    No question on the panel references the edited node.
  - Backend logs include `contract.node_updated` (with
    `fields_updated:["description"]` and
    `provenance_changes:{"description":"user"}`),
    `compiler.provenance_check_start` (with `user_decided_nodes 0 → 1`),
    and `compiler.uvdc_breakdown`.
  - Provenance view toggle: legend reads `User-edited (1) / Other`,
    only the edited node remains at full opacity, all others dim;
    toggling it off restores the normal graph.
- One bug was found and fixed during the end-to-end run: `log.debug(
  "compiler.node_provenance_detail", extra={"name": ...})` collided with
  the reserved `LogRecord.name` and 500'd the Verify route under
  `DEBUG=1`. The key was renamed to `node_name`, and a regression test
  (`test_verify_contract_works_at_debug_log_level`) now runs
  `verify_contract` with logging at `DEBUG` to make sure the bug
  cannot recur. See `07-bugs-found-and-fixed.md`.
