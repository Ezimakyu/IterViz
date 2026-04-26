# 06 — Frontend: API client, stores, components, status rings

This document covers the frontend half of M5: the typed API client
extensions, the new WebSocket Zustand store, the `contract` store
extensions, and the three components that drive the Phase 2 UX
(`ControlBar`, `AgentPanel`, `NodeCard`).

## API client (`frontend/src/api/client.ts`)

Five new functions were added on top of the M3 client, all returning
`Promise<T | ApiError>` (no thrown 4xx/5xx):

| Export | HTTP |
| --- | --- |
| `freezeContract(sessionId)` | `POST /sessions/{id}/freeze` |
| `startImplementation(sessionId, mode)` | `POST /sessions/{id}/implement` |
| `registerAgent(name, type)` | `POST /agents` |
| `listAgents()` | `GET /agents` |
| `downloadGenerated(sessionId)` | URL builder for `GET /sessions/{id}/generated` (consumed as an `<a href>`) |

`downloadGenerated` is a URL builder rather than a `fetch` because the
zip is delivered straight to the browser via an anchor click; calling
`fetch` and converting to a blob would buffer the entire archive in
memory.

## WebSocket store (`frontend/src/state/websocket.ts`)

A standalone Zustand store. It holds the live `WebSocket`, a flat
`connected` flag, the `sessionId` it's bound to, and a
`reconnectAttempts` counter (capped at `MAX_RECONNECT_ATTEMPTS = 5`,
`RECONNECT_DELAY_MS = 1500`).

### Connection lifecycle

```
connect(sessionId):
  if existing socket already on this session → return (idempotent)
  if existing socket on a different session →
      existing.onclose = null         ←── prevent stale reconnect
      existing.close()
      set({ socket: null, sessionId, reconnectAttempts: 0 })
  open():
      socket = new WebSocket(`${WS_BASE}/sessions/${sessionId}/stream`)
      socket.onopen     → set({ socket, connected: true, sessionId, ... })
      socket.onmessage  → JSON.parse → handleMessage(data)
      socket.onclose    → if still on same sessionId AND under cap,
                          schedule open() in 1.5s
      socket.onerror    → set({ lastError: "..." })
disconnect():
  socket?.close()
  reset all fields
```

### Session-switch race fix

When the user switches between sessions A → B, the original code did
`existing.close()` and let the new socket's `onopen` update
`sessionId`. The old socket's `onclose` fires asynchronously *between*
those two events; at that moment `get().sessionId` is still `"A"`, so
the close handler decides "I'm still on A, schedule a reconnect in
1.5s". 1.5s later that reconnect opens a fresh socket on session A
and overwrites the just-set `sessionId="B"`. Net result: silent
session reversion.

The fix detaches the close handler **before** closing
(`existing.onclose = null`) and eagerly writes the new `sessionId` /
resets `reconnectAttempts` into the store before opening the new
socket. With the close handler gone, the stale onclose can never fire,
and even if it could, the store already reflects session B.

### `handleMessage` dispatch

Every WS message is mapped onto a contract-store action:

| `message.type` | Action |
| --- | --- |
| `node_status_changed` | `updateNodeStatus(node_id, status, agent?)` |
| `node_claimed` | `updateNodeStatus(node_id, "in_progress", { id, name })` |
| `node_progress` | `setNodeProgress(node_id, progress)` |
| `agent_connected` | `setAgentInfo(agent_id, ...)` |
| `implementation_complete` | `setImplementationComplete(success)` |
| `integration_result` | `setIntegrationMismatches(mismatches)` |
| `error` | `console.warn` (no UI-visible error toast yet) |

The contract store actions only mutate state — they don't trigger any
network calls — so the dispatch loop is cheap and the UI re-renders
follow naturally from Zustand's selector subscriptions.

## Contract store extensions (`frontend/src/state/contract.ts`)

New M5 fields on top of the M3 / M4 store:

| Field | Type | Where it's set |
| --- | --- | --- |
| `isFrozen` | `boolean` | True after `freeze` thunk; also derived from `meta.status` (`verified` / `implementing` / `complete`) when a session is loaded from `GET /sessions/{id}` |
| `isImplementing` | `boolean` | Set true on `implement` thunk; cleared by `setImplementationComplete` |
| `implementationMode` | `'internal' \| 'external' \| null` | Tracks which mode the user picked |
| `implementationComplete` | `boolean` | Driven by `implementation_complete` WS message |
| `implementationSuccess` | `boolean` | Same broadcast carries the `success` boolean |
| `connectedAgents` | `Map<string, Agent>` | Driven by `agent_connected` WS message |
| `nodeAgents` | `Map<string, { agentId, agentName }>` | Driven by `node_claimed` / `node_status_changed{status=in_progress}` |
| `nodeProgress` | `Map<string, number>` | Driven by `node_progress` |
| `integrationMismatches` | `IntegrationMismatch[]` | Driven by `integration_result` |

