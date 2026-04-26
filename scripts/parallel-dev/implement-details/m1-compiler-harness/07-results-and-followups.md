# 07 — Results, false positives, and M2 hand-off

## Final three-model matrix

| Model | Recall | Precision | Per-contract pass | Notes |
|---|---|---|---|---|
| `gpt-4o-mini` | 72.73% | 61.54% | 5/8 | **Fails** SPEC targets — kept as a regression "floor". |
| `gpt-4o` | 100% | 91.67% | 7/8 | Meets SPEC; one false positive on `intent_mismatch.json`. |
| **`claude-opus-4-5`** | **100%** | **100%** | **8/8** | Demo target. Clean sweep. |

`pytest tests/test_schemas.py` → 16/16 on every run.
`python scripts/eval_compiler.py --no-llm` → 8/8 fixtures parse cleanly.

## Where each model fails

### `gpt-4o-mini`

Mini's main failure mode is **fabricated connectivity claims**. Even
with the explicit "scan the entire `edges[]` array" instruction in the
prompt, it sometimes asserts that nodes are orphaned when they are
plainly connected. Adding more guardrails to the prompt didn't move
its precision past ~62%, and at that point we were tuning *for* mini
at the cost of clarity for stronger models. The decision was to bump
the OpenAI default to `gpt-4o`.

### `gpt-4o`

Catches every seeded violation but emits one spurious INV-003
(`user_input_terminates`) on `intent_mismatch.json`, claiming `n-form`
doesn't reach a store/external. It does — transitively, via
`n-form → n-router → n-pg`. The transitive-reachability instruction
in the prompt is followed correctly on every other fixture; the
plausible cause is that the model is "anchoring" on the headline
intent_mismatch finding and over-flagging adjacent structure.

This is one false positive across 12 emitted violations on this
contract, hence the 91.67% precision aggregate. M1 targets are still
met; this is a candidate for follow-up tuning if we want a clean
8/8 with `gpt-4o`.

### `claude-opus-4-5`

Zero failures on this corpus. The output is also notably more
disciplined about questions — Opus 4.5 routinely produces fewer
questions than the budget allows when the corresponding violations
are clear, which matches the "silently defer beyond budget" prompt
guidance.

## Concrete wins from prompt iteration

These are the deltas that produced the largest measurable improvements
during eval iteration, in order of impact:

1. **Connectivity verification block** (Pass 2 preamble). Halved
   `gpt-4o-mini`'s INV-001/INV-002/INV-003 false positives. Helps every
   model.
2. **Trust-boundary check** (Pass 3 preamble). Eliminated
   `failure_scenario` violations on internal edges. Without this, all
   models over-fired here.
3. **"What is NOT an intent_mismatch"** (Pass 1). Stopped models from
   conflating structural defects (cycles, missing schemas) with
   purpose mismatch. `gpt-4o`'s precision moved up to 91.67% after
   this addition.
4. **Final self-check** (end of prompt). Cheap (no extra LLM call —
   same generation) but consistently dropped FP counts on borderline
   cases.

## Remaining false positives / open issues

Single known remaining FP on `gpt-4o`:

- `intent_mismatch.json` — extra INV-003 on `n-form`. Aggregate targets
  still met. Fix candidates for M2:
  - add explicit "transitive reachability" worked example to the prompt;
  - add a fixture where the ui→store path is exactly two hops to give
    the model more grounding.

No known remaining FPs on `claude-opus-4-5` for this corpus.

## Knobs and overrides

| Override | Effect |
|---|---|
| `GLASSHOUSE_LLM_PROVIDER=openai\|anthropic` | force a provider |
| `GLASSHOUSE_COMPILER_MODEL=...` | force a specific model |
| `DEBUG=1` | bump logger level to DEBUG (also emits per-call payload metadata) |
| `--no-llm` (eval CLI) | skip LLM, only verify contracts parse |
| `--contract NAME` (eval CLI) | run a single fixture |

## Hand-off to M2 (Architect Agent + Contract I/O)

Everything M2 needs from M1 is already in place:

- `app/schemas.py` — Contract / Violation / CompilerOutput. Stable.
- `app/llm.py` — `call_compiler(contract)` returns a validated
  `CompilerOutput`. M2 imports this verbatim.
- `app/prompts/compiler.md` — system prompt the orchestrator will
  reuse on every Compiler invocation.
- `app/logger.py` — structured logging shape M2's WebSocket layer
  will inherit.
- `tests/conftest.py` — `CannedLLMClient` fixture lets M2's
  orchestrator tests run without API budget.

What M2 has to add:

- Architect agent (the "draft a contract from a prompt" side).
- Contract persistence (file-based or DB; ARCHITECTURE.md §6).
- Verification loop (the back-and-forth between Architect and
  Compiler with `verification_log` accumulation).
- WebSocket broadcaster.
- Question-priority deterministic test (the one we deferred from M1).

## Post-M1 housekeeping

- The `devin_env` config installs Miniconda + creates the `glasshouse`
  env automatically on every future session — already approved by the
  user.
- `ANTHROPIC_API_KEY` is stored org-wide as a saved secret (rotated
  after the initial plaintext exposure).
- No CI workflow on the repo yet; M3 will add one. `--no-llm` mode +
  pytest are CI-ready as is.
