# 02 — Physics Layout (d3-force)

The original M0 spec called for static dagre layout. After the first round
of UI feedback ("Obsidian-style magnetic graph"), the layout engine was
swapped for `d3-force`. The hook `src/hooks/useForceLayout.ts` owns the
simulation.

## Why a continuous simulation

`forceSimulation` is configured with `alphaMin: 0.02` and
`alphaDecay: 0.012`, so the simulation never fully cools. This gives:

- **Live jiggle** — nodes drift slightly even at rest.
- **Reactive selection** — bumping `alpha` to 0.6 on selection change
  causes an immediate visible re-layout around the focused node.
- **Drag-aware** — when the user drags a node, that node is pinned via
  `fx`/`fy` until release; the rest of the graph re-arranges around it.

Trade-off: the sim costs a few hundred microseconds per tick on the
medium contract, which is invisible at 60fps. For graphs with hundreds
of nodes this would need to be revisited.

## Forces in the simulation

```
charge          forceManyBody, per-tier strength (or BOOST_CHARGE if selected)
link            forceLink, distance varies by tier (CHILD_LINK_DISTANCE for kids)
collide         forceCollide, radius = max(width,height)/2 + 28
flowX           forceX(targetX), strength 0.18  ← rank-column pinning
centerY         forceY(0), strength 0.04        ← gentle vertical centering
labelRepel      custom — see below
labelLabelRepel custom — see below
snowflake       custom — see below
```

### Custom force: `labelRepel`

Each edge midpoint acts as a virtual collision body. For every
non-adjacent node within `LABEL_CLEARANCE` (140px) of an edge midpoint,
we push the node outward proportional to overlap:

```ts
const dist = Math.hypot(dx, dy);
const minR = n.width / 2 + LABEL_CLEARANCE;
if (dist < minR) {
  const push = ((minR - dist) / dist) * alpha * 1.4;
  n.vx += dx * push;
  n.vy += dy * push;
}
```

This is the force that keeps "DATA" / "CONTROL" / "EVENT" / "DEPENDENCY"
kind pills readable instead of squished between two nodes.

### Custom force: `labelLabelRepel`

Two edge midpoints can be near each other even when their endpoint
nodes are far apart (think two parallel edges). When two midpoints are
within `LABEL_LABEL_CLEARANCE` (130px) and the edges share no endpoint,
we split the push between both edges' endpoint nodes so the labels
separate:

```ts
const fx = dx * push * 0.5;
const fy = dy * push * 0.5;
a.s.vx += fx;  a.s.vy += fy;   // edge A endpoints pushed one way
a.t.vx += fx;  a.t.vy += fy;
b.s.vx -= fx;  b.s.vy -= fy;   // edge B endpoints pushed the other
b.t.vx -= fx;  b.t.vy -= fy;
```

### Custom force: `snowflake`

For child-tier nodes (single parent, parent is core), pull toward the
parent's current Y so children orbit the parent's row. Horizontal pull
is gentle (0.08·alpha) because rank already pins X; vertical pull is
stronger (0.18·alpha) so children don't drift up/down.

### Selection boost

`opts.boostedId` is the currently selected node id. The charge force
checks each tick whether a node is the boosted one and returns
`BOOST_CHARGE = -2800` instead of the per-tier value. The selection
useEffect also bumps `sim.alpha()` to ≥0.6 so the boost takes effect
immediately.

## Tick → React Flow bridge

Every tick the hook reads RF's current node array, copies it, and
overwrites positions with the simulation's. Drag state is preserved by
checking `prev.dragging` and pinning the sim node via `fx`/`fy`:

```ts
sim.on("tick", () => {
  const current = getNodes();
  const next: Node[] = [];
  for (const sn of simNodes) {
    const prev = byId.get(sn.id);
    if (prev?.dragging) {
      sn.fx = prev.position.x + (prev.width ?? sn.width) / 2;
      sn.fy = prev.position.y + (prev.height ?? sn.height) / 2;
      next.push(prev);
      continue;
    }
    if (sn.fx != null) { sn.fx = null; sn.fy = null; }
    next.push({
      ...prev,
      position: {
        x: (sn.x ?? 0) - sn.width / 2,
        y: (sn.y ?? 0) - sn.height / 2,
      },
    });
  }
  setNodes(next);
});
```

Two subtleties worth calling out:

- The simulation stores **center coordinates**; React Flow expects
  **top-left**. Hence the `sn.x - width/2` translation on every tick.
- `setNodes` returns a new array reference every tick. React Flow's
  internal store does shallow equality so this triggers a re-render
  cycle. With ~12 nodes this is fine; for larger graphs we'd need to
  batch or memoise.

## Tunable constants

| Constant | Final | Earlier | Notes |
|---|---:|---:|---|
| `BOOST_CHARGE` | -2800 | -2800 | unchanged after first physics round |
| `LINK_DISTANCE` | 380 | 280 → 240 | spaced wider with each iteration |
| `CHILD_LINK_DISTANCE` | 240 | 150 → 130 | children closer to parent |
| `LABEL_CLEARANCE` | 140 | 110 → 72 | node↔edge-midpoint clearance |
| `LABEL_LABEL_CLEARANCE` | 130 | 90 / new | introduced in semantic-flow round |
| `RANK_SPACING` | 480 | 360 → 260 | column width along X |
| label-repel mult | 1.4 | 0.7 | boosted in the spacing round |
| label-label-repel mult | 1.2 | 0.5 | boosted in the spacing round |
