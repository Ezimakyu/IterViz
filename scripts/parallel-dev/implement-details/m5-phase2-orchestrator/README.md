# M5 — Phase 2 Orchestrator — Implementation Details

This directory documents how Milestone **M5** was actually built. It is the
working reference for the freeze + leaf-detection + subagent-dispatch
backend, the agent-coordination REST/WebSocket surface, the live-wired
frontend (Freeze → Implement → Download flow with status rings and
`AgentPanel`), the external-agent example script, and the tests that lock
the orchestrator's invariants in place.

> Source PR:
> [#11](https://github.com/Ezimakyu/IterViz/pull/11) — built on top of M3
> (PR #8) and M4 (PR #10). M3 owns the Architect/Compiler/Q&A loop; M4
> owns editable nodes + provenance; M5 takes a verified contract and
> drives it to implemented code.

## What landed

| Path | Purpose |
| --- | --- |
| `backend/app/agents.py` | In-memory external-agent registry (register, heartbeat, status, assignment binding, stale-agent detection) |
| `backend/app/assignments.py` | Per-node work units with PENDING → IN_PROGRESS → COMPLETED/FAILED lifecycle, lock-protected `_find_by_node_locked` to defeat double-claim races |
| `backend/app/orchestrator.py` | `freeze_contract`, `identify_leaf_nodes`, `get_neighbor_interfaces`, `create_assignments` (idempotent), `run_implementation_internal` (sequential subagent loop with mock fallback), `run_integration_pass`, `get_generated_files_dir` (path-traversal hardened) |
| `backend/app/ws.py` | `ConnectionManager` + per-message `broadcast_*` helpers (`node_status_changed`, `node_claimed`, `node_progress`, `agent_connected`, `implementation_complete`, `integration_result`, `error`) |
| `backend/app/api.py` *(extension)* | 11 new routes — `POST/GET /agents`, `GET /sessions/{id}/assignments`, `POST .../nodes/{id}/{claim,status,implementation,release}`, `POST .../freeze`, `POST .../implement`, `GET .../generated` |
| `backend/app/main.py` *(extension)* | `/api/v1/sessions/{id}/stream` WebSocket endpoint with `finally`-block disconnect cleanup |
| `backend/app/schemas.py` *(extension)* | M5 enums (`AgentType`, `AgentStatus`, `AssignmentStatus`, `ImplementMode`, `NodeStatus`, expanded `ContractStatus`), models (`Agent`, `NeighborInterface`, `AssignmentPayload`, `AssignmentResult`, `Assignment`, `Implementation`, `ActualInterface`, `IntegrationMismatch`), API DTOs, and seven `WS*` message types |
| `backend/app/prompts/{subagent,integrator}.md` | Prompt files used by the internal subagent + integrator passes (loaded via `llm.load_prompt`) |
| `backend/tests/test_agents.py` | 7 unit tests covering register, heartbeat, `DISCONNECT_THRESHOLD`, status, assignment binding |
| `backend/tests/test_assignments.py` | 7 unit tests covering create, available filtering, claim, double-claim, complete + wrong-agent, release |
| `backend/tests/test_orchestrator.py` | 11 unit tests covering freeze idempotency, leaf detection, neighbor interfaces, assignment fan-out, `run_implementation_internal` happy path, **path-traversal** regression, **idempotency** regression |
| `backend/tests/test_ws.py` | 3 async tests for `ConnectionManager` connect/disconnect lifecycle, broadcast fan-out, session isolation |
| `backend/tests/test_api.py` *(extension)* | M5 endpoint coverage (freeze gate, agent register/list, claim/release, implement-then-download) |
| `frontend/src/types/contract.ts` *(extension)* | TS mirrors of M5 schemas + WS message union |
| `frontend/src/api/client.ts` *(extension)* | `freezeContract`, `startImplementation`, `registerAgent`, `listAgents`, `downloadGenerated` |
| `frontend/src/state/contract.ts` *(extension)* | M5 store slice — `isFrozen`, `isImplementing`, `implementationMode`, `implementationComplete`, `connectedAgents`, `nodeAgents`, `nodeProgress`, `integrationMismatches` + thunks `freeze` / `implement` |
| `frontend/src/state/websocket.ts` | New Zustand WS store with reconnect-with-backoff and **session-switch race fix** (detach old `onclose` before close) |
| `frontend/src/components/ControlBar.tsx` *(extension)* | Header subtitle transitions, **Freeze** button gated on `uvdcScore >= 1.0 && errorCount === 0`, **Implement (internal/external)** buttons, **Download** anchor, tooltip explaining the 100%-coverage gate |
| `frontend/src/components/AgentPanel.tsx` | Side panel listing connected agents and their claimed nodes; renders only during/after Phase 2 |
| `frontend/src/components/NodeCard.tsx` *(extension)* | `STATUS_RING` map (`drafted` / `in_progress` yellow pulse / `implemented` emerald / `failed` red), violet agent-claim badge |
| `frontend/src/App.tsx` *(extension)* | Mounts `AgentPanel` alongside the graph during Phase 2 |
| `scripts/external_agent_example.py` | Reference external-agent loop: register → poll → claim → progress → submit |

## File guide in this directory

| File | What it covers |
| --- | --- |
| `01-overview.md` | Where M5 sits, end-to-end Freeze → Implement → Download sequence, design choices |
| `02-freeze-and-leaves.md` | `freeze_contract`, hashing, status guards, leaf-node detection, neighbor-interface extraction |
| `03-agents-and-assignments.md` | Agent registry, heartbeat / disconnect, assignment lifecycle, lock-protected claim |
| `04-orchestrator-and-integration.md` | `create_assignments` idempotency, internal subagent loop, mock fallback on LLM failure, integration pass |
| `05-api-and-websocket.md` | The 11 REST routes, the `/stream` WebSocket, `ConnectionManager`, broadcast helpers, path-traversal hardening |
| `06-frontend.md` | API client, contract + websocket Zustand stores, ControlBar / AgentPanel / NodeCard wiring, status-ring colors |
| `07-tests-and-acceptance.md` | Test layout, fixture strategy, recorded E2E test plan and how each annotation was verified |
| `08-bugs-found-and-fixed.md` | Internal bugs caught during the build (claim-before-complete, path traversal in subagent filenames, TOCTOU in assignment mutations) plus the three Devin Review fixes (zip leak, ws-disconnect leak, claim-state inconsistency) plus the second Devin Review pass (path traversal in `download_generated`, duplicate assignments on repeated `/implement`, ws reconnection race) |

## Acceptance summary

- `pytest tests/ -v` → **123 passed** (M1 + M2 + M3 + M4 + 28 new M5 tests).
- Frontend `tsc --noEmit` + `npm run lint` + `npm run build` all green.
- Live E2E run (recorded) on the canned *"Build a Slack bot that summarizes unread DMs daily."* prompt completed Freeze → Implement (internal) → Download. All 6 nodes flipped yellow → green via WebSocket without manual refresh; the downloaded zip contained `contract.json` (`meta.status=complete`, `meta.frozen_hash` populated) plus 6 node directories with real Python code (e.g. `daily_scheduler.py` 4447 bytes with APScheduler imports + class + functions).
- All 4 recording annotations (1 setup + 3 test asserts) PASSED.

## What M5 does NOT include

- **Persistence for agents/assignments/WebSocket connections.** All three live in process-local memory; restart loses them. Production deploy would back agents/assignments with SQLite (mirroring `app.contract`) and switch the connection registry to Redis or similar.
- **Internal-mode parallelism.** `run_implementation_internal` walks assignments sequentially. `asyncio.gather` (or a worker pool) is the obvious next step but was deliberately out of scope for the demo path.
- **A real integration model.** `run_integration_pass` only flags edges with a declared `payload_schema` whose source has empty exports. Comparing actual function signatures against declared payloads is left for a follow-up.
- **Authentication on `/agents` and the WebSocket endpoint.** Anyone reachable on the API can register an agent and subscribe to a session.
- **Live updates of `meta.status` over WebSocket.** The store re-derives `isFrozen` / `isImplementing` from broadcast events; a fresh page load reads it from `GET /sessions/{id}` instead.
