# 04 — Floating Edges

Static React Flow gives you a "handles on fixed sides" model: each node
declares `<Handle>` positions and edges connect to them. With a physics
sim, nodes move continuously, so a fixed handle on the top-right of a
node is wrong as soon as the target moves below the source.

The fix is **floating edges**: every render frame, recompute the source
and target endpoint positions from the live node bounding boxes.

## Side picking

`src/utils/floatingEdges.ts:getEdgeParams` does this:

```ts
export function getEdgeParams(source: Node, target: Node) {
  const sourceIntersect = getNodeIntersection(source, target);
  const targetIntersect = getNodeIntersection(target, source);
  return {
    sx, sy, tx, ty,
    sourcePos: getEdgeSide(source, sourceIntersect),
    targetPos: getEdgeSide(target, targetIntersect),
  };
}
```

`getNodeIntersection` is the closed-form intersection of the line from
`source.center → target.center` with `source`'s axis-aligned bounding
box:

```ts
const w = source.width / 2;
const h = source.height / 2;
const dx = target.cx - source.cx;
const dy = target.cy - source.cy;
const sx = w / |dx|;
const sy = h / |dy|;
const s  = min(sx, sy);
return { x: source.cx + dx * s, y: source.cy + dy * s };
```

So whichever side the line "exits" first wins — left/right if the line
is mostly horizontal, top/bottom if mostly vertical.

`getEdgeSide` returns one of `Position.{Left,Right,Top,Bottom}` based on
which axis the intersection landed on:

```ts
if (|dx| * h ≥ |dy| * w) return dx > 0 ? Right : Left;
return dy > 0 ? Bottom : Top;
```

This `Position` value is used purely for cosmetic rendering (the
end-marker arrow rotation, where the kind pill is anchored). The actual
SVG path uses the intersection coordinates directly.

## Why pill-shaped nodes don't need extra math

The nodes are CSS `border-radius: 9999px` pills. Strictly speaking the
intersection should be against a stadium (rectangle + two semicircles),
but the rounded ends are short relative to the pill width (240/40 ≈ 6%
on core nodes), so AABB intersection is visually indistinguishable.

## What this fixes vs the original bug

User-reported bug from session 2:

> Some edges connect to opposite ends (e.g., top of higher node to
> bottom of lower node).

This came from the original dagre layout pinning all edges to the same
side regardless of relative position. With floating edges, an edge
between a node at (100, 100) and a node at (500, 400) leaves the right
side of the first and enters the top of the second; if the second node
is then dragged to (500, -100), the edge re-routes to leave the top of
the first and enter the bottom of the second on the very next tick.
