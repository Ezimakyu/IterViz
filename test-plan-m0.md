# M0 Static React Flow Mockup — Test Plan

PR: https://github.com/Ezimakyu/IterViz/pull/2
Branch: `devin/1777162153-m0-static-mockup`
Scope: pure frontend under `frontend/`. No backend. All tests run against `npm run dev` on `http://localhost:5173`.

## What changed (user-visible)

- A new `frontend/` app renders an architecture contract as a React Flow DAG.
- Contracts are loaded from `/sample_contract_small.json` (4 nodes / 5 edges) and `/sample_contract_medium.json` (8 nodes / 12 edges).
- Dagre (`rankdir=TB`, `nodesep=80`, `ranksep=100`) lays nodes out non-overlapping.
- Each node card shows name, kind badge, status badge, a colored confidence bar, first assumption (truncated), and a "Show details" toggle that expands description / responsibilities / assumptions / open questions.
- Each edge has a kind badge label with a hover tooltip that reveals kind + payload summary (e.g. `payload: object with 3 fields`).
- A header dropdown switches between the two contracts and re-renders the canvas without a full page reload.

## Code paths traced (evidence)

| Behavior | File | Notes |
|----------|------|-------|
| Dropdown and store wiring | `frontend/src/App.tsx:21-47`, `frontend/src/state/contract.ts:29-54` | Zustand store fetches from `public/` on select change. |
| Dagre layout constants | `frontend/src/utils/layout.ts:4-47` | `NODE_WIDTH=280`, `NODE_HEIGHT=160`, `rankdir=TB`, `nodesep=80`, `ranksep=100`. |
| Confidence color thresholds | `frontend/src/components/NodeCard.tsx:31-35` | `<0.5` red, `<0.8` yellow, else green. |
| Expand toggle | `frontend/src/components/NodeCard.tsx:82-99` | Button text flips "Show details" ↔ "Hide details"; details block is conditional. |
| Edge hover tooltip | `frontend/src/components/EdgeLabel.tsx:51-79` | Tooltip is `invisible` + `group-hover:visible`; shows kind + `payload: <summary>`. |
| Re-render on contract switch | `frontend/src/components/Graph.tsx:45-58` | `<ReactFlow key=contract.meta.id ... fitView>` forces remount + re-fit. |

## Adversarial primary flow

Each step has an expected concrete observation. If the M0 implementation were broken, at least one assertion would visibly fail.

### T1. Initial load — small contract renders through dagre with no overlap

1. Open `http://localhost:5173`.
2. **Assertion**: Header shows "Glasshouse" and a dropdown pre-selected to "Small (CLI tool)".
3. **Assertion**: Exactly 4 node cards are visible: "CLI Entry Point", "Data Fetcher", "Local Cache", "Report Writer".
4. **Assertion**: No two node card bounding boxes overlap (visual — cards are arranged top-to-bottom with visible gap; dagre would fail silently by stacking everything at (0,0), which would be obvious).
5. **Assertion**: "Local Cache" confidence bar is **red** (confidence 0.45 — below 0.5 threshold).
6. **Assertion**: "Data Fetcher" confidence bar is **yellow** (confidence 0.7 — in [0.5, 0.8) band).
7. **Assertion**: "Report Writer" confidence bar is **green** (confidence 0.9 — above 0.8).

A broken implementation would show overlapping nodes (no dagre) or all bars the same color (broken threshold).

### T2. NodeCard expand reveals the richer detail block

1. On the small contract, click "Show details" on "CLI Entry Point".
2. **Assertion**: The button text flips to "Hide details".
3. **Assertion**: A "Responsibilities" bulleted list appears containing exactly "Parse CLI flags", "Load config file", "Invoke fetcher and writer".
4. **Assertion**: An "Open questions" list appears containing "Should --dry-run be supported in M0?".
5. Click the button again.
6. **Assertion**: Button text flips back to "Show details" and the details block is hidden.

A broken toggle would either not change the text, not toggle visibility, or permanently show/hide the section.

### T3. Edge hover tooltip shows kind + payload summary

1. On the small contract, hover the edge from "Data Fetcher" → "Local Cache" (kind `data`, `payload_schema` has 3 fields).
2. **Assertion**: A tooltip appears containing the text `data`, `store payload`, and `payload: object with 3 fields`.
3. Move the cursor away.
4. **Assertion**: Tooltip disappears.

A broken tooltip would either not appear on hover or would show wrong field count/kind.

### T4. Dropdown switch → medium contract re-renders without page refresh

1. Note some non-trivial client-only state (expand a node via T2 first — this state is per-card and lost on hard reload, but the *tab* should not reload).
2. Open the header dropdown and pick "Medium (web app w/ auth + DB)".
3. **Assertion**: The URL stays `http://localhost:5173/` and no full page refresh flash occurs (no white flash, React Flow transitions immediately).
4. **Assertion**: Exactly 8 node cards are visible with names including "Web UI", "REST API", "Auth Service", "Postgres", "Redis", "Stripe API", "Email Provider", "Background Worker".
5. **Assertion**: No two node card bounding boxes overlap (medium graph, still TB layout).
6. **Assertion**: "Redis" confidence bar is **red** (0.45), "Email Provider" is **yellow** (0.65), "Web UI" is **green** (0.9).
7. Switch back to "Small (CLI tool)".
8. **Assertion**: The small graph's 4 nodes re-appear; URL unchanged.

A broken dropdown would either reload the page (URL flash / console reset), not re-layout (overlapping medium graph), or render the old 4 nodes.

## Out of scope

- No backend, no WebSocket, no live diff highlighting. Those land in M3+.
- No automated unit tests for this milestone — M0 is a visualization sanity check.