Two new thunks:

- `freeze()` — calls `API.freezeContract(sid)`, snapshots the current
  contract into `previousContract` (so a future Verify-style diff
  highlight could fire), sets `isFrozen: true`.
- `implement(mode)` — sets `isImplementing: true`,
  `implementationMode: mode`, then calls
  `API.startImplementation(sid, mode)`. The WebSocket is *already*
  connected by `ControlBar.startImplement` so the first
  `node_status_changed` after the HTTP response lands hits the store.

`updateNodeStatus(nodeId, status, agent?)` is centrally responsible
for keeping `nodeAgents` consistent: when an agent is provided, it
records the binding; when status flips back to `drafted` (i.e. on
`release`), it removes the binding so the violet agent badge clears.

## `ControlBar.tsx`

Single header row that renders:

- **Glasshouse** title + status subtitle (transitions
  `M3 · Architect ↔ Compiler ↔ Q&A loop` → `M5 · Phase 2 ready` →
  `M5 · Phase 2 implementing…`).
- Iteration / Coverage / Violations stats (carried over from M3, with
  M5 just reading them).
- **Verify** button (M3) — disabled once frozen.
- **Freeze / Frozen** button — `canFreeze = !!sessionId && !isLoading
  && !isFrozen && uvdcScore >= 1.0 && errorCount === 0`. Tooltip text
  switches between *"Reach 100% coverage with 0 errors before
  freezing"* and *"Freeze the contract for implementation"*.
- **Implement (internal)** and **Implement (external)** buttons —
  `canImplement = !!sessionId && !isLoading && isFrozen &&
  !isImplementing && !implementationComplete`. Both call
  `startImplement(mode)` which **first** ensures the WebSocket is
  open (`wsConnect(sessionId)`) so we don't miss the early
  `node_status_changed=in_progress` messages, then dispatches the
  `implement` thunk.
- **Download** anchor — only renders when `implementationComplete`,
  links straight to `API.downloadGenerated(sessionId)`.
- **Reset** — same M3 behavior.

### Why connect WS before HTTP

The bug this avoids: open WS *after* `POST /implement` returns, and
the backend has already started broadcasting the first
`node_status_changed=in_progress` to zero subscribers. The user then
sees a node go straight from `drafted` to `implemented` with no
yellow ring, breaking the "live updates" demo.

## `AgentPanel.tsx`

Right-rail side panel. Renders `null` until either `isImplementing` or
`implementationComplete` is true, so it stays out of the way during
Phase 1.

The component reads `connectedAgents` and `nodeAgents`, builds a
`Map<agentId, nodeName[]>` so each agent's claimed-node list is shown
directly under its name, and renders one card per agent with:

- Agent name + status (`active` green, `disconnected` red, `idle`
  muted).
- Agent type pill.
- Bulleted list of node names currently claimed.

When `implementationComplete` flips, a one-line banner at the top of
the panel shows either *"Implementation complete"* (emerald) or
*"Implementation finished with failures"* (red).

## `NodeCard.tsx` — status rings + agent badge

The status ring map:

```ts
const STATUS_RING: Record<NodeStatus, string> = {
  drafted: "",
  in_progress: "!ring-yellow-400 ring-[4px] animate-pulse",
  implemented: "!ring-emerald-500 ring-[4px]",
  failed: "!ring-red-500 ring-[4px]",
};
```

The yellow `animate-pulse` is what the recording captures as nodes go
through implementation.

`NodeCard` already had three other ring sources from M3 / M4:

- `isNew` / `isChanged` → yellow ring (M3 diff highlight).
- `isUserEdited` → blue ring (M4 user-edit provenance).
- `isFocused` (selection) → sky border.

Tailwind class collisions are handled with the `!` important prefix on
the M5 status ring classes so the implementation status always wins
over the M3 diff highlight when both are active. The M4 blue ring
keeps its `!ring-blue-500/80` so a user-edited node doesn't lose its
blue ring when it transitions to `in_progress` — the user-edit signal
is a separate dimension.

A small violet agent-claim badge (just the agent name, with a
`title="Claimed by …"` tooltip) renders in the top-left of the node
card when `nodeAgents.get(id)` is set, so the user can see which
external agent is currently working on a node without opening the
side panel.

## `App.tsx`

The only change is conditional mounting of `AgentPanel` next to the
graph during Phase 2 (`{ (isImplementing || implementationComplete)
&& <AgentPanel /> }`). Phase 1 layout (PromptInput / ControlBar /
Graph / QuestionPanel) is untouched.
