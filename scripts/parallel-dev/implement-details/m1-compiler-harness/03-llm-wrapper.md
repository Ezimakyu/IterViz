# 03 — LLM wrapper (`backend/app/llm.py`)

A 160-line module that does exactly four things:

1. Resolves which provider to use.
2. Resolves which model to use.
3. Builds an `instructor`-patched chat client.
4. Calls it with `temperature=0`, `response_model=CompilerOutput`, and
   the system prompt loaded from `app/prompts/compiler.md`.

It is intentionally minimal — no retry policies beyond what `instructor`
provides, no caching, no token accounting. M2's orchestrator can layer
those on without rewriting this file.

## Provider resolution

In priority order:

1. Explicit `provider="openai" | "anthropic"` argument to `call_compiler`.
2. `GLASSHOUSE_LLM_PROVIDER` environment variable.
3. `OPENAI_API_KEY` is set → `openai`.
4. `ANTHROPIC_API_KEY` is set → `anthropic`.
5. Otherwise raise a `RuntimeError` with a useful message.

If both API keys are present, OpenAI wins by default; set
`GLASSHOUSE_LLM_PROVIDER=anthropic` to switch.

## Model resolution

```python
DEFAULT_MODELS = {
    "openai":    "gpt-4o",
    "anthropic": "claude-opus-4-5",
}
```

Override via `GLASSHOUSE_COMPILER_MODEL`. The bare alias
`claude-opus-4-5` resolves to `claude-opus-4-5-20251101` through
Anthropic's SDK; `instructor` handles that translation internally.

`gpt-4o-mini` was the original OpenAI default until the eval showed it
fails the precision target on this corpus. Bumping to `gpt-4o` was the
smallest functional change to clear M1.

## Why `instructor`?

We deliberately avoid hand-parsing JSON from raw chat completions:

- `instructor` enforces our `CompilerOutput` model on the structured-
  output side of the SDK (OpenAI's `response_format` / Anthropic's
  function-calling tool).
- `extra="forbid"` on `CompilerOutput` then rejects any stowaway field.
- A schema validation failure (verdict↔severity mismatch, > 5 questions,
  bad enum value) propagates as a normal `ValidationError`, which
  `instructor` surfaces and retries up to `max_retries` (default 2).

The net effect: `call_compiler(contract)` either returns a valid
`CompilerOutput` or raises. There is no "ambiguous" return.

## Anthropic-specific quirk

Anthropic's SDK requires `max_tokens` on every call. We hard-code 4096
in the kwargs only when `provider == "anthropic"`. OpenAI does not
require this and we don't pass it there.

## Logging

The wrapper emits two structured records per call:

- `DEBUG`: `compiler call started` with provider, model, contract id,
  node/edge counts.
- `INFO`: `compiler call completed` with duration_ms, verdict,
  violation_count, question_count.

These records are durable across runs and reproducible from the eval
harness output (`scripts/eval_compiler.py`) — useful for diffing
behaviour after a prompt edit.

## What the wrapper does NOT do

- No streaming. The Compiler is a single-shot verifier; streaming the
  output would complicate validation without buying anything.
- No tool use beyond `instructor`'s structured-output bridge. The
  Compiler reads the contract, period.
- No persistence. Logging the verdict back into
  `contract.verification_log` is the orchestrator's job (M2/M3).
- No fallback between providers. If `openai` fails, we don't silently
  retry on `anthropic`; that masks the real failure mode and would skew
  the eval metrics.
