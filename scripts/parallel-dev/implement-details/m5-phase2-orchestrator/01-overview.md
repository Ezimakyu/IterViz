# 01 — Overview

## Where M5 sits in the system

M5 is the milestone that turns a verified contract into actual code on
disk. M3 closed the Architect ↔ Compiler ↔ Q&A loop (the contract gets
"green"); M4 made the contract editable and traceable; M5 takes the
green contract, freezes it, and either drives an internal LLM
subagent through every node or hands the assignments out to external
agents over a REST + WebSocket protocol.

```
                       (M3) Verify → answers → refine ↺
                                  │
                                  ▼
                       UVDC=100% / 0 errors
                                  │ click Freeze
                                  ▼
        POST /api/v1/sessions/{id}/freeze
                                  │
                                  ▼
              orchestrator.freeze_contract(session_id)        (M5 new)
              ┌──────────────────────────────────────────┐
              │ status → verified, meta.frozen_hash =    │
              │ sha256(canonical contract), frozen_at    │
              └──────────────┬───────────────────────────┘
                             │  click Implement (internal | external)
                             ▼
        POST /api/v1/sessions/{id}/implement
                             │
                             ▼
              orchestrator.create_assignments(session_id)     (M5 new)
              ┌──────────────────────────────────────────┐
              │ idempotent — returns existing set if any │
              │ one assignment per node, with neighbor   │
              │ interfaces snapshotted into payload      │
              └──────────────┬───────────────────────────┘
                             │
                  internal ──┴── external
                     │            │
                     ▼            ▼
        run_implementation_internal     external agents poll
        sequentially walks assignments  GET /sessions/{id}/available_assignments
        per node:                       then claim / progress / submit via REST
          claim → broadcast(node_      ┌──────────────────────────────────┐
              status_changed=in_       │ Each REST mutation triggers      │
              progress)                │ ws.broadcast_*(...) so the UI    │
          → _run_subagent (LLM /        │ updates without polling.         │
              mock fallback)            └──────────────────────────────────┘
          → write files, complete
              assignment, broadcast
              implemented
                             │
                             ▼
              orchestrator.run_integration_pass(session)      (M5 new)
              ┌──────────────────────────────────────────┐
              │ verify edge.payload_schema vs producer's │
              │ exports; collect IntegrationMismatch[]   │
              └──────────────┬───────────────────────────┘
                             │
                             ▼
              broadcast(implementation_complete{success, mismatches})
              status → complete; write contract.json into output dir
                             │ user clicks Download
                             ▼
        GET /api/v1/sessions/{id}/generated  → zip
        ┌──────────────────────────────────────────────────┐
        │ get_generated_files_dir() resolves and verifies  │
        │ candidate path stays inside the generated root   │
        │ before zipping. BackgroundTask deletes the temp  │
        │ zip after the response is sent.                  │
        └──────────────────────────────────────────────────┘
```

## End-to-end sequence

Each numbered step matches a user-visible event in the recorded E2E run.

1. **Freeze gate.** With UVDC < 100% or any errors, the **Freeze** button
   is disabled and its tooltip reads *"Reach 100% coverage with 0
   errors before freezing."* The header subtitle still reads
   `M3 · Architect ↔ Compiler ↔ Q&A loop`.
2. **Freeze.** Click **Freeze**. `freeze` thunk hits
   `POST /api/v1/sessions/{id}/freeze`; the orchestrator computes
   `sha256(canonical_json(contract_minus_meta))`, writes
   `meta.frozen_hash` / `meta.frozen_at` / `meta.status="verified"`, and
   responds with the updated contract. The header switches to
   `M5 · Phase 2 ready`, the Freeze button locks to "Frozen", and the
   two **Implement** buttons (internal / external) light up.
3. **Implement (internal).** Click **Implement (internal)**. The store
   first calls `wsConnect(sessionId)` so the WS is open before the HTTP
   call returns, then `POST /api/v1/sessions/{id}/implement` with
   `mode=internal`. The backend creates one assignment per node
   (idempotent), schedules
   `orchestrator.run_implementation_internal(session_id)` as a
   `BackgroundTask`, and returns `{ job_id, mode, assignments_created }`.
4. **Live updates.** As the orchestrator walks each assignment it
   broadcasts `node_status_changed{status=in_progress}` (yellow ring),
   then `node_status_changed{status=implemented}` after the subagent
   completes. The frontend's WS store applies each event to
   `nodeStatuses` / `nodeAgents`, and `NodeCard` re-renders with the
   matching ring color.
