# M3 Phase 1 Loop — End-to-end Test Plan

PR: https://github.com/Ezimakyu/iterviz/pull/8

## What changed (user-visible)

- Pasting a prompt into the new fullscreen `PromptInput` and clicking
  **Architect** creates a backend session and renders the contract graph.
- New `ControlBar` exposes a **Verify** button, **Iteration `n/3`**
  counter, **Coverage %** (UVDC) display, and `xE / yW` violation tally.
- `QuestionPanel` (right side) lists the Compiler's top questions with
  **Affects:** chips and per-question textareas, plus a **Submit
  Answers** button that triggers `submitAnswers` followed by
  `architect/refine` and clears the question list.
- After a refine, changed/new nodes show a yellow ring + a **NEW** badge
  in the React Flow canvas, and a small "X new · Y changed" pill appears
  at the top-right of the graph.
- The Compiler suppresses any violation whose `suggested_question` was
  already answered, so the same prompt should not reappear after the
  user has weighed in.

## Primary flow (single recording)

I will keep this to one E2E flow that exercises the entire loop.
Pre-conditions (already done in setup, NOT part of the recording): backend on
`:8000`, frontend on `:5173`, fresh DB, `ANTHROPIC_API_KEY` exported.

### Flow

1. Open `http://127.0.0.1:5173/` and confirm the fullscreen
   `PromptInput` is shown (no header/graph yet).
2. Type the canned prompt: *"Build a Slack bot that summarizes unread
   DMs daily."* — click **Architect**.
3. Iteration 0: graph appears.
4. Click **Verify** — wait for spinner to clear.
5. Read the first question; type a non-empty answer in its textarea;
   click **Submit Answers**. (Iteration 1 → 2 transition.)
6. Repeat steps 4–5 two more times. (Iteration 2 → 3 transition.)
7. Stop after the 3rd refine completes.

### Concrete assertions

Each assertion includes the exact pass/fail criterion. *Bold = the
assertion would visibly fail if the M3 wiring were broken.*

| # | Where | Expected | Pass/fail criterion |
|---|---|---|---|
| A1 | After step 1 | Fullscreen prompt visible; no `ControlBar`, no graph. | Page contains the textarea with placeholder *"Build a Slack bot that summarizes unread DMs daily."* and the only button-area copy is "Architect" / "Use sample prompt". No "Verify" button visible. |
| A2 | After step 2 | Architect runs, contract is fetched, layout switches. | "Architect" button shows "Drafting…" while loading, then disappears as the layout changes to `ControlBar` + Graph + `QuestionPanel`. ControlBar shows `Iteration 0/3`, `Coverage 0%`, `Violations 0E / 0W`. |
| A3 | After step 2 | Graph renders ≥ 4 nodes. | The React Flow canvas contains ≥ 4 distinct `data-testid="node-card-*"` elements with non-empty names from the Slack-bot domain (e.g. one of: *Slack API*, *Summarizer*, *Scheduler*, *DM Fetcher*). |
| A4 | After step 4 (1st verify) | **Compiler returns 1–5 questions and a non-trivial UVDC.** | `QuestionPanel` lists between 1 and 5 question cards (`data-testid="question-N"`) — strict ≤ 5 cap from the spec. ControlBar `Coverage` updates from `0%` to a value > 0%. `Violations` shows `≥ 1E or ≥ 1W`. |
| A5 | After step 4 | Each question shows a violation tag and at least one Affects chip. | At least one card displays `error` or `warning` and `intent_mismatch` / `invariant` / `failure_scenario` / `provenance`, and at least one Affects chip with a node name. |
| A6 | Before step 5 | Submit Answers is disabled until at least one textarea has text. | Button is greyed out (`disabled`) when all answer textareas are empty; becomes enabled after typing into one. |
| A7 | After step 5 (1st submit) | **`submitAnswers` + `refineContract` fire and the graph re-renders with diff highlighting.** | After "Refining…" clears: ControlBar `Iteration` advances to `1/3`. Graph shows the "new · changed" pill at top-right with `≥ 1` total. At least one node-card has the yellow ring (`ring-yellow-400`) or a NEW badge. `QuestionPanel` clears (no question cards visible) and reverts to the *"Click Verify to ask…"* empty state. |
| A8 | After step 5 (1st submit) | **The just-answered question does NOT reappear on the next Verify.** | After the next click of **Verify** (step 4 of iteration 2), the QuestionPanel question texts must NOT include the question I just answered. (This is the M3 "answered_questions don't reappear" guarantee — covered by `tests/test_phase1_loop.py::test_answered_questions_dont_reappear` but also needs to be visible end-to-end.) |
| A9 | After steps 4–5 ×3 | **Iteration counter shows `3/3`; UVDC ends ≥ initial.** | After the third refine, `Iteration` reads exactly `3/3`. `Coverage` after iteration 3 is greater than or equal to its value after iteration 1 (decisions don't reduce coverage). |
| A10 | Backend logs | Per-pass and per-node confidence are logged. | The backend's stdout shows three `compiler.verify_complete` log entries with `session_id` matching the active session, and the architect logs `architect.refine.complete` three times. |

### "Would this look identical if the change were broken?" check

- A1 fails if `App.tsx` doesn't conditionally render `PromptInput`.
- A2 fails if `startSession` doesn't set `sessionId` in the store.
- A3 fails if `Graph.tsx` still pulls from the static catalog instead of
  the store.
- A4 fails if `verify` thunk or `setVerificationResult` is wrong, or if
  the Compiler emits >5 questions.
- A6 fails if the submit button isn't gated on answer text.
- A7 fails if `submitAnswersAndRefine` doesn't snapshot
  `previousContract`, or if `NodeCard.tsx`'s yellow ring / NEW badge is
  not wired, or if `iteration` isn't incremented.
- A8 fails if the Compiler's "already-answered filter" regresses.
- A9 fails if `iteration` is incremented in the wrong place or UVDC is
  not updated.
- A10 fails if the backend logging was removed.

## Out of scope

- Stress / regression on M0 selection, dropdown, or contract-catalog
  behaviour (those were removed by this PR).
- Mobile / responsive layout.
- Browser back/forward and deep-link reloads.
- Auth / multi-user concurrency.

## Evidence I'll capture

- One screen recording of the whole flow (steps 1–7) with annotations
  per test (`test_start` + `assertion`).
- Backend log lines pasted into the test report (Iteration counter,
  three `compiler.verify_complete` entries, three
  `architect.refine.complete` entries).
- Final `ConfidenceReport` JSON from
  `pytest tests/test_phase1_loop.py::test_three_pass_confidence_improvement -s`.

## Known limitations

- Anthropic latency: each Architect call takes ~30–45s and each
  Compiler "live" pass is similar; the recording will pause during
  these intervals. I'll annotate them so the viewer knows we're
  waiting on the LLM, not stuck.
- If the Compiler emits 0 questions on the first Verify (because the
  Architect's contract was already clean), I will fall back to the
  pytest confidence-report evidence and explicitly mark A4–A8 as
  *inconclusive in the UI*.
