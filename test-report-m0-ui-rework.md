# Test Report — M0 UI Rework (PR #2)

**PR**: https://github.com/Ezimakyu/IterViz/pull/2 (head `be99c35`)
**Tested on**: Chrome (Testing build) against `http://localhost:5173` (Vite dev server)
**Test plan**: `test-plan-m0-ui-rework.md`
**Session**: https://app.devin.ai/sessions/43c6cc52379e4d249c78145409f5d8bd

## Summary

Tested all 5 UI-rework requests end-to-end. Every assertion passed on its first successful dispatch; no product bugs surfaced during testing. One caveat: the test VM's VNC display has a ~0.64× scale between the screenshot coordinate space and the actual display, which made `computer act` clicks miss small targets (edge label buttons, X buttons). I fell back to dispatching the same `mousedown`/`mouseup`/`click` events through the DOM — this exercises the real React handlers (`onNodeClick`, edge button `onClick`, popup close) so the assertions are still valid, but the recording shows less natural mouse movement than I would like.

## Results

- **T1 — Compact pill rendering**: passed. Four pills with only name + colored confidence bar; no Show-details button, no inline assumption text; CLI Entry Point 85% green, Data Fetcher 70% yellow, Local Cache 45% red, Report Writer 90% green.
- **T2 — Node popup + magnetic repulsion**: passed. Click CLI Entry Point → top-right popup (INTERFACE / DRAFTED, 85% confidence, description, 3 responsibilities, 1 assumption flagged load-bearing, 1 open question, decided-by prompt). The three other pills visibly drift ~45 px leftward while the popup is open; they drift back toward the center cluster after the X closes the popup.
- **T3 — Edge popup toggle + X close**: passed. Click DATA edge between Data Fetcher and Local Cache → smaller bottom-right popup (DATA kind pill, title "Data Fetcher → Local Cache", label "store payload", payload "object with 3 fields", fields `url : string · required`, `body : string · required`, `fetched_at : string`, confidence 70%, decided-by agent). Re-clicking the same edge closes it; re-opening then clicking the X also closes it. Edge button `aria-label` flips between "click to show details" ↔ "click to hide details" as expected.
- **T4 — Floating edges on drag**: passed. Dragged Local Cache from bottom-left to upper-mid. During and after the drag the edge between Data Fetcher and Local Cache re-routes to their facing sides; no edge passes through a pill body. After release, the physics sim continues animating.
- **T5 — Medium contract + descriptive kind labels**: passed. Dropdown switch to "Medium (web app w/ auth + DB)" reseeds 8 pills in place (URL stays `/`); all renamed nodes visible (`Webhook Worker`, `Redis Cache`). Edge kind pills render `event` and `dependency` in addition to `data`/`control`. Webhook Worker popup kind badge reads "Event Handler" (not raw "job"), confidence 55% yellow, description "Background event handler that consumes Stripe webhooks asynchronously." Redis Cache popup kind badge reads "Data Store" (not raw "store"), confidence 45% red.

## Evidence (screenshots)

### T1 — small contract, compact pills

Pills show only name + colored bar; kind/status badges and Show-details button are gone.

![T1 small contract pills](https://app.devin.ai/attachments/e15d4c95-e866-4806-803c-f87dbd1821dc/screenshot_a1b1b6bc5ba74a5b81614737813b3427.png)

### T2 — node popup open, neighbors drifted

Popup anchored top-right with INTERFACE / DRAFTED badges, 85% green bar, responsibilities, assumption and open-question sections. The other three pills (Report Writer, Data Fetcher, Local Cache) have shifted visibly leftward compared to T1 — this is the boosted repulsion at work.

![T2 node popup + magnetic separation](https://app.devin.ai/attachments/073249f6-58ec-4e8b-939c-83174719b915/screenshot_3407c61edbab4df496788ceaa19565af.png)

### T3 — edge popup (smaller, bottom-right)

Smaller than the node popup. Shows the kind pill, title, label, payload summary, field list with required markers, confidence, and decided-by.

![T3 edge popup](https://app.devin.ai/attachments/6720dc36-16ae-4b67-8878-ea16cbc86502/screenshot_a15a86688d534fe6b8e2f809e35567fd.png)

### T4 — after dragging Local Cache, edges re-route

Local Cache has been moved from the lower-left position to a new spot; its edges to Data Fetcher (DATA) re-route onto the facing sides.

![T4 post-drag layout](https://app.devin.ai/attachments/0c1f3663-d861-4e37-b523-e0d05b0a0c1e/screenshot_3c0f50ffb0d14621963c035a38d300ea.png)

### T5 — medium contract, Webhook Worker popup (EVENT HANDLER)

Dropdown shows "Medium (web app w/ auth + DB)" and all 8 renamed nodes (`Webhook Worker`, `Redis Cache`, `Stripe API`, `Email Provider`, `Postgres`, `Auth Service`, `REST API`, `Web UI`) spawn in place without page reload. Popup shows "Event Handler" kind, not raw "job".

![T5 medium contract + webhook worker popup](https://app.devin.ai/attachments/82f030b0-ff85-4bdc-bfa1-c30384a1435f/screenshot_899f5cd0620d4bc9b81d65ced6f6f108.png)

### T5b — Redis Cache popup (DATA STORE)

Kind badge reads "Data Store" (not raw "store"); 45% red bar; description and responsibilities match the renamed schema.

![T5b redis cache popup](https://app.devin.ai/attachments/5a2bf7a7-af66-41c2-b577-d18ce93d7c98/screenshot_16dd1afc938a4a2bb1a193fa161eaf1c.png)

## Video

Full annotated recording of the flow (T1 → T2 → T3 → T4 → T5): https://app.devin.ai/attachments/a09a2a5c-df03-4130-8388-4990dc6eb7ee/rec-393b4f02-0108-4e41-8f84-80ad9deaa7ad-subtitled.mp4

## Caveats

- Clicks were dispatched through the DOM (real `MouseEvent` with `bubbles: true`) for edge labels, the X close button, and the dropdown because `computer act` clicks at screenshot coordinates were landing off-target due to the VNC display scaling. These dispatches go through React's native event handlers exactly like a user click, so the assertions remain valid — but the on-screen mouse cursor doesn't always move to the element being activated in the recording.
- Two "data" edge labels in the small contract render at identical coordinates (one on top of the other). This is a minor stacking issue already reflected in the current layout; not something I fixed here.
- `npm run build` and `npm run lint` both pass (0 errors, 0 warnings) — run in a previous step, not re-run as part of this test pass.
