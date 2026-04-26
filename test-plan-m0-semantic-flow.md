# Test Plan — M0 semantic flow + hierarchy tiers + edge-label repulsion

Commit under test: `d8d55b1`  — PR: https://github.com/Ezimakyu/IterViz/pull/2

## What changed (user-visible)

1. The "node layout" selector in the bottom-right corner (MiniMap) is removed — bottom-right of the canvas should no longer contain any panel.
2. Nodes are now sized by hierarchy tier instead of a single fixed size:
   - **Core** (graph hubs, entry points, ≥3 degree or ≥2 out): 240×80 pill, larger text, ring-[3px]
   - **Feature** (moderate role): 200×72 pill, standard text, ring-2
   - **Child** (single-parent leaf of a core): 160×56 pill, smaller text, ring-1
   - **Orphan** (disconnected): 160×56 pill, smaller text, ring-1
3. Layout is semantic: entry points (0 in-degree) pinned to the leftmost column, downstream nodes to the right (BFS rank × 260px column spacing via `forceX`). Children of a core node pull toward that parent's Y via a custom "snowflake" force.
4. Repulsion is tier-graduated (`TIER_CHARGE`): core=-1800, feature=-1050, child=-260, orphan=-1400. Core nodes push other core nodes away strongly; children stay close to their parent.
5. A custom `labelRepel` force makes every edge midpoint push non-adjacent nodes away with `LABEL_CLEARANCE=72px` min radius — edge kind pills (`DATA`, `CONTROL`, `EVENT`, `DEPENDENCY`) should never get squished between two nodes.

## Primary flow

Load `http://localhost:5173`. Observe the initial small contract, then switch the dropdown to the medium contract (which is where the "squished edge label" regression showed in the user's feedback image).

## Key assertions

| # | Assertion | Expected (concrete) | How a broken impl would differ |
|---|-----------|---------------------|--------------------------------|
| T1 | **No bottom-right panel** | On initial load, the bottom-right ~240×180px region of the canvas contains no rendered panel (no MiniMap, no layout-selector). The only RF controls are the zoom/pan buttons on the bottom-LEFT. | Broken: a minimap (miniature graph) or selector is visible in the bottom-right. |
| T2 | **Variable sizing on small contract** | `CLI Entry Point` and `Data Fetcher` (both core) are visibly larger pills than `Local Cache` (child of Data Fetcher). Measure: core pill width ≈ 240px vs child ≈ 160px — a ≥50px width delta. | Broken: all 4 pills are the same size. |
| T3 | **Semantic L→R flow on small contract** | `CLI Entry Point` (rank 0, entry) is the leftmost node on screen. `Local Cache` (rank 2) is the rightmost node. `Data Fetcher` and `Report Writer` (rank 1) sit in between. X-position order: CLI < Data Fetcher/Report Writer < Local Cache. | Broken: nodes are in some other order (e.g., Local Cache leftmost, or random). |
| T4 | **Medium contract edge labels readable** | Switch dropdown to "Medium (web app w/ auth + DB)". After the sim settles (~3s), every edge kind pill (`DATA`, `CONTROL`, `EVENT`, `DEPENDENCY`) is visible with no pill being fully covered by or sandwiched inside a node rectangle. No edge label overlaps a node pill's interior. | Broken (the regression from user's screenshot): at least one edge label is squished between two node pills. |
| T5 | **Medium contract L→R + children near parent** | `Web UI` (entry, rank 0) is the leftmost node. `Postgres`/`Redis Cache`/`Webhook Worker`/`Email Provider`/`Stripe API` (rank 2) are the rightmost cluster. `Stripe API` (child of `REST API`) and `Email Provider` (child of `Auth Service`) are smaller pills than the core nodes. | Broken: Web UI ends up in the middle or right, or rank-2 nodes land to the left of rank-1 nodes. |
| T6 | **Drag + selection boost still work (regression)** | Click a node → top-right popup opens; neighbors visibly drift outward (boosted repulsion). Drag a node → edges re-route to facing sides in real time. Click the X or background → popup closes. | Broken: the popup doesn't appear, neighbors don't move, or edges don't re-route after drag. |

## Scope

Recording covers small → medium switch + one selection/drag interaction. ~60s video.

No setup steps: dev server already running at `http://localhost:5173`, browser already pointed at it.
