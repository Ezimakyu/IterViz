# 06 — Viewport: Native Zoom + Pan-on-Drag

This is the final iteration's headline change. It came from a
specific user suggestion:

> at default window size, not everything in the graph has to fit, and
> then we can just left click + drag around to move to other sections
> of the graph

Before this round, every contract switch and every sim cool-down
triggered `fitView({ padding: 0.25 })`. That worked for the small
contract but compressed the medium contract to roughly 0.5× zoom,
which negated all the spacing constants in world space — a 110px
clearance became a 55px clearance, labels overlapped nodes again.

## What changed

Two changes in `Graph.tsx`:

```diff
- fitView
- fitViewOptions={{ padding: 0.3 }}
+ defaultViewport={{ x: 200, y: 360, zoom: 1 }}
+ panOnDrag                 // explicit
```

One change in `useForceLayout.ts` — removed the auto-fit on cool:

```diff
- let refitted = false;
  sim.on("tick", () => {
    ...
-   if (!refitted && sim.alpha() < 0.1) {
-     refitted = true;
-     requestAnimationFrame(() => fitView({ padding: 0.25, duration: 400 }));
-   }
  });
```

`useReactFlow().fitView` is no longer destructured anywhere.

## Initial viewport math

The simulation seeds nodes around world (0, 0) with each rank-column
offset by `targetX = rank * RANK_SPACING - spanX / 2`. For the small
contract (`maxRank = 2`, `RANK_SPACING = 480`):

```
spanX = 2 * 480 = 960
rank 0 (CLI Entry Point) → targetX = -480
rank 1 (Data Fetcher)    → targetX = 0
rank 2 (Local Cache)     → targetX = 480
```

`defaultViewport={{ x: 200, y: 360, zoom: 1 }}` translates the world by
(+200, +360) before painting. So:

```
Screen X of CLI Entry Point center ≈ -480 + 200 = -280   (off-screen left)
Screen X of Data Fetcher center    ≈    0 + 200 =  200   (visible)
Screen X of Local Cache center     ≈  480 + 200 =  680   (visible)
```

`y = 360` puts the horizontally-centered vertical lane near the middle
of a typical canvas.

So at startup the user sees Data Fetcher and Local Cache on the right
half of the screen, with the rest of the graph available by panning
left. This is intentional — the user can immediately drag to expose
any off-screen content.

## Pan vs node-drag

ReactFlow has `panOnDrag` and `nodesDraggable`. Both are enabled. The
priority is decided by the cursor target:

- Click on canvas background → pan starts.
- Click on a node body → node drag starts (and `useForceLayout`'s
  tick handler pins that node via `fx`/`fy` until release).

The two never conflict because RF dispatches based on `event.target`.

## Caveats verified during testing

- The synthetic `xdotool` drag emits multiple intermediate move events,
  so the test recording shows ~1.5× the cursor delta as pan distance.
  A real human cursor pans 1:1.
- The canvas keeps RF's internal zoom in `[0.2, 1.8]`, so the user can
  still mouse-wheel zoom out for a bird's-eye view if they want. The
  initial viewport just no longer zooms automatically.
