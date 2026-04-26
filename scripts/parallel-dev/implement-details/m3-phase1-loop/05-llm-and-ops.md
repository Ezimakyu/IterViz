# 05 — LLM wrapper + operational fixes

M3 made the LLM layer "live" — every Architect generate / refine and
every Compiler verify pass that uses LLM calls hits Anthropic in
production. That immediately exposed three operational issues that
M1 and M2 had not — `claude-opus-4-5`'s much larger output budget,
the SDK's nonstreaming-duration check, and the need to handle missing
API keys gracefully at startup.

## Defaults (`backend/app/llm.py`)

```python
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL    = "claude-opus-4-5"
DEFAULT_MODELS   = { "anthropic": DEFAULT_MODEL, "openai": "gpt-4o-mini" }
```

`_resolve_provider()` picks the provider in this order:

1. explicit `provider=...` keyword arg,
2. `GLASSHOUSE_LLM_PROVIDER` env var,
3. `ANTHROPIC_API_KEY` ⇒ `anthropic`,
4. `OPENAI_API_KEY` ⇒ `openai`,
5. else `RuntimeError`.

This means a developer who only has `ANTHROPIC_API_KEY` set gets the
M3 defaults out of the box; tests that don't set either env var get
a deterministic-only mode (used heavily in `test_compiler.py`).

## `ensure_api_key(provider=None)`

Wired into FastAPI startup (`backend/app/main.py`). Behaviour:

- If `ANTHROPIC_API_KEY` is set, return it (no-op fast path).
- Else, if running in an interactive TTY, print a banner with the
  Anthropic key URL and prompt via `getpass` for the key. Optionally
  appends to `backend/.env` if the user types `y`.
- Else (CI, FastAPI workers, non-interactive), raise `RuntimeError`
  so the caller (`api.py`) can surface it as a `503 Service
  Unavailable` instead of crashing the worker.

The non-interactive branch is critical: without it, an `input()` call
inside FastAPI's startup hook would block the process forever. The
test suite verifies the fail-fast behaviour by running with no env
var set.

## `max_tokens` and `timeout` — the journey

Both `call_compiler()` and `call_structured()` now pass two
Anthropic-specific kwargs:

```python
common_kwargs["max_tokens"] = 32768
common_kwargs["timeout"]    = 900.0
```

This was reached after four iterations during live validation.

| Step | Setting | Why it changed |
| --- | --- | --- |
| Initial | `max_tokens=4096` | M1's value, fine for short Compiler responses. |
| Architect first refine | `max_tokens=8192` | Architect Contract JSON is bigger than a CompilerOutput; M2 set this. |
| Refine #2 (live test) | `IncompleteOutputException` | Full Contract JSON with 6 nodes + payload schemas + decisions[] exceeded 8192. Bumped to 16384 (`1be0bc4`). |
| Refine #3 (live test) | `IncompleteOutputException` again | Same reason after a third refine. Bumped to 32768 (`a717efd`). |
| With max_tokens=32768 | `Streaming is required for operations that may take longer than 10 minutes` | Anthropic SDK's `_calculate_nonstreaming_timeout()` rejects large `max_tokens` unless an explicit `timeout` is passed. Added `timeout=900.0` (`410fcaf`). |

`call_structured()`'s function signature exposes both as defaultable
parameters (`max_tokens=32768`, `timeout=900.0`) so future callers
can tighten the budget if they know they're producing smaller
responses, but the defaults are sized for the worst case (a 6-node
Contract refined three times).

## What's NOT in this change

- We do **not** stream responses. Streaming would change the
  programming model substantially (instructor's structured-output
  retry loop assumes a buffered response) and is unnecessary at
  Phase-1 scale where each call is a single discrete refinement.
- We do **not** have token-budget telemetry beyond the existing
  `duration_ms` log entries. Adding `tokens_used` would require
  pulling it from the Anthropic SDK response object — an easy
  follow-up but not needed for M3.
- We do **not** rate-limit on the server. The frontend's
  Verify/Submit buttons are gated on `isLoading`, which is sufficient
  for the single-user demo flow.

## Recap of the four ops bugs

These are detailed in `07-bugs-found-and-fixed.md`. Two of them
involved this file:

- `IncompleteOutputException` on refine #2 → `max_tokens=16384`
  (`1be0bc4`).
- `Streaming is required` after `max_tokens=32768` → `timeout=900.0`
  (`410fcaf`). Curl sanity test confirmed: full Contract JSON in
  ~55 s, no error.
