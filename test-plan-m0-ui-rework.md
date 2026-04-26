# Test Plan — M0 UI Rework (PR #2)

PR: https://github.com/Ezimakyu/IterViz/pull/2 (head `be99c35`)
Target: frontend-only, `cd frontend && npm run dev` on `http://localhost:5173`.

Each test is designed so a broken implementation would produce a visibly different outcome.

## Code paths under test

| Claim | File | Evidence |
|---|---|---|
| Compact pill nodes show only name + confidence bar | `frontend/src/components/NodeCard.tsx:28-67` | No "Show details" button, no inline `Assumes:` paragraph |
| Click node → top-right popup with X | `frontend/src/components/Graph.tsx:65-73, 134-139`, `frontend/src/components/NodeDetailsPopup.tsx:41-80` | `toggleSelectedNode`; popup `absolute right-4 top-4`, X button |
| Click edge → bottom-right smaller popup | `frontend/src/components/EdgeLabel.tsx:54-73`, `frontend/src/components/EdgeDetailsPopup.tsx:29-42` | `toggleSelectedEdge`; `absolute bottom-4 right-4 w-[320px]` |
| Physics jiggle + boost on select | `frontend/src/hooks/useForceLayout.ts:44-51, 75-77` | charge uses `boostedRef`; boost = `-2400`, base `-900`; alpha bumped on id change |
| Floating edges route to near side | `frontend/src/utils/floatingEdges.ts:18-47`, `frontend/src/components/EdgeLabel.tsx:36-57` | BBox-intersection recomputed every render from live `nodeInternals` |
| Drag pins node to pointer | `frontend/src/hooks/useForceLayout.ts:103-112` | `fx`/`fy` set while `prev.dragging`, cleared otherwise |
| Descriptive kind labels in popup | `frontend/src/components/NodeDetailsPopup.tsx:3-10` | `store → Data Store`, `job → Event Handler`, `external → External Service` |
| Dropdown re-seeds without reload | `frontend/src/state/contract.ts:45-66`, `frontend/src/components/Graph.tsx:95` | `<ReactFlow key={contract.meta.id}>` remount + force sim rebuild |

## Adversarial flow (recorded, one pass)

### T1. Initial small-contract render is compact pills, not old fat cards

1. Open `http://localhost:5173`. Wait for layout to settle.
2. **Assert**: Exactly 4 pill-shaped nodes visible with names "CLI Entry Point", "Data Fetcher", "Local Cache", "Report Writer".
3. **Assert**: Each pill contains ONLY the node name and a horizontal confidence bar. No "Show details" button, no kind badge, no status badge, no "Assumes:" paragraph.
4. **Assert**: Pills are fully rounded (border-radius uses `rounded-full`), not rectangular.
5. **Assert**: `Local Cache` confidence bar is **red** (<0.5 threshold at 0.45). `Data Fetcher` is **yellow** (0.70). `Report Writer` and `CLI Entry Point` are **green** (0.90 / 0.85).

Broken-implementation signature: old rectangular cards, visible "Show details" button, or mono-color confidence bars.

### T2. Node click → top-right scrollable popup + magnetic node separation

1. Click the `CLI Entry Point` pill.
2. **Assert**: A popup appears anchored to the top-right of the canvas (~right-4 top-4), visibly not covering the pill it was opened for.
3. **Assert**: Popup header shows kind badge reading `INTERFACE` and status badge reading `DRAFTED`, with the node name `CLI Entry Point` below.
4. **Assert**: Popup body contains the description "Parses command-line args and orchestrates the run.", a `Responsibilities` list with exactly `Parse CLI flags`, `Load config file`, `Invoke fetcher and writer`, and an `Open questions` list containing `Should --dry-run be supported in M0?`.
5. **Assert**: Between before-click and ~1 second after the popup is open, the other three pills visibly move outward — measured by eye as a clear position change of ≥ 20 px on at least two neighbors. If the positions are identical to pre-click frames, the boost force is broken.
6. Click the X button in the popup header.
7. **Assert**: Popup disappears and `CLI Entry Point` visibly drifts back toward the center cluster (boost released).

Broken-implementation signature: popup doesn't appear, popup opens on top of the clicked node, no position change in neighbors, or X button doesn't close.

### T3. Edge click → bottom-right edge popup with payload fields; re-click closes

1. Click the `DATA` edge label between `Data Fetcher` and `Local Cache`.
2. **Assert**: A smaller popup appears anchored to the bottom-right (~bottom-4 right-4), noticeably smaller than the node popup (~320px wide vs ~420px).
3. **Assert**: Popup header shows a colored `DATA` pill, title text `Data Fetcher → Local Cache`, an X button, and below it `Label · store payload`, `Payload · object with 3 fields`, a `Fields` list containing `url : string · required`, `body : string · required`, `fetched_at : string`, and `confidence · 70%`.
4. Click the same edge label again (no X click).
5. **Assert**: Popup disappears (toggle-off via re-click).
6. Click it a third time → popup returns. Click the X button.
7. **Assert**: Popup disappears (X also works).

Broken-implementation signature: popup doesn't appear, missing fields list, wrong source/target order, or re-click doesn't toggle off.

### T4. Drag a node → edges re-route to the sides facing the counterpart

1. Drag `Local Cache` from its current position to the top-right of the canvas (far enough that it's above and right of `Data Fetcher`).
2. **Assert**: While dragging and after release, the edge between `Data Fetcher` and `Local Cache` enters/leaves on the sides of the two pills that face each other (i.e., from the top-right side of `Data Fetcher` and the bottom-left side of `Local Cache`). The edge does NOT pass through or clip across the pill body.
3. **Assert**: After releasing, the physics sim continues to animate — the node is not frozen where dropped; over ~2 seconds it drifts back under link attraction.

Broken-implementation signature: edges locked to fixed handles (top/bottom), passing through nodes, or node frozen after drop.

### T5. Dropdown switch → medium contract in place with descriptive kind labels

1. Open the `Contract` dropdown in the header and select `Medium (web app w/ auth + DB)`.
2. **Assert**: The URL stays `http://localhost:5173/` (no page refresh flash).
3. **Assert**: After the sim settles, exactly 8 pills are visible: `Web UI`, `REST API`, `Auth Service`, `Postgres`, `Redis Cache`, `Stripe API`, `Email Provider`, `Webhook Worker` (note the renames).
4. **Assert**: `Redis Cache` confidence bar is **red** (0.45), `Webhook Worker` is **yellow** (0.55), `Web UI` is **green** (0.90).
5. Click `Webhook Worker` pill.
6. **Assert**: Node popup opens showing kind badge text `EVENT HANDLER` (not `JOB`). The description reads "Background event handler that consumes Stripe webhooks asynchronously.".
7. Close the popup. Click `Redis Cache` pill.
8. **Assert**: Node popup kind badge reads `DATA STORE` (not `STORE`).

Broken-implementation signature: page refreshes (URL changes or white flash), wrong number of pills, old raw `JOB`/`STORE` labels, or labels still showing `Background Worker`/`Redis`.

## Out of scope

- Backend / WebSockets (M1+).
- Automated unit tests.
- Long-running perf or FPS measurements of the sim — visual confirmation only.
