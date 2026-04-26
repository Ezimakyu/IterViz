# 05 — UI: Pills, Popups, Dropdown

The original M0 had verbose node cards that expanded inline. The first
round of UX feedback rewrote the node renderer entirely.

## NodeCard (pill)

`src/components/NodeCard.tsx`. Shows only:

- Component name (centered, bold).
- Confidence bar (red <0.5, yellow 0.5–0.8, green >0.8).

The pill outline is colour-coded by node `kind` (a thin ring). All other
detail (description, responsibilities, assumptions, open questions)
moved to the popup.

Width and height come from the tier:

```tsx
const size = TIER_SIZE[tier];
<div style={{ width: size.width, height: size.height }}
     className="rounded-full border-2 ..."
```

No expandable inline content, no "Show details" link.

## Node popup (top-right)

`src/components/NodeDetailsPopup.tsx`. Triggered by clicking a node.

- Fixed position top-right, ~480px wide, `max-h-[70vh]`, internal
  scroll.
- Close `×` button in the header.
- Click another node → store toggles; popup re-renders for the new
  node. Click the same node → popup closes.
- Layout is intentionally an **overlay** — popups can occlude the graph
  underneath, which is fine because the user wanted the spotlighted
  detail.

While a node is selected:

- `Graph.tsx` passes `selectedNodeId` to `useForceLayout` as
  `boostedId`.
- The charge force returns `BOOST_CHARGE = -2800` for that node.
- The selection effect bumps `sim.alpha()` to 0.6.
- Neighbours visibly drift outward from the selected node by ~40–50px
  while the popup is open, then drift back when it closes.

## Edge popup (bottom-right)

`src/components/EdgeDetailsPopup.tsx`. Triggered by clicking an edge's
kind pill. Smaller than the node popup (~360px), bottom-right.

Shows:

- Source → Target name pair.
- Kind badge (DATA / CONTROL / EVENT / DEPENDENCY).
- Optional label.
- Payload schema fields (one row per top-level key with type).

Toggle behaviour: clicking the same edge again closes it; clicking the
`×` closes it; clicking a different edge swaps to that one.

## EdgeLabel (the kind pill)

`src/components/EdgeLabel.tsx` renders the floating SVG path AND a
small `<button>` at the path midpoint with the kind text. The button is
the click target for opening the edge popup.

The button uses `aria-label="<kind> edge, click to show details"` so
screen readers announce the relationship. The DOM tests in
`08-testing.md` rely on these aria labels.

## Dropdown

`src/App.tsx` owns a simple `<select>` with the two contract files:

```tsx
<select value={active} onChange={e => setActive(e.target.value)}>
  <option value="small">Small (CLI tool)</option>
  <option value="medium">Medium (web app w/ auth + DB)</option>
</select>
```

Switching contracts re-runs the fetch, replaces the contract in the
Zustand store, and the `useEffect` in `useForceLayout` keyed on the new
contract reseeds the simulation. The URL stays `/`; React Flow doesn't
unmount, so the canvas reuses its existing zoom/pan state.

## Removed: MiniMap selector

The original M0 included React Flow's MiniMap in the bottom-right.
After the semantic-flow round, the user asked to remove the "node
layout" selector — turned out to be the MiniMap. Removed in favour of
just `<Controls position="bottom-left" showInteractive={false} />`.
