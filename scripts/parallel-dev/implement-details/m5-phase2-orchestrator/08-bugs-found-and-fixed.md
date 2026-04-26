# 08 — Bugs found and fixed

This document is a flat enumeration of every bug caught while building
M5, in the order they were discovered. The first three were found
during the initial implementation pass against the M5 spec. The next
three came from the first Devin Review pass on PR #11. The last
three came from the second Devin Review pass after the merge from
`main`. All nine are fixed in the merged branch.

## Build-pass bugs

### B1 — `run_implementation_internal` never claimed assignments

- **Symptom.** Every assignment stayed `PENDING` forever in internal
  mode; `get_available_assignments` kept returning already-implemented
  nodes. The recorded UI test would have shown nodes flip yellow then
  fall back to drafted on a refresh.
- **Cause.** The original loop went `get_assignments_for_session →
  _run_subagent → complete_assignment`, with no `claim_assignment` in
  between. `complete_assignment` enforces `assigned_to == agent_id`
  (so external agents can't overwrite each other's work), so internal
  completions silently no-op'd and returned `None`.
- **Fix.** Added an explicit
  `assignments_svc.claim_assignment(session_id, node.id, "internal")`
  before each subagent call. If the claim returns `None` (already
  claimed by another agent), the loop skips that assignment and
  continues. See `orchestrator.py:299-309`.
- **Locked in by.** `test_internal_run_marks_assignments_completed`
  asserts every assignment ends `COMPLETED`.

### B2 — Path traversal via LLM-generated filenames

- **Symptom.** A malicious or hallucinating LLM that returned
  `filename: "../../etc/evil.py"` would write files outside
  `backend/generated/<session>/<node>/`.
- **Cause.** `output_dir / raw_filename` was used directly. `Path` is
  permissive about parent components.
- **Fix.** `safe_name = Path(str(raw_name)).name or f"file_{i}.py"`
  strips every directory component. See `orchestrator.py:336`.
- **Locked in by.** `test_internal_run_marks_assignments_completed`
  feeds a filename of `"../../etc/evil.py"` and asserts every
  resulting file path resolves under the test's `tmp_path` generated
  root.

### B3 — TOCTOU race in assignment claim/complete/release

- **Symptom.** Two concurrent claimers of the same node could both
  observe `PENDING`, both transition the assignment to `IN_PROGRESS`,
  and both later try to complete it.
- **Cause.** The pattern was `(lock → look up → release lock) → (lock
  → mutate → release lock)`. The window between the two critical
  sections was the race.
- **Fix.** Introduced `_find_by_node_locked(session_id, node_id)`, a
  helper that does the lookup but **assumes the caller already holds
  `_lock`**. Every mutating function (`claim_assignment`,
  `complete_assignment`, `release_assignment`, `fail_assignment`) now
  does its lookup + state check + mutation in a single `with _lock:`
  block via this helper. See `assignments.py:110-167`.
- **Locked in by.** `test_double_claim_returns_none`.

## First Devin Review pass

### B4 — Temp zip file leak in `download_generated`

- **Symptom.** Every download leaked a `.zip` into the OS temp
  directory permanently.
- **Cause.** The handler created a `NamedTemporaryFile(delete=False,
  suffix=".zip")` and passed it to `FileResponse` with no cleanup
  callback. `FileResponse` doesn't unlink files it streams.
- **Fix.** `BackgroundTask(tmp_path.unlink, missing_ok=True)` is
  passed to `FileResponse` so the zip is unlinked after the response
  is fully sent. See `api.py:574-580`.

### B5 — WebSocket disconnect leak

- **Symptom.** Any non-`WebSocketDisconnect` exception during the
  WebSocket loop (e.g. `RuntimeError` from a slow client, network
  reset) left the connection registered in
  `ConnectionManager._connections` forever, eventually consuming the
  per-session list and slowing every broadcast.
- **Cause.** Cleanup was inside an `except WebSocketDisconnect` block,
  not a `finally`.
- **Fix.** Moved `manager.disconnect(session_id, websocket)` into a
  `finally` block. See `main.py:90-102`.

### B6 — `claim_node` left state inconsistent on unknown node id

