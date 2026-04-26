# 07 — Bugs found and fixed during validation

The first pass of M3 was code-complete in one feature commit
(`be770d2`). Live validation against Claude Opus 4.5 — and Devin
Review running over the diff — surfaced four bugs, all of which were
fixed before the PR was merged. They are documented here as the
post-mortem so the next milestone can avoid the same traps.

## Bug 1 — Stale verification artifacts after refine

**Commit:** `509c561` — `fix(m3): clear stale violations + uvdcScore on refine`.

**Symptom:** after Submit Answers + refine, the ControlBar still
displayed the old Coverage % and the `xE / yW` violation tally from
*before* the refine. Clicking Verify again reset them, but the
intermediate state was misleading.

**Root cause:** `submitAnswersAndRefine` cleared `questions` (so the
QuestionPanel emptied correctly) but forgot to clear `violations`
and `uvdcScore`. Both numbers were computed against the *previous*
contract and were therefore stale.

**Fix:** the thunk now does:

```typescript
set((s) => ({
  previousContract: s.contract,
  contract: refined.contract,
  violations: [],
  questions: [],
  uvdcScore: 0,
  iteration: s.iteration + 1,
  isLoading: false,
  error: null,
}));
```

Caught by Devin Review code review.

## Bug 2 — LLM violations bypassed `_already_answered`

**Commit:** `4dbac4f` — `fix(m3): also filter LLM extra_violations through _already_answered`.

**Symptom:** A question the user had already answered in pass 1 could
re-appear in pass 2. The deterministic provenance/invariant filter
was stripping the duplicate, but the LLM was free to re-raise the
same suggestion through `extra_violations`, and that path skipped
the filter.

**Root cause:** the suppression logic used to be:

```python
invariant_violations  = [v for v in invariant_violations  if not _already_answered(v)]
failure_violations    = [v for v in failure_violations    if not _already_answered(v)]
provenance_violations = [v for v in provenance_violations if not _already_answered(v)]

extra_violations = []
if use_llm:
    extra_violations, ... = _call_llm_passes(contract)

all_violations = (
    invariant_violations + failure_violations
    + provenance_violations + extra_violations  # NOT filtered
)
```

**Fix:** apply the same filter to `extra_violations` *after* the LLM
call returns:

```python
extra_violations = [v for v in extra_violations if not _already_answered(v)]
```

Locked in by `test_answered_questions_dont_reappear` in
`tests/test_phase1_loop.py`. Caught by Devin Review.

## Bug 3 — `IncompleteOutputException` on refine #2 / #3

**Commits:** `1be0bc4` (`max_tokens=16384`) → `a717efd`
(`max_tokens=32768`).

**Symptom:** the second refine in the live E2E test returned an
`IncompleteOutputException` from `instructor`. The Anthropic
response had been truncated mid-JSON because the Architect's
Contract had grown — by the third pass the `decisions[]` array,
expanded assumptions, and explicit payload schemas pushed the JSON
well past 8192 tokens.

**Root cause:** M2 set `max_tokens=8192` for the Architect because
fresh contracts fit comfortably. Refining a contract three times
with full payload schemas does not.

**Fix:** raise `max_tokens` in `call_compiler()` and
`call_structured()` to **32768** for Anthropic. Documented in
`05-llm-and-ops.md`.

## Bug 4 — `Streaming is required` after `max_tokens=32768`

**Commit:** `410fcaf` — `fix(m3): pass explicit timeout to bypass anthropic streaming check`.

**Symptom:** with `max_tokens=32768`, the Anthropic SDK refused the
request with:

```
Streaming is required for operations that may take longer than 10 minutes
```

even though responses were arriving in ~55 s.

**Root cause:** the SDK's `_calculate_nonstreaming_timeout()` makes a
worst-case estimate of how long the request *could* take based on
`max_tokens`. With a large budget and no explicit `timeout`, that
estimate exceeds the SDK's hard 10-minute guard and the SDK rejects
the request before sending it.

**Fix:** pass `timeout=900.0` (15 minutes) explicitly. The SDK takes
this as the binding upper bound and skips its own estimator. Curl
sanity test confirmed: full 6-node Contract JSON in ~55 s, no
errors, full text returned.

## Lessons recorded

- LLM-emitted artifacts (`extra_violations`, future suggestions,
  etc.) must always flow through the same filters as deterministic
  artifacts. An LLM is not a privileged source.
- Frontend state derived from a contract version (Coverage,
  violations, questions) must be cleared whenever the contract
  changes, even if the change came from inside the same thunk.
- Anthropic's nonstreaming path requires both a generous
  `max_tokens` *and* an explicit `timeout` to handle long structured
  responses. M3's defaults — `max_tokens=32768`, `timeout=900.0` —
  should travel with any future agent that returns full Contracts.
- Live validation finds bugs that unit tests miss. The first three
  bugs were caught either by Devin Review or by the live E2E
  recording, not by `pytest`. Both layers are needed.
