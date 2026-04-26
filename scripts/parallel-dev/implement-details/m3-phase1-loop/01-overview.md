# 01 — Overview

## Where M3 sits in the system

M3 is the milestone that finally closes the Architect ↔ Compiler ↔ Q&A
feedback loop. Before this PR the Architect could draft a Contract
(M2) and the Compiler could rate one in isolation (M1), but there was
no end-to-end path from a user prompt to a refined Contract that
incorporates the user's answers.

```
                     POST /api/v1/sessions
                         prompt: "..."
                              │
                              ▼
                  architect.generate_contract(prompt)        (M2)
                              │ Contract v1
                              ▼
              ┌──────────────────────────────────────┐
              │ Frontend: ControlBar + Graph +       │
              │ QuestionPanel (no questions yet)     │
              └──────────────┬───────────────────────┘
                             │ click Verify
                             ▼
        POST /api/v1/sessions/{id}/compiler/verify
                             │
                             ▼
                compiler.verify_contract(contract)            (M3 new)
            ┌────────────────┴──────────────────────────────┐
            │ deterministic invariants INV-001..INV-007     │
            │ + optional LLM passes (intent/failure/proven) │
            │ + already-answered suppression                │
            │ + ranking + 5-question cap + UVDC             │
            └────────────────┬──────────────────────────────┘
                             │ CompilerOutput
                             ▼
              ┌──────────────────────────────────────┐
              │ ControlBar shows Coverage %, xE/yW   │
              │ QuestionPanel shows ≤ 5 questions    │
              └──────────────┬───────────────────────┘
                             │ user types answers, clicks Submit
                             ▼
        POST /api/v1/sessions/{id}/answers              (M3 new)
                             │ updates contract.decisions[]
                             ▼
        POST /api/v1/sessions/{id}/architect/refine     (M3 new)
                             │
                             ▼
                architect.refine_contract(contract,        (extends M2)
                                          decisions)
                             │ Contract v(N+1)
                             ▼
              ┌──────────────────────────────────────┐
              │ Frontend: previousContract snapshot, │
              │ iteration += 1, yellow ring + NEW    │
              │ badge on changed nodes, Coverage and │
              │ violations cleared                   │
              └──────────────────────────────────────┘
                             │ rinse and repeat (3× in test plan)
```

## End-to-end sequence

Each numbered step matches a user-visible event in the recorded E2E run.

1. **Initial draft.** The user pastes a prompt into the fullscreen
   `PromptInput`. `startSession` thunk hits `POST /api/v1/sessions`, the
   Architect produces Contract v1, and the layout swaps to ControlBar +
   Graph + QuestionPanel. ControlBar reads `Iteration 0/3`, `Coverage 0%`,
   `Violations 0E / 0W`.
2. **Verify (pass 1).** `verify` thunk hits `POST .../compiler/verify`.
   The Compiler runs the seven deterministic invariants, then (when an
   API key is present) the three LLM passes; ranks violations; caps to
   five questions; computes UVDC. Backend persists a `VerificationRun`
   on `contract.verification_log[]` and returns `CompilerResponse`. The
   ControlBar updates Coverage and `xE / yW`; the QuestionPanel renders
   the question cards.
3. **Answer + refine.** The user types into one or more textareas (the
   Submit button stays disabled until at least one is non-empty) and
   clicks **Submit Answers**. The frontend's `submitAnswersAndRefine`
   thunk fires `POST .../answers` followed by `POST .../architect/refine`.
   On success it:
   - snapshots the current contract into `previousContract` (for diff),
   - sets the new contract returned by the refine endpoint,
   - clears `violations`, `questions`, and `uvdcScore` (they were
     computed against the old contract and are stale),
   - bumps `iteration` by 1.
4. **Diff render.** `Graph.tsx` compares `contract` to `previousContract`
   and tags nodes/edges as `isNew` or `isChanged`. `NodeCard.tsx`
   applies a `ring-yellow-400` Tailwind class for changed nodes and a
   small `NEW` badge for nodes that did not exist in the previous
   contract. A summary pill (`X new · Y changed`) sits at the
   top-right of the graph.
5. **Loop.** Steps 2–4 repeat; the test plan locks in **exactly 3
   cycles** so the iteration counter ends at `3/3`. Compiler enforces
   that any violation whose `suggested_question` matches an
   already-answered `Decision` is dropped, so the user never sees the
   same question twice across iterations (`test_answered_questions_dont_reappear`).

## Key design choices

- **Deterministic invariants first.** The seven `INV-*` checks run as
  pure Python before any LLM is involved. This gives M3 a sane fallback
  when `ANTHROPIC_API_KEY` is unset (CI, smoke tests) and means the
  unit tests do not need network access. The LLM passes layer
  semantic checks on top — they cannot remove deterministic violations.
- **One LLM seam, again.** The Compiler reuses M1's
  `app.llm.call_compiler()` and only that. Tests monkeypatch
  `_call_llm_passes` (in `compiler.py`) so no provider SDK is touched.
- **Already-answered suppression is universal.** Both deterministic
  and LLM-emitted violations are filtered through `_already_answered`
  before merging. A regression here would let the same OAuth or
  retry-policy question reappear in every Verify, which is the
  smoke-test failure of M3.
- **Refine clears verification artifacts.** Coverage, violations, and
  questions live on the *previous* contract. Leaving them in the store
  after a refine produces stale UI numbers; the thunk clears all three
  in one `set()` call.
- **Iteration counter is store-side only.** The backend persists
  `VerificationRun`s and `Decision`s but does not maintain a "phase 1
  iteration" counter — the frontend owns it. This keeps the API
  stateless w.r.t. UI semantics.
- **Diff is computed on the fly.** No separate diff payload from the
  backend; `Graph.tsx` derives `isNew`/`isChanged` per render from the
  two contract snapshots in the store. This is cheap (≤ 10 nodes in
  practice) and avoids API churn.
- **Strict 5-question cap.** Documented in SPEC.md and enforced both by
  ranking output truncation and by `test_max_five_questions`. No matter
  how many violations the LLM produces, the panel never shows a sixth
  card.

## What M3 does NOT include

- The Compiler is **not** automatically run on session creation —
  the user must click Verify. This is intentional so the panel does
  not flash a wall of questions on first paint.
- There is no streaming/WebSocket variant; the loop is plain
  request/response. Each Architect / Compiler call is 30–180 s on
  Claude Opus 4.5, so the loading buttons (`Drafting…`, `Verifying…`,
  `Refining…`) stay disabled for the duration.
- The Compiler does **not** mutate the contract directly. Suggestions
  flow back as `Question` records inside `CompilerOutput`; only the
  Architect (via refine) is allowed to write a new contract version.