5. **Integration pass.** After every assignment finishes the orchestrator
   runs `run_integration_pass`, sets `meta.status="complete"`, dumps
   `contract.json` into the session's output directory, and broadcasts
   `implementation_complete`. The frontend flips
   `implementationComplete=true`, the AgentPanel shows
   *"Implementation complete"*, and the **Download** button appears.
6. **Download.** The Download button is a plain anchor to
   `GET /api/v1/sessions/{id}/generated`. The handler streams a zip of
   the entire output directory (one folder per node + `contract.json`)
   and schedules the temp file for deletion.

## Modes: internal vs external

| Aspect | internal | external |
| --- | --- | --- |
| Who runs the subagent | `_run_subagent` in the backend (calls `llm.call_structured`, falls back to a mock structured response if the LLM fails) | An out-of-process script (e.g. `scripts/external_agent_example.py`, Devin, Cursor) |
| Who claims the assignment | `run_implementation_internal` claims via `assignments.claim_assignment(..., internal_agent_id)` before each subagent run | The agent calls `POST .../nodes/{id}/claim` |
| What happens on `/implement` | The route schedules `run_implementation_internal` as a `BackgroundTask` and returns immediately | The route only creates assignments — external agents must already be polling `/agents/{id}/available_assignments` |
| Result delivery | Files written under `backend/generated/{session_id}/{node_id}/` by `_run_subagent` itself | The agent calls `POST .../nodes/{id}/implementation` with the file paths and `actual_interface` |
| Status → `complete` | Triggered automatically when the loop finishes | Triggered by the last `submit_implementation` (the route checks if all assignments are completed and runs the integration pass) |

## Design choices

### "Implement every node, not just leaves"

`identify_leaf_nodes` is exposed and tested, but `create_assignments`
intentionally fans out to **every** node, not just leaves. This is so
the demo can show all six rings transitioning — implementing only leaves
would leave non-leaf nodes stuck on "drafted" forever. The
`identify_leaf_nodes` helper is still in the public API for downstream
tooling that wants leaf-only execution.

### Idempotent freeze and idempotent assignments

Both `freeze_contract` and `create_assignments` are idempotent:

- `freeze_contract` rehashes and overwrites `frozen_hash` (it computes
  the same hash for the same contract, so this is a no-op for repeat
  calls).
- `create_assignments` returns the existing assignment set if one is
  already present for the session, instead of creating duplicates.
  Without this, repeated `/implement` clicks would each fan out a
  fresh set of assignments, but `_find_by_node_locked` only ever finds
  one (the first match), so duplicates would be unreachable but still
  visible in `get_available_assignments`. See
  `08-bugs-found-and-fixed.md` § "Duplicate assignments on repeated
  /implement".

### LLM fallback to mock structured response

Every `_run_subagent` call is wrapped in a try/except. If
`llm.call_structured` raises (no API key, rate limit, network failure,
parse failure), the subagent falls back to a deterministic mock that
emits a small Python skeleton with the node's name and
responsibilities. This was a hard requirement for the demo: the
recorded E2E test ran with an empty `ANTHROPIC_API_KEY` and still
produced runnable output, just stubbier than the real LLM would.

### Integration pass scope

`run_integration_pass` only checks whether each edge with a declared
`payload_schema` has a non-empty `actual_interface.exports` from its
source node. It is intentionally weak (string-name match, no type
comparison) so the demo can complete green; richer checks land in M6.

### Flat status taxonomy

`NodeStatus` is `drafted | in_progress | implemented | failed`. This
maps 1:1 to ring colors, so the frontend doesn't need a derived state
machine. Likewise `AssignmentStatus` is
`pending | in_progress | completed | failed` — every state transition
is observable from a single value.

## What carried over from earlier milestones

- M3's `Architect` agent + `Compiler` are unchanged; M5 only consumes
  the contract once UVDC is 100%.
- M4's `update_node` route, `userEditedFields` provenance, and
  `provenanceView` toggle all still work after Freeze. We add the
  M5-specific status ring on top of the M4 user-edit ring on
  `NodeCard` (stacked, distinct colors).
- M3's `claude-opus-4-5` defaults, `ensure_api_key()`, and the 32K
  `max_tokens` / 900s timeout all apply to M5 subagent calls.