- **Symptom.** `POST /sessions/{id}/nodes/{unknown_id}/claim` would
  go through `claim_assignment` (succeed, mark assignment
  `IN_PROGRESS`), then bind the agent to that assignment, *then* fail
  to find the node in the contract — at which point the agent was
  marked active and an assignment was claimed but no `node_claimed`
  broadcast or contract update happened.
- **Cause.** Node-existence check happened *after* state mutations.
- **Fix.** Look up `target_node = next((n for n in contract.nodes if
  n.id == node_id), None)` *before* touching `assignments_svc` or
  `agents_svc`; return `success=False` immediately if the node is
  missing. Same fix applied symmetrically in
  `submit_implementation`. See `api.py:317-323` and `api.py:403-409`.

## Second Devin Review pass (post-merge)

### B7 — Path traversal in `download_generated` (CRITICAL)

- **Symptom.** A request to
  `GET /api/v1/sessions/%2E%2E/generated` would zip
  `backend/generated/..` (i.e. the entire `backend/` tree) and stream
  it to the caller, leaking source code, the SQLite database, and any
  keys checked into the repo.
- **Cause.** `get_generated_files_dir(session_id)` did
  `output_dir = get_generated_dir() / session_id` with no
  normalization or containment check. `..` (and absolute paths like
  `/etc`) escape.
- **Fix.** `.resolve()` both the root and the candidate, then verify
  `candidate != root` and `root in candidate.parents` before
  returning. See `orchestrator.py:596-611`.
- **Locked in by.** `test_get_generated_files_dir_rejects_traversal`
  with cases `..`, `../sibling`, `../../etc`, `/etc`.

### B8 — Duplicate assignment creation on repeated `/implement`

- **Symptom.** Clicking **Implement** twice (or starting external mode
  twice) fan-out a fresh set of assignments each time. The duplicates
  were unreachable through `claim_assignment` /
  `complete_assignment` (because `_find_by_node_locked` returns the
  first match) but they showed up in `get_available_assignments`,
  which external agents poll, so external agents would see the same
  node twice and waste claim attempts on assignments nobody could
  complete.
- **Cause.** `orchestrator.create_assignments` had no idempotency
  guard. The route on `api.py:535` calls it unconditionally.
- **Fix.** Early-return the existing set if
  `get_assignments_for_session(session_id)` is non-empty. See
  `orchestrator.py:225-231`.
- **Why "return existing" rather than "transition status to
  IMPLEMENTING for both modes":** external mode keeps the contract in
  `verified` while external agents poll and claim. Flipping to
  `IMPLEMENTING` would prematurely block new claims out of
  `get_available_assignments` (which today doesn't filter by status,
  but the future intent is to fence claims when the run is "done").
- **Locked in by.** `test_create_assignments_is_idempotent`.

### B9 — WebSocket reconnection race when switching sessions

- **Symptom.** When the user navigates from session A to session B,
  the new WebSocket opens correctly, but ~1.5s later the store
  silently reverts to session A.
- **Cause.** In `frontend/src/state/websocket.ts:90-137`, the original
  flow was:
  1. `existing.close()` (the old socket starts closing).
  2. `open()` (start opening the new socket).
  3. New socket's `onopen` fires → `set({ socket, sessionId: B, ... })`.

  But the old socket's `onclose` fires asynchronously *between* steps
  1 and 3. At that moment `get().sessionId` is still `"A"`, so the
  close handler decides "I'm still on A, schedule a reconnect in
  1.5s". 1.5s later it overwrites the just-set `sessionId="B"` with
  a fresh socket on session A.
- **Fix.** Before closing the old socket, both:
  1. Detach its `onclose` (`existing.onclose = null`) so the stale
     reconnect handler can never fire.
  2. Eagerly write the new `sessionId` and reset
     `reconnectAttempts` into the store, so even if the close
     handler somehow fired, `get().sessionId !== sessionId` would
     short-circuit it.

  See `websocket.ts:90-101`.
- **Why it's a real bug, not a style fix.** The race is short
  (typically a few hundred ms), but it's deterministic when network
  latency to the WS endpoint is non-trivial. The session reversion is
  silent — there's no error toast, no console log, the user just
  starts seeing updates for the wrong session. This is the kind of
  bug that surfaces as "WebSocket sometimes shows stale data" in
  production and burns several hours of debugging when it does.
