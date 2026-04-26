# M3 — Phase 1 Loop End-to-End — Implementation Details

This directory documents how Milestone **M3** was actually built. It is the
working reference for the Blind Compiler module, the three new API routes,
the live-wired frontend (Zustand + diff highlighting), the LLM-budget fixes
required for Anthropic's nonstreaming path, and the tests that lock the
loop's invariants in place.

> Source PR:
> [#8](https://github.com/Ezimakyu/IterViz/pull/8) — merged on top of M2
> (PR #3) so the Architect agent, contract persistence, and FastAPI factory
> from M2 are the canonical versions.

## What landed

| Path | Purpose |
| --- | --- |
| `backend/app/compiler.py` | `verify_contract`: deterministic invariants `INV-001..007` + optional LLM passes + ranking + 5-question cap + UVDC + already-answered suppression |
| `backend/app/api.py` *(extension)* | `POST .../compiler/verify`, `POST .../answers`, `POST .../architect/refine` — all persistence-aware |
| `backend/app/contract.py` *(extension)* | `add_decision()`, `add_verification_run()`, default-empty `decisions[]` / `verification_log[]` |
| `backend/app/schemas.py` *(extension)* | `Decision`, `VerificationRun`, `NodeConfidenceUpdate`, `ConfidenceSnapshot`, `ConfidenceSummary`, `ConfidenceReport`, plus API DTOs `CompilerResponse`, `AnswersRequest`, `RefineRequest`, `ContractResponse` |
| `backend/app/llm.py` *(extension)* | `claude-opus-4-5` defaults, `ensure_api_key()`, `max_tokens=32768`, explicit `timeout=900.0` for Anthropic |
| `backend/app/main.py` *(extension)* | `ensure_api_key()` wired into FastAPI startup |
| `backend/tests/test_compiler.py` | 19 unit tests — one per invariant, valid contract, ranking, 5-question cap, UVDC, `use_llm=False` mode |
| `backend/tests/test_phase1_loop.py` | 4 integration tests including `test_three_pass_confidence_improvement` (emits structured `ConfidenceReport` JSON) and `test_answered_questions_dont_reappear` |
| `backend/tests/test_api.py` *(extension)* | 8 new tests covering verify / answers / refine endpoints + verification-log persistence |
| `frontend/src/api/client.ts` | Typed fetch wrappers returning `ApiError` instead of throwing on 4xx/5xx |
| `frontend/src/state/contract.ts` | Zustand store with `previousContract`, `iteration`, thunks `startSession` / `verify` / `submitAnswersAndRefine` (clears stale verification artifacts on refine) |
| `frontend/src/components/PromptInput.tsx` | Fullscreen prompt → Architect button |
| `frontend/src/components/ControlBar.tsx` | Verify, Coverage %, `xE / yW`, `Iteration n/3`, Reset |
| `frontend/src/components/QuestionPanel.tsx` | ≤ 5 question cards with violation tag + Affects chips, Submit gated on non-empty answer |
| `frontend/src/components/Graph.tsx` *(extension)* | Diff highlighting — yellow ring + `NEW` badge, `X new · Y changed` pill |
| `frontend/src/components/NodeCard.tsx` *(extension)* | `isNew` / `isChanged` props applied as Tailwind ring classes |
| `frontend/src/App.tsx` *(extension)* | Conditional fullscreen `PromptInput` vs `ControlBar` + `Graph` + `QuestionPanel` layout based on session state |

## File guide in this directory

| File | What it covers |
| --- | --- |
| `01-overview.md` | High-level picture: full Phase 1 loop, data flow, design choices |
| `02-compiler.md` | INV-001..007, ranking, 5-question cap, UVDC, already-answered suppression, LLM passes |
| `03-api-and-persistence.md` | The three routes, request/response shape, `add_decision` / `add_verification_run` |
| `04-frontend.md` | API client, Zustand store, components, diff highlighting, layout |
| `05-llm-and-ops.md` | `claude-opus-4-5` defaults, `ensure_api_key()`, the max_tokens / timeout journey |
| `06-tests-and-acceptance.md` | Test layout, fixture strategy, `ConfidenceReport`, acceptance-criteria mapping |
| `07-bugs-found-and-fixed.md` | The four bugs caught during validation and how they were resolved |

## Acceptance summary

- `pytest tests/ -v` → **69 passed** (M1 + M2 + 31 new M3 tests).
- Frontend `tsc --noEmit` + `npm run lint` + `npm run build` all green.
- Live E2E run on the canned *"Build a Slack bot that summarizes unread DMs daily."* prompt completed three full Verify → Submit Answers → Refine cycles. Coverage trajectory **12% → 28% → 35%**, iteration counter ended at `3/3`, and previously-answered questions did not resurface on subsequent verifies. All 10 assertions from `test-plan.md` (A1–A10) passed.
- Backend logs show three `compiler.verify_complete` and three `architect.refine.complete` entries per session, with `uvdc_score`, `violation_count`, and `question_count` matching the values displayed in the ControlBar.

## What M3 does NOT include

- WebSocket streaming (`/api/v1/sessions/{id}/stream`) is still not wired —
  the loop is request/response.
- Editable graph (M4) and Phase-2 orchestrator (M5) are intentionally absent.
- The Compiler ranking is single-pass; no global re-prioritisation across
  iterations beyond the deterministic suppression of already-answered
  violations.
