# 07 — Bugs found and fixed during M4

Only one real bug landed in M4 — but it's a useful one because it's
exactly the kind of thing automated tests would silently miss without
explicit care, and because it required a regression test that runs in
a non-default state to lock down.

## Bug 1: `LogRecord.name` collision in `compiler.node_provenance_detail`

### Symptom

During the live end-to-end test (Anthropic Claude → Verify under
`DEBUG=1`), `POST /api/v1/sessions/{id}/compiler/verify` returned a
**500 Internal Server Error** on the second pass. Backend log:

```
KeyError: "Attempt to overwrite 'name' in LogRecord"
  File "/usr/lib/python3.10/logging/__init__.py", line 1596, in makeRecord
    raise KeyError("Attempt to overwrite %r in LogRecord" % key)
  File "backend/app/compiler.py", line 791, in verify_contract
    log.debug(
        "compiler.node_provenance_detail",
        extra={
            "node_id": node.id,
            "name": node.name,        # ← collision
            "decided_by": _enum_value(node.decided_by),
            ...
        },
    )
```

### Root cause

Python's `logging` module reserves a fixed set of attribute names on
every `LogRecord`: `name`, `msg`, `args`, `levelname`, `levelno`,
`pathname`, `filename`, `module`, `exc_info`, `exc_text`, `stack_info`,
`lineno`, `funcName`, `created`, `msecs`, `relativeCreated`, `thread`,
`threadName`, `processName`, `process`, `message`, `asctime`. If the
`extra={...}` dict contains any of those keys, `Logger.makeRecord`
raises `KeyError(f"Attempt to overwrite {key!r} in LogRecord")`.

The M4 implementation passed `name=node.name` in `extra` for a
debug-level structured log line. `name` is the *most* reserved key
(it's the logger's own module name) so this exploded as soon as the
log statement was actually evaluated.

### Why every existing test passed

The tests run with the default log level (`WARNING` / no extra
config), so `log.debug(...)` was a no-op and the `extra` dict was
never materialized into a `LogRecord`. The bug only triggered when:

1. A real client called the route (so the `verify_contract` codepath
   actually ran on a non-trivial contract), **and**
2. The backend was started with `DEBUG=1` (so `log.debug(...)`
   actually executed), **and**
3. The contract had at least one node (so the per-node loop iterated
   at least once).

The end-to-end test happened to satisfy all three, which is why it
caught the bug that `pytest backend/tests/` had not.

### Fix

Two changes in the same commit (`044ea9b` on branch
`devin/1777195392-m4-editable-graph`):

```diff
 log.debug(
     "compiler.node_provenance_detail",
     extra={
         "node_id": node.id,
-        "name": node.name,
+        "node_name": node.name,
         "decided_by": _enum_value(node.decided_by),
         ...
     },
 )
```

And a regression test under `TestProvenanceAwareVerification` in
`backend/tests/test_compiler.py`:

```python
def test_verify_contract_works_at_debug_log_level(self):
    """Regression: a previous version of `verify_contract` emitted
    ``log.debug("compiler.node_provenance_detail", extra={"name": ...})``,
    which collided with ``LogRecord.name`` and raised KeyError under
    ``DEBUG=1``. Make sure we can run the full deterministic pass at
    DEBUG without that crash recurring.
    """
    import logging
    from app import compiler as compiler_mod

    a = _node(name="A", decided_by=DecidedBy.PROMPT)
    b = _node(name="B", decided_by=DecidedBy.PROMPT)
    contract = _contract([a, b], [_edge(a, b)])

    prev_level = compiler_mod.log.level
    compiler_mod.log.setLevel(logging.DEBUG)
    try:
        out = verify_contract(contract, use_llm=False)
    finally:
        compiler_mod.log.setLevel(prev_level)
    assert out is not None
```

The test temporarily sets the compiler module's log level to
`DEBUG`, runs `verify_contract`, then restores. If anyone re-introduces
a reserved-key collision in `extra=` from any structured log line in
that pipeline, the test fails with a clear `KeyError` in CI.

### Verification

- The test was added on top of the original buggy code first and
  reproduced the failure exactly (as a `KeyError` in pytest).
- The rename was then applied; the test passed.
- The full backend suite was re-run: **90 passed** (M0 through M4).
- The end-to-end run (recorded in `.devin/test-report-m4.md`) was
  re-driven from the start; the bug did not recur and the M4 flow
  completed cleanly with `compiler.uvdc_breakdown` going `0.16 → 0.20`.

### Lessons

- **Never use a Python identifier as a structured-log key without
  thinking about `LogRecord` reserved names.** A simple grep over the
  codebase for `extra={` with any of those keys will surface other
  candidates: `module`, `message`, `asctime` are common offenders.
  M4 avoided the rest of them, but a future audit pass would be
  cheap.
- **Tests must exercise the configurations operators run in.** This
  bug was hiding behind log-level configuration that none of the
  default test runs exercised. The regression test now forces
  `DEBUG`, which catches any future occurrence regardless of the
  caller's environment.

## Bugs not found

The rest of the test pass and the live run did not surface anything
else. The structural-field rejection, no-op semantics, multi-field
update, and 404 behaviors all worked first try; UVDC monotonicity
matched the unit-test expectation against the live LLM-generated
contract.

## Open follow-ups (not bugs, scoped out of M4)

- Edge-level user editing (kind/payload schema) is supported on the
  Compiler side but not exposed in the UI. Wire it through in M4.5
  or M5.
- Assumption-list editing through the popup is supported on the
  schema/service side but the UI element doesn't exist yet.
- Per-field provenance display in the popup is currently a simple
  blue border. A future iteration could surface "decided by" per
  field instead of just "decided by" for the whole node.
