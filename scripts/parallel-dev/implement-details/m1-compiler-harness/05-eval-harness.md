# 05 — Eval harness (`backend/scripts/eval_compiler.py`)

A 268-line script that loads every JSON fixture under
`scripts/seed_contracts/`, runs `app.llm.call_compiler`, compares
emitted violations against the expectation sidecar, and reports
recall / precision in aggregate.

## CLI

```
python scripts/eval_compiler.py [--contract NAME] [--no-llm]
```

| Flag | Effect |
|---|---|
| (none) | Run every contract through the live LLM. |
| `--contract NAME` | Run a single fixture (e.g. `--contract orphaned_node.json`). |
| `--no-llm` | Skip the LLM call entirely; only verify each contract parses cleanly. CI-safe. |

Exit codes: `0` if all targets met (recall ≥ 80%, precision ≥ 90%, all
contracts pass per-contract grading), `1` otherwise.

## Pipeline

1. Insert `backend/` onto `sys.path` so `from app.* import ...` works
   regardless of the current working directory.
2. Load `_expected.json`.
3. For each `*.json` in the seed dir (excluding `_expected.json`):
   a. Parse with `Contract.model_validate(...)`. Schema errors are
      surfaced and counted as a contract-level failure.
   b. If `--no-llm`, stop here.
   c. Otherwise, call `app.llm.call_compiler(contract)` to get a
      `CompilerOutput`.
   d. Run the matcher against the contract's expectation entry.
4. Print a per-contract summary (verdict, violations, questions,
   intent_guess) plus an aggregate block.

## Matcher (`_violation_matches`)

```python
def _violation_matches(emitted: dict, expected: dict) -> bool:
    accept_types = expected.get("accept_types") or [expected["type"]]
    if emitted["type"] not in accept_types:
        return False

    rule_substr = expected.get("rule_substr")
    if rule_substr:
        if rule_substr.lower() not in emitted["message"].lower():
            return False
        return True   # affects is auto-satisfied if rule matched

    expected_affects = set(expected.get("affects") or [])
    if not expected_affects:
        return True
    emitted_affects = set(emitted.get("affects") or [])
    return bool(emitted_affects & expected_affects)
```

Three independent strategies, applied in order:

1. **Type match.** `emitted.type` must be in `accept_types`. By default
   `accept_types = [expected.type]`, but the sidecar can opt into a
   wider bucket (e.g. accept either `provenance` or `invariant`).
2. **Rule substring.** When `rule_substr` is set (e.g. `"INV-001"`),
   the emitted message must contain it case-insensitively. If matched,
   we treat `affects` as satisfied — many models report finer-grained
   `affects` like `node.assumptions[0]` instead of `n-store`, and we
   don't want that to penalize them when the rule was clearly hit.
3. **Affects overlap.** If `expected.affects` is non-empty, the
   emitted `affects` set must intersect it. An empty `expected.affects`
   means "match by type alone".

## Metrics

- **Per-contract pass.** A contract passes only if there are no errors,
  the verdict matches, *and* every expected violation was matched
  *and* every emitted violation was matched (no false positives).
- **Aggregate recall.** Sum of matched expected violations across all
  contracts, divided by total expected violations.
- **Aggregate precision.** Sum of matched emitted violations across
  all contracts, divided by total emitted violations.
- **Targets.** Recall ≥ 80%, precision ≥ 90% (from TODO.md M1).

The aggregate metrics are independent of the per-contract pass count:
a contract can fail per-contract grading (e.g. one spurious violation)
while the aggregate still meets targets. The exit-code check requires
both — aggregates met *and* all contracts pass.

## Why a sidecar instead of inline expectations?

Two reasons:

1. The seed contracts double as *example documents*. Mixing grading
   metadata into them would make them less useful as references for
   M2 agents that will read these contracts as exemplars.
2. The matcher can evolve independently of the corpus. We extended
   `accept_types` and `rule_substr` mid-iteration; doing that without
   touching every fixture saved a lot of churn.

## What the harness intentionally does NOT do

- No statistical confidence (e.g. CI bootstrap on recall). The corpus
  is small enough that point estimates are sufficient for M1.
- No diff against a previous run. Helpful eventually, but each eval
  takes ~30s of wall time and we just re-ran from scratch each time.
- No per-violation scoring. A violation is matched (1) or not (0).
  Partial credit (e.g. "right type, wrong affects") was considered
  and rejected — too easy to trick yourself with weighted metrics.
