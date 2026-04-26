# 04 — Frontend (`frontend/src/...`)

The frontend is wired live to the M3 backend through one thin API
client, one Zustand store, four components, and a small layout switch
in `App.tsx`. Selection state from M0/M2 is preserved so the existing
graph and node-card interactions keep working unchanged.

## API client (`src/api/client.ts`)

A single typed module with five async functions:

```typescript
const API_BASE = "http://localhost:8000/api/v1";

export const API = {
  createSession(prompt) → Promise<{ session_id, contract } | ApiError>
  getSession(sessionId) → Promise<{ contract } | ApiError>
  verifyContract(sessionId) → Promise<CompilerResponse | ApiError>
  submitAnswers(sessionId, decisions) → Promise<{ contract } | ApiError>
  refineContract(sessionId, decisions?) → Promise<{ contract; diff? } | ApiError>
};
```

All five functions return `T | ApiError` instead of throwing on 4xx /
5xx. The store always checks `isApiError(result)` before consuming the
value, so a failed verify or refine surfaces a friendly error message
in the UI rather than crashing the React tree.

`ApiError` is a discriminated union with a `kind: "ApiError"` brand
plus `status` and `detail` fields lifted from the FastAPI error
response.

## Zustand store (`src/state/contract.ts`)

The store owns:

| Field | Purpose |
| --- | --- |
| `sessionId` | UUID returned by `POST /sessions`; absent ⇒ render `PromptInput` fullscreen. |
| `contract` | Latest contract from the backend. |
| `previousContract` | Snapshot from before the most recent refine — input to diff highlighting. |
| `violations`, `questions`, `uvdcScore` | Latest `CompilerResponse` artifacts. |
| `iteration` | Number of completed Verify → Submit → Refine cycles. The ControlBar shows `Iteration {iteration}/3`. |
| `selectedNodeId`, `selectedEdgeId` | Inherited from M0; preserved verbatim. |
| `isLoading`, `error` | UI gating for buttons + error banners. |

### Three thunks

```typescript
startSession(prompt)             → POST /sessions, on success calls setSession
verify()                         → POST /sessions/{id}/compiler/verify
                                   on success calls setVerificationResult
submitAnswersAndRefine(decs)     → POST /sessions/{id}/answers
                                   then POST /sessions/{id}/architect/refine
                                   on success: snapshot previousContract,
                                   bump iteration, **clear violations +
                                   questions + uvdcScore**
```

The "clear stale artifacts on refine" step in
`submitAnswersAndRefine` is one of the bugs caught during validation
(see `07-bugs-found-and-fixed.md`). Coverage and violation counts are
computed against the *previous* contract; leaving them in place makes
the ControlBar lie until the user clicks Verify again.

### Action helpers

- `setSession(sessionId, contract)` — also clears
  `previousContract`, `violations`, `questions`, `uvdcScore`,
  `iteration`, `error`, and selection. Used on a fresh session.
- `setVerificationResult(result)` — pulls only `violations`,
  `questions`, `uvdc_score` from `CompilerResponse`. Does **not**
  touch `previousContract` or `iteration`.
- `updateContract(contract)` — snapshots `previousContract = current`
  before swapping. Used by the refine path internally.
- `resetSession()` — wired to the ControlBar's Reset button; clears
  every field back to the initial state.

## Components

### `PromptInput.tsx`

Fullscreen card with a large textarea, an **Architect** primary
button (label flips to `Drafting…` while `isLoading`), and a **Use
sample prompt** secondary button. Submission calls
`startSession(prompt)`; an empty prompt keeps the button disabled.

### `ControlBar.tsx`

Horizontal header rendered when a session exists. Three columns:

```
[Glasshouse · M3 · Architect ↔ Compiler ↔ Q&A loop]
                                                           ITERATION  COVERAGE  VIOLATIONS  [Verify] [Reset]
                                                              0/3        0%       0E / 0W
```

- `Iteration` shows `{iteration}/3`.
- `Coverage` shows `{Math.round(uvdcScore * 100)}%`.
- `Violations` shows error count `E` and warning count `W` derived
  from `violations`.
- `Verify` button is disabled when `isLoading` and shows `Verifying…`
  during the call.
- `Reset` is disabled while loading; calls `resetSession`.

### `QuestionPanel.tsx`

Right-hand aside. When there are no questions the empty state reads
*"Click Verify to ask the Blind Compiler what's missing."* Otherwise
it renders an ordered list of up to five question cards:

```
1. <question text>
   error · failure_scenario     ← derived from violation type/severity
   Affects: [chip] [chip]       ← clicking a chip selects the node/edge
   <textarea: "Your answer…">
```

Each card maintains a local `answers[i]` string. The **Submit
Answers** button is disabled until at least one textarea has
non-empty trimmed text; clicking it builds an array of `Decision`
objects and calls `submitAnswersAndRefine(decisions)`.

The chips are real buttons that dispatch `setSelectedNode` /
`setSelectedEdge`, matching the existing M0 selection flow.

### `Graph.tsx` + `NodeCard.tsx` (extensions)

`Graph.tsx` derives diff state per render:

```typescript
const newNodeIds   = nodeIds(contract) − nodeIds(previousContract)
const changedIds   = nodes whose JSON differs from previousContract's version
const newEdgeIds   = edgeIds(contract) − edgeIds(previousContract)
const changedEdges = edges whose JSON differs
```

It then passes `isNew` / `isChanged` props down to `NodeCard.tsx`,
which applies a `ring-2 ring-yellow-400` Tailwind class for changed
nodes and a small `NEW` badge for nodes that did not exist
previously. A summary pill (`{newCount} new · {changedCount} changed`)
sits at the top-right of the canvas when either count is non-zero.

The diff is recomputed cheaply per render — at the M3 scale of
≤ 10 nodes, doing it server-side would buy nothing.

### `App.tsx`

```tsx
return contract === null
  ? <PromptInputFullscreen />
  : (
    <>
      <ControlBar />
      <main>
        <Graph />
        <QuestionPanel />
      </main>
    </>
  );
```

Layout swaps based purely on `contract === null`. The fullscreen
prompt and the working layout are mutually exclusive.
