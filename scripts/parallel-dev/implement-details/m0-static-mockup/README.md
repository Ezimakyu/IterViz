# M0 — Static React Flow Mockup: Implementation Details

This directory documents how Milestone M0 (the architecture-contract visualizer
in `frontend/`) was built and iterated. M0 started as the static dagre mockup
described in `scripts/parallel-dev/prompts/m0-static-mockup.md` and evolved
through six rounds of user feedback into a physics-driven, semantic L→R
flow with native-zoom panning.

The implementation lives in `frontend/src/`. The merged PR is
[Ezimakyu/IterViz#2](https://github.com/Ezimakyu/IterViz/pull/2).

## Reading order

1. [`01-architecture.md`](./01-architecture.md) — file layout, component
   responsibilities, data flow from JSON → store → React Flow.
2. [`02-physics-layout.md`](./02-physics-layout.md) — d3-force simulation,
   custom forces, the tick → React Flow bridge.
3. [`03-semantic-flow.md`](./03-semantic-flow.md) — hierarchy tiers, BFS
   rank, per-tier sizing/charge tables, snowflake clustering.
4. [`04-floating-edges.md`](./04-floating-edges.md) — relative-position
   side picking and intersection math for edges.
5. [`05-ui-popups.md`](./05-ui-popups.md) — pill nodes, node/edge popup
   overlays, contract dropdown.
6. [`06-viewport.md`](./06-viewport.md) — the final pan-on-drag + native
   zoom decision (replaces auto-fitView).
7. [`07-iterations.md`](./07-iterations.md) — timeline of every behaviour
   change with the constants that moved.
8. [`08-testing.md`](./08-testing.md) — DOM-measurement patterns used to
   verify spacing, drag, and label clearance.

## High-level summary

- **Frontend stack**: Vite + React 18 + TypeScript, Tailwind for layout,
  Zustand for the contract/selection store, React Flow 11 as the canvas
  primitive, d3-force as the layout engine.
- **Layout**: nodes are classified into four tiers (`core`, `feature`,
  `child`, `orphan`) which control both rendered pill size and physics
  charge. A BFS rank from entry points pins each node to a vertical
  column via `forceX`, giving a left-to-right flow.
- **Physics**: a continuously running `forceSimulation` (`alphaMin
  0.02`) provides Obsidian-style live jiggle. Custom forces handle
  edge-label vs node repulsion, edge-label vs edge-label repulsion, and
  snowflake clustering of children around their parent.
- **Edges**: rendered as floating SVG paths whose endpoints are
  recomputed from the live node bounding boxes every tick, so edges
  always leave/enter on the side facing the other node.
- **Interaction**: clicking a node opens a scrollable popup; clicking an
  edge opens a smaller popup. The selected node's charge is boosted
  (`-2800`) so neighbours visibly drift outward while the popup is open.
- **Viewport**: render at native zoom 1.0 with a fixed initial
  viewport. Graphs that exceed the canvas overflow off-screen; the user
  pans by left-click-dragging the canvas background. There is no
  auto-fitView.
