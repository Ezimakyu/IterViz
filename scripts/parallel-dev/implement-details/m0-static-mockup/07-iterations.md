# 07 — Iteration Timeline

Six rounds of change between the original M0 spec and the merged PR.
Each round starts from a specific user complaint and ends with what
shipped.

## Round 1 — Original M0 (static dagre)

**Spec**: `scripts/parallel-dev/prompts/m0-static-mockup.md`.
Vite + React + TypeScript + Tailwind + Zustand. `Graph.tsx` with
dagre TB layout (nodesep 80, ranksep 100). `NodeCard.tsx` with
inline expand/collapse. `EdgeLabel.tsx` with hover tooltip.

Result: shipped, all acceptance criteria met. Verified end-to-end
with a recording.

## Round 2 — UI rework (compact pills + popups + physics)

User asked for:

1. Simplify nodes — name + confidence bar only, no inline detail.
2. Move node detail to popup overlays with X to close.
3. Add Obsidian-style magnetic repulsion.
4. Fix edge connection points (no more top-of-A → bottom-of-B).
5. Improve labels (e.g. `store → memory`, `job → event`).

Shipped:

- `NodeCard` rewritten as compact pills.
- `NodeDetailsPopup` (top-right, scrollable, X to close).
- `EdgeDetailsPopup` (bottom-right, smaller, toggle on re-click).
- `useForceLayout` introduced — d3-force with charge/link/collide.
- Floating edges in `floatingEdges.ts` — endpoints recomputed each
  frame from live bounding boxes.
- Renamed nodes: `Background Worker → Webhook Worker`,
  `Redis → Redis Cache`. Kind labels became descriptive
  (DATA STORE, EVENT HANDLER, etc.).

## Round 3 — Edge-label clearance + remove minimap + semantic flow

User asked for:

1. Edge labels should repel nearby nodes so kind pills stay readable.
2. Remove the bottom-right "node layout" selector (= MiniMap).
3. Implement semantic L→R flow with hierarchy-based sizing.

Shipped:

- `hierarchy.ts` introduced — tier classification + BFS rank.
- `TIER_SIZE` (core/feature/child/orphan) drives both DOM size and
  collision radius.
- `TIER_CHARGE` per-tier charge values for `forceManyBody`.
- `forceX(targetX)` pins each node to its rank column.
- Snowflake force pulls children toward parent's Y.
- Custom `labelRepel` force introduced (LABEL_CLEARANCE = 72px at
  this point).
- MiniMap removed.

Constants this round: `RANK_SPACING = 260`, `LINK_DISTANCE = 240`,
`CHILD_LINK_DISTANCE = 130`, `LABEL_CLEARANCE = 72`.

## Round 4 — Stronger spacing (first attempt)

User saw labels still cramped on medium contract. Asked for stronger
edge-label repulsion AND wider horizontal spacing.

Tried:

- Bumped `RANK_SPACING` 260 → 360.
- Bumped `LABEL_CLEARANCE` 72 → 110.
- Added `labelLabelRepel` force (LABEL_LABEL_CLEARANCE = 90).

Tested. Did not pass:

- Medium contract X-delta only 434px (target ≥ 530).
- Two labels overlapped Redis Cache at 0px and 6px.

Root cause: `fitView` was still active and compressing the entire
graph to fit the viewport, so the increased world-space spacing was
zoom-shrunk into the same screen-pixel cramping.

## Round 5 — Pan + native zoom (replaces auto-fit)

User suggestion: stop auto-fitting. Render at zoom 1.0 and let the
user pan.

Shipped:

- Removed `fitView` from `Graph.tsx`.
- Removed auto-fit-on-cool from `useForceLayout.ts`.
- Added `defaultViewport={{ x: 200, y: 360, zoom: 1 }}`.
- Made `panOnDrag` explicit alongside `nodesDraggable`.
- Bumped constants again now that they actually map to screen pixels:
  `RANK_SPACING = 480`, `LINK_DISTANCE = 380`,
  `CHILD_LINK_DISTANCE = 240`, `LABEL_CLEARANCE = 140`,
  `LABEL_LABEL_CLEARANCE = 130`.
- Bumped multipliers in custom forces:
  - `labelRepel`: 0.7 → 1.4
  - `labelLabelRepel`: 0.5 → 1.2

Tested. Passed:

- Pills render at exact `TIER_SIZE` (core 240px wide), no zoom shrink.
- Min label-to-node 26px (target ≥ 18).
- Min label-to-label 62px (target ≥ 30).
- Pan-on-drag confirmed (drag canvas left → content shifts left).
- Node drag still works; edges re-route live.

This is the merged state.

## Constants table (all rounds)

| Constant | Round 3 | Round 4 | Round 5 (final) |
|---|---:|---:|---:|
| `RANK_SPACING` | 260 | 360 | **480** |
| `LINK_DISTANCE` | 240 | 280 | **380** |
| `CHILD_LINK_DISTANCE` | 130 | 150 | **240** |
| `LABEL_CLEARANCE` | 72 | 110 | **140** |
| `LABEL_LABEL_CLEARANCE` | — | 90 | **130** |
| labelRepel mult | 0.7 | 0.7 | **1.4** |
| labelLabelRepel mult | — | 0.5 | **1.2** |
| auto fitView | yes | yes | **no** |
