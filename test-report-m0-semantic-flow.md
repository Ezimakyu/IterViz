# Test Report — M0 semantic flow + hierarchy tiers + edge-label repulsion

PR: https://github.com/Ezimakyu/IterViz/pull/2 (commit `d8d55b1`)
Recording: `rec-1fccfa88-290a-4aaa-96db-2152a241243d-subtitled.mp4` (attached)

## Summary

All 6 assertions passed end-to-end. Tested by loading the small contract, switching the dropdown to the medium contract (which is where the user's earlier "squished edge label" feedback originated), then exercising one click + one drag for the regression check.

| # | Test | Result | Evidence |
|---|------|--------|----------|
| T1 | Bottom-right "node layout" selector is gone | PASS | bottom-right of the canvas region is empty; only zoom/pan controls in bottom-left |
| T2 | Variable sizing on small contract | PASS | core pills 263px wide vs child pill 175px (Δ88px, > 50px expected) |
| T3 | Semantic L→R flow on small contract | PASS | x-position order: CLI Entry Point (116) → Data Fetcher (377) → Report Writer (420) → Local Cache (701) |
| T4 | Medium-contract edge labels readable (no squish) | PASS | DOM-measured: all 12 edge label centroids fall outside every node's interior (no `insideNode` collisions) |
| T5 | Medium contract L→R + smaller child pills | PASS | Web UI is leftmost (x=228); Stripe API and Email Provider render at 95×33px vs core pills at 143×48px |
| T6 | Drag + selection boost still work (regression) | PASS | clicking Auth Service opens the top-right popup; dragging Webhook Worker re-routes its edges to the facing side in real time |

## Method

- Vite dev server: `http://localhost:5173`
- Browser: Chrome 137 at 1024×768
- Measurements taken via `document.querySelectorAll('.react-flow__node')` and `button[aria-label*="edge"]` `getBoundingClientRect()`; results logged below.

### T2 + T3 — small-contract measurements

```json
[
  {"name": "CLI Entry Point", "x": 116, "w": 263, "h": 88},
  {"name": "Data Fetcher",    "x": 377, "w": 263, "h": 88},
  {"name": "Report Writer",   "x": 420, "w": 219, "h": 79},
  {"name": "Local Cache",     "x": 701, "w": 175, "h": 61}
]
```

- Core pill widths (CLI Entry Point, Data Fetcher) = 263px.
- Child pill width (Local Cache, single-parent leaf of Data Fetcher) = 175px → Δ = 88px (≥ 50px requirement).
- L→R order matches the BFS rank: rank 0 (CLI) leftmost, rank 2 (Local Cache) rightmost.

### T4 — medium-contract label/node overlap check

```json
LABEL_OVERLAPS = [
  {"kind": "data",       "cx": 363, "cy": 287, "insideNode": null},
  {"kind": "control",    "cx": 446, "cy": 313, "insideNode": null},
  {"kind": "data",       "cx": 523, "cy": 267, "insideNode": null},
  {"kind": "data",       "cx": 503, "cy": 181, "insideNode": null},
  {"kind": "data",       "cx": 569, "cy": 238, "insideNode": null},
  {"kind": "event",      "cx": 514, "cy": 464, "insideNode": null},
  {"kind": "data",       "cx": 504, "cy": 260, "insideNode": null},
  {"kind": "event",      "cx": 608, "cy": 343, "insideNode": null},
  {"kind": "data",       "cx": 618, "cy": 272, "insideNode": null},
  {"kind": "dependency", "cx": 541, "cy": 317, "insideNode": null},
  {"kind": "data",       "cx": 585, "cy": 323, "insideNode": null},
  {"kind": "control",    "cx": 383, "cy": 373, "insideNode": null}
]
```

`insideNode === null` for every one of the 12 edge kind pills (DATA / CONTROL / EVENT / DEPENDENCY) — no label sits inside any node's bounding rectangle. The custom `labelRepel` force is doing its job.

### T5 — medium-contract layout

```json
NODES_BY_X = [
  {"name": "Web UI",         "x": 228, "w": 143},
  {"name": "REST API",       "x": 355, "w": 143},
  {"name": "Auth Service",   "x": 395, "w": 143},
  {"name": "Postgres",       "x": 508, "w": 143},
  {"name": "Email Provider", "x": 509, "w":  95},
  {"name": "Stripe API",     "x": 517, "w":  95},
  {"name": "Webhook Worker", "x": 585, "w": 143},
  {"name": "Redis Cache",    "x": 641, "w": 119}
]
```

- Web UI (entry point) is leftmost.
- Stripe API and Email Provider (both children-of-core) are 95px-wide pills, smaller than the 143px core pills.
- Children cluster near their parents: Email Provider sits below Auth Service, Stripe API sits below REST API.

## Screenshots

| Step | Screenshot |
|------|------------|
| T1 + T2 + T3 — small contract | ![](https://app.devin.ai/attachments/7e35a63f-8a20-4e2a-a14d-c3c9dfba07b9/screenshot_a870f1f1f7994f079287e9e31718928e.png) |
| T4 + T5 — medium contract after sim settles | ![](https://app.devin.ai/attachments/c97d000f-9f31-469e-be28-77fd40780585/screenshot_e118de5e5cb04d4690557cbd4040ad2d.png) |
| T6a — Auth Service popup + neighbor drift | ![](https://app.devin.ai/attachments/a2e0020f-42fa-4089-99cf-21ef560c36df/screenshot_6ed9ab2e1bcc40eb8acb831d200d8bcf.png) |
| T6b — Webhook Worker dragged to bottom-right; edges re-route to top | ![](https://app.devin.ai/attachments/734b2c4b-615a-4059-a5b0-ea24a19bff9c/screenshot_25e02de609d74955bcc0105808623c6e.png) |

## Caveats

- Pill widths reported in the medium contract (143/119/95) are smaller than the source `TIER_SIZE` (240/200/160) because the auto `fitView` zooms out to fit all 8 nodes in the viewport. Relative ratios are preserved (core > feature > child), which is what matters for the user's hierarchy requirement.
- I had to restart Vite + Chrome mid-session due to a WiFi disconnect on my side. The ~60s recording you have is the post-restart run; everything was re-verified against a fresh page load.
