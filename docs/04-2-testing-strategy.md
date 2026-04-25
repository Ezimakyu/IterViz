# 4.2 Testing Strategy

Tests live next to the code they exercise: each package has a `tests/` directory, and cross-package end-to-end tests live in `tests/integration/` at the repo root.

---

## 4.2.1 Test categories

### Telemetry Collector Tests

Run by `pytest packages/iterviz-server`. Cover:

* **WebSocket transport** — connection setup, frame parsing, reconnection on disconnect, backpressure.
* **Payload validation** — accepts well-formed JSON frames, rejects malformed ones with an informative error.
* **Routing** — frames with different `run_id`s land in the correct ring buffers.

> Shared-memory tests have been removed: shared memory is no longer in scope. The transport list for Phase 1 is **WebSocket only**.

### Time-Series Store Tests

* Ring buffer eviction at `window_size`.
* Concurrent writes from multiple Runs.
* Snapshot consistency (`GET /api/metrics?run_id=…` returns a coherent view).

### Run Lifecycle Tests

* `Run` creation, status transitions, and metadata persistence.
* Two-Runs-with-the-same-name produce distinct `run_id`s.

### Frontend Tests

Run by `npm test` in `packages/iterviz-ui/`. Cover:

* WebSocket client decoding.
* Chart-type auto-detection.
* Auto-grid responsive layout snapshots.
* (Phase 3) Visual regression snapshots for line/histogram/scatter charts.

### Logging & Error Handling Tests *(new)*

A dedicated test category that exercises the fire-and-forget guarantees and observability surfaces:

* **Fire-and-forget**: deliberately raise inside the transport / serializer / collector boundary and assert the host process is unaffected. The exception must be caught, logged to stderr, and never propagated.
* **Marker log format**: assert exactly the five expected stdout lines per session (server started, dashboard URL, run created, receiving metrics, run completed) and assert their structure / fields.
* **Reconnect-with-backoff**: simulate a server drop and assert the SDK retries with the documented exponential backoff schedule, flushes its buffered frames on reconnect, and emits a single warning when the bounded buffer overflows.
* **Verbose mode**: assert that `verbose=True` promotes debug-level records from `~/.iterviz/logs/` into stderr.

### Integration Tests

Live in `tests/integration/`. Spin up an actual `iterviz-server` subprocess, connect a real `iterviz-client`, drive a small loop, and assert the server's HTTP API and WebSocket fan-out match expectations.

---

## 4.2.2 Tooling

| Concern | Tool |
|---|---|
| Static Analysis | **`ruff`** (lint), **`mypy`** (type check) for Python; ESLint + `tsc --noEmit` for TypeScript. |
| Unit tests (Python) | `pytest`, `pytest-asyncio` for async paths. |
| Unit tests (TS) | `vitest` or `jest` (decided in Phase 0). |
| Integration tests | `pytest` driving subprocesses. |
| Coverage | `coverage.py` for Python, `c8` for TS. |
| CI | GitHub Actions (matrix on Python versions and OS). |

---

## 4.2.3 Test execution workflow

1. **Static Analysis (`ruff`, `mypy`)** — runs first, gates everything else.
2. **Unit tests per package** — `pytest packages/iterviz-client`, `pytest packages/iterviz-server`, `npm test` in `packages/iterviz-ui`.
3. **Integration tests** — `pytest tests/integration` last, since they spawn real servers.
4. **(Phase 3) Visual regression** — runs against the built UI bundle.

`make test-all` runs steps 1–3 in order locally; CI runs all four (where applicable per phase).

---

## 4.2.4 Conventions

* **Don't modify tests to make them pass.** If a test fails, fix the code or argue (in a PR comment) that the test is wrong. Don't silently weaken assertions.
* **Async tests use `pytest-asyncio`** with the `asyncio_mode = "auto"` config so every `async def test_…` is collected.
* **Fakes over mocks where possible.** Prefer a small in-memory fake (e.g. an in-process WebSocket) over heavy mock objects.
* **No network in unit tests.** Unit tests run hermetically. The only place real sockets are allowed is `tests/integration/`.
