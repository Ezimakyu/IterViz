# Test Plan — M0 spacing adjustments

Commit under test: `c7efaa0` — PR: https://github.com/Ezimakyu/IterViz/pull/2

## What changed (user-visible)

1. `RANK_SPACING` 260 → **360** — each L→R rank column sits ~38% further from its neighbour, so the whole graph is visibly wider with more breathing room between source and target columns.
2. `LABEL_CLEARANCE` 72 → **110** — the existing per-edge-midpoint repulsion now pushes non-adjacent nodes ~50% further away, so node labels never crowd an edge label.
3. **NEW label↔label repulsion** — when two edge midpoints get within 90px of each other, the simulation nudges their endpoint nodes apart so the kind pills (DATA/CONTROL/EVENT/DEPENDENCY) separate. Edges that share an endpoint are exempt.
4. `LINK_DISTANCE` / `CHILD_LINK_DISTANCE` bumped 240→280 / 130→150 so the link force doesn't fight the wider columns.

## Primary flow

Reload `http://localhost:5173`, observe the small contract briefly, then switch to the medium contract (where the spacing complaints originated) and let the sim settle ~5s.

## Key assertions

| # | Assertion | Concrete pass criterion | How a broken impl would differ |
|---|-----------|------------------------|--------------------------------|
| S1 | **Wider L→R columns on medium contract** | After fitView settles, `Web UI` (rank 0) → `Redis Cache`/`Webhook Worker` (rank 2) X-delta is ≥ 530px in screen space (was 413px in the previous run; +28% from 360/260 spacing minus fitView shrink). | Broken: X-delta ≤ 430px → spacing didn't take effect. |
| S2 | **Every edge label clears every non-adjacent node by ≥ 14px** | DOM check: for each of the 12 medium-contract edge label centroids, distance to the nearest non-adjacent node's bounding rect is ≥ 14px (in screen pixels, after fitView shrink of `LABEL_CLEARANCE=110` ≈ ~50px world). | Broken: at least one label sits inside a non-adjacent node or within 5px of its border. |
| S3 | **Every pair of non-adjacent edge labels is ≥ 28px apart** | DOM check: for the 12 edge label centroids, the min pairwise distance among non-adjacent pairs is ≥ 28px (post-fitView screen-space equivalent of the 90px world-space `LABEL_LABEL_CLEARANCE`). | Broken: two label pills overlap or touch. |
| S4 | **Small contract still renders cleanly (regression)** | Small contract: 4 pills visible, `CLI Entry Point` leftmost, `Local Cache` rightmost; X-delta CLI→Cache ≥ 600px (previously 585px @ 260 spacing). | Broken: small contract layout regressed (overlaps, wrong order, or shrank). |

## Scope

~30s recording on a fresh page load: small contract glance → switch to medium → DOM measurements via console → done. No interaction (drag/click) — that was already verified last round.

No setup steps; dev server and browser are already up.
