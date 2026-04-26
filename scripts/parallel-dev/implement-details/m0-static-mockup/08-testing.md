# 08 — Testing & Verification

Every round shipped with a recorded end-to-end test. The patterns below
are reusable for future graph milestones (M3+).

## Recording shape

Each test plan is a Markdown file at the repo root:
`test-plan-m0*.md`. Each one declares:

- A primary flow (≤5 user actions).
- 4–6 named assertions in `It should ...` format.
- DOM measurements where pixel-perfect numbers matter.

Tests run via `enter_test_mode` → `recording_start` → annotated
interactions → `recording_stop`. Annotations use `test_start` and
`assertion` types so the recording slows down at decision points.

## DOM measurement patterns

### Pill width / overflow check

```js
const canvas = document.querySelector('.react-flow').getBoundingClientRect();
const nodes = [...document.querySelectorAll('.react-flow__node')].map(n => {
  const r = n.getBoundingClientRect();
  return {
    name: n.querySelector('h3')?.textContent,
    w: Math.round(r.width),
    offscreen: r.right < canvas.left || r.left > canvas.right,
  };
});
```

Used for assertion P1 (pills at full TIER_SIZE) and to count how many
nodes overflow the viewport.

### Label-to-node clearance

For every edge kind pill, compute the minimum point-to-AABB distance
to every node:

```js
function pointToBoxDist(px, py, box) {
  const dx = Math.max(box.l - px, 0, px - box.r);
  const dy = Math.max(box.t - py, 0, py - box.b);
  return Math.hypot(dx, dy);
}
```

Used to verify `labelRepel` is doing its job. Threshold: 18px.

### Label-to-label clearance

Pairwise centroid distances between every two edge labels. Threshold:
30px. Used to verify `labelLabelRepel` is doing its job.

### Drag verification

Read node center before drag, drive `left_click_drag(start, end)`,
read node center after, confirm direction is correct. Edge re-route
is verified visually in the recording (the SVG path's `d` attribute
is awkward to compare; the screenshot is the easier evidence).

## Aria labels as test selectors

Every kind pill button has:

```html
<button aria-label="data edge, click to show details">data</button>
```

This is the most reliable selector for edge-related assertions —
querying by `aria-label*="edge"` returns exactly the 12 (or 5)
kind-pill buttons regardless of which side of which node they're
floating on.

## Caveats from the recording environment

These came up repeatedly and should be expected on any future
recording:

- **Synthetic xdotool drag emits multiple intermediate move events**,
  so a 300px cursor delta can produce a ~470px pan or ~232px node
  move. The direction is always correct; the magnitude is amplified.
  Don't assert on exact pixel deltas — only on direction and a lower
  bound.
- **CSS `:hover` doesn't reliably trigger from xdotool cursor
  movement** in headless display capture. For hover-only UI (e.g.,
  the original tooltip) fall back to dispatching `MouseEvent`
  directly. We avoided this in the final design by making everything
  click-driven.
- **The VNC display had a ~0.64× scale mismatch** between screenshot
  pixels and click-coordinate pixels in some sessions. When this
  happens, prefer DOM event dispatch over physical clicks for
  assertions, then take a real screenshot for the visual record.

## What was NOT tested at the unit level

There are no Jest/Vitest unit tests in `frontend/` yet. The whole
M0 surface is verified through DOM-measured end-to-end tests because
the interesting behaviour (physics layout, side picking, label
clearance) emerges from interaction between the simulation and the
DOM and is much easier to assert against the rendered output than
against the pure functions in isolation.

A future M3+ milestone with editable graphs would benefit from unit
tests on `buildHierarchy` and `getEdgeParams` since both are pure.
