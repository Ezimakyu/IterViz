# 00 — Overview

## Goal

From `TODO.md` M1: *"Build an isolated eval script to iterate on the Blind
Compiler's system prompt. Establish a baseline for violation detection."*

M1 is intentionally **decoupled** from the rest of the backend:
- No FastAPI server, no database, no websockets, no orchestrator — those
  arrive in M2/M3.
- Everything M1 ships is callable from a single CLI: `scripts/eval_compiler.py`.
- The artifacts produced here (schemas, prompt, seed corpus) are the ones
  M2 and M3 will import and extend, so getting them right now matters more
  than getting them numerous.

## Acceptance criteria (from TODO.md M1)

1. `python scripts/eval_compiler.py` runs without errors.
2. Recall ≥ 80%.
3. Precision ≥ 90%.
4. `valid_simple.json` returns `verdict=pass` with 0 violations.
5. Each invalid contract triggers its expected violations.
6. `pytest tests/test_schemas.py` passes.

All six are met on the `devin/1777162267-m1-compiler-harness` branch.

## Headline results

| Model | Recall | Precision | Per-contract |
|---|---|---|---|
| `gpt-4o-mini` | 72.73% | 61.54% | 5/8 — fails M1 targets |
| `gpt-4o` | 100% | 91.67% | 7/8 — meets targets |
| **`claude-opus-4-5`** | **100%** | **100%** | **8/8 — clean sweep** |
| `--no-llm` (schema parse only) | n/a | n/a | 8/8 parse cleanly |

`gpt-4o` is the OpenAI default in `app/llm.py`; `claude-opus-4-5` is the
Anthropic default and the demo target. `gpt-4o-mini` was retained as a
"floor" model — its consistent failure on this corpus is itself a useful
signal during prompt tuning, since regressions show up there first.

## Design choices that survived

- **Pydantic v2 with `extra=forbid` on `CompilerOutput`.** Forces the LLM
  through `instructor` to emit only the fields we model — no stowaway
  reasoning blobs, no taxonomy invention.
- **Temperature = 0.** SPEC.md §3 requires the Compiler be deterministic;
  this is the only sane default for a verifier.
- **Expectation sidecar (`_expected.json`).** Keeps grading data out of
  the contract fixtures, so the seed contracts remain valid example
  contracts that future agents can learn from.
- **Three-strategy violation matcher.** `accept_types`, `rule_substr`,
  `affects`-overlap. Lets us be strict about *what* was found while
  forgiving the LLM's choice of taxonomy bucket on borderline cases.
- **`is_terminal: bool` on `Node`.** Pragmatic addition for INV-001 so
  source/sink fixtures don't false-trigger orphan detection.
- **Structured JSON logging from day one.** Every `app.llm.call_compiler`
  emits one INFO record per pass; reproducing an eval run from logs is
  straightforward and won't need a rewrite for M2.

## What did NOT make it in (and why)

- **No CI workflow.** The repo has no `.github/workflows/` yet; adding one
  is M3's job per the parallel-dev plan. `--no-llm` mode + pytest are
  ready to drop into a workflow later without changes.
- **No verification_log persistence.** SPEC.md §3.5 mentions writing the
  Compiler output back into `contract.verification_log`. That belongs in
  the Architect agent loop (M2), not in an isolated eval script.
- **No UVDC scoring.** SPEC.md §6 calls out a User-Visible Defect
  Correlation metric. Out of M1 scope; we only track recall/precision
  against curated expectations.
- **No question prioritization tests.** The prompt enforces the priority
  ladder verbally; building a deterministic test for it requires multiple
  fixtures with conflicting tiers and is a M2 follow-up.
