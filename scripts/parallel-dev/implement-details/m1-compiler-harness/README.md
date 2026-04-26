# M1 — Blind Compiler Tuning Harness (implementation details)

Branch: `devin/1777162267-m1-compiler-harness` · PR: [#4](https://github.com/Ezimakyu/IterViz/pull/4)

This directory documents how M1 was built. M1's job is **not** to ship the
final Glasshouse server — it is to (a) define the contract schema we will
keep using through M2/M3, (b) draft the Blind Compiler system prompt, and
(c) prove on a frozen seed corpus that a real LLM clears the SPEC's
`recall ≥ 80% / precision ≥ 90%` bar.

## File map

```
backend/
├── pyproject.toml                    # build system + pytest config (pythonpath=".")
├── requirements.txt                  # openai, anthropic, instructor, pydantic, pytest, pytest-cov
├── app/
│   ├── __init__.py
│   ├── logger.py                     # structured JSON logger, DEBUG=1 toggles level
│   ├── llm.py                        # instructor wrapper, temperature=0, multi-provider
│   ├── schemas.py                    # Contract, Node, Edge, Violation, CompilerOutput
│   └── prompts/
│       └── compiler.md               # Blind Compiler system prompt (4 passes + few-shots)
├── scripts/
│   ├── eval_compiler.py              # eval harness, reports recall/precision
│   └── seed_contracts/
│       ├── _expected.json            # expectation sidecar
│       └── *.json                    # 8 seed fixtures
└── tests/
    ├── conftest.py                   # fixtures, sys.path injection, CannedLLMClient
    └── test_schemas.py               # 16 schema validation tests
```

## Reading order

1. [`00-overview.md`](./00-overview.md) — goal, acceptance criteria, headline results.
2. [`01-schemas.md`](./01-schemas.md) — every Pydantic model, why each constraint exists.
3. [`02-prompt.md`](./02-prompt.md) — Blind Compiler system prompt anatomy.
4. [`03-llm-wrapper.md`](./03-llm-wrapper.md) — `instructor` + provider/model resolution.
5. [`04-seed-contracts.md`](./04-seed-contracts.md) — what each of the 8 fixtures exercises.
6. [`05-eval-harness.md`](./05-eval-harness.md) — matcher semantics + metrics aggregation.
7. [`06-tests-and-logger.md`](./06-tests-and-logger.md) — pytest layout + structured logging.
8. [`07-results-and-followups.md`](./07-results-and-followups.md) — three-model matrix, FPs, M2 hand-off.

## Quick reproduce

```bash
conda activate glasshouse
cd backend
pytest tests/test_schemas.py                   # 16/16
python scripts/eval_compiler.py --no-llm       # 8/8 contracts parse

# Live LLM eval (one of):
GLASSHOUSE_LLM_PROVIDER=openai  GLASSHOUSE_COMPILER_MODEL=gpt-4o          python scripts/eval_compiler.py
GLASSHOUSE_LLM_PROVIDER=anthropic GLASSHOUSE_COMPILER_MODEL=claude-opus-4-5 python scripts/eval_compiler.py
```

Headline: **Opus 4.5 → 100% recall / 100% precision / 8/8 contracts.**
