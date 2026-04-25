# IterViz

> Real-time visualization for iterative processes — machine learning training loops, optimization solvers, simulations, data pipelines, and any other long-running computation that produces a stream of metrics.

IterViz is a lightweight observability layer for *any* iterative program. You instrument your loop with a single context manager, IterViz auto-spawns a local server, opens a dashboard in your browser, and streams metrics live as your run progresses. Zero configuration is required.

> **Status:** Planning / bootstrapping phase. No runnable code yet — this repo currently contains design documents only. See [`docs/`](docs/) for the full implementation plan.

---

## Quick start (target API)

```python
import iterviz

with iterviz.run("my_experiment") as viz:
    for i in range(1000):
        result = step()
        viz.log({"objective": result})
```

That's it. `iterviz.run(...)`:

1. Auto-spawns a local IterViz server subprocess on first use.
2. Opens the dashboard in your default browser.
3. Creates a new `Run` (UUID + name + timestamp + status).
4. Streams every `viz.log({...})` call to the dashboard over WebSocket as JSON.
5. Auto-finalizes the run on context exit, even if your loop raises.

A decorator form is also available:

```python
@iterviz.track("optimization")
def optimize(viz):
    for i in range(1000):
        viz.log({"objective": step()})
```

The procedural `iterviz.init()` / `viz.log()` / `viz.finalize()` API is also supported for cases where a context manager isn't ergonomic.

### Connecting to a remote server

By default IterViz auto-spawns a local server. To target an existing remote server, pass `server_url`:

```python
with iterviz.run("my_experiment", server_url="ws://my-host:8765") as viz:
    ...
```

---

## Monorepo layout

IterViz is a **monorepo** of three independently-versioned packages:

```
IterViz/
├── README.md
├── Makefile
├── packages/
│   ├── iterviz-client/         # Python SDK — what user code imports
│   │   ├── pyproject.toml
│   │   ├── iterviz_client/
│   │   └── tests/
│   ├── iterviz-server/         # Python backend — collector, store, REST + WS
│   │   ├── pyproject.toml
│   │   ├── iterviz_server/
│   │   └── tests/
│   └── iterviz-ui/             # TypeScript frontend — served by iterviz-server
│       ├── package.json
│       ├── src/
│       └── tests/
└── tests/
    └── integration/            # Cross-package end-to-end tests
```

* `iterviz-client` optionally depends on `iterviz-server` to enable auto-spawn. If the server package isn't installed, the client falls back to remote-only mode (`server_url` required).
* `iterviz-server` serves the built `iterviz-ui` static assets, so the user only ever installs Python packages.
* The root `Makefile` (or `justfile`) coordinates cross-package builds, lint, type-check, and tests.

---

## Design principles

* **JSON only** for the Phase 1 wire format. Protobuf may be revisited later as an optimization.
* **WebSocket only** transport in Phase 1. JSONL file transport is deferred to Phase 2b.
* **Auto-spawn by default.** No manual two-step `iterviz-server start` + `iterviz.init()` dance.
* **Zero-config.** Metric chart types are auto-detected from the first payload; layout is an auto-grid.
* **Fire-and-forget telemetry.** All exceptions in the telemetry path are caught and logged — they never propagate into the host process. A visualization bug must never crash your training run.
* **Domain-agnostic.** A `Run` is any iterative process — ML, optimization, ETL, simulation. IterViz makes no ML-specific assumptions.

---

## Documentation

Full implementation plan and design docs live in [`docs/`](docs/):

| # | Page |
|---|---|
| 1 | [Overview](docs/01-overview.md) |
| 1.1 | [Project Purpose & Goals](docs/01-1-project-purpose-and-goals.md) |
| 1.2 | [Repository Status & Roadmap](docs/01-2-repository-status-and-roadmap.md) |
| 2 | [Architecture](docs/02-architecture.md) |
| 2.1 | [Data Ingestion & Telemetry Collection](docs/02-1-data-ingestion-and-telemetry-collection.md) |
| 2.2 | [Data Transformation & Storage](docs/02-2-data-transformation-and-storage.md) |
| 2.3 | [Rendering Engine & Frontend UI](docs/02-3-rendering-engine-and-frontend-ui.md) |
| 3 | [Configuration](docs/03-configuration.md) |
| 3.1 | [Configuration Schema Reference](docs/03-1-configuration-schema-reference.md) |
| 3.2 | [Usage Examples & Integration Guide](docs/03-2-usage-examples-and-integration-guide.md) |
| 4 | [Contributing](docs/04-contributing.md) |
| 4.1 | [Development Environment Setup](docs/04-1-development-environment-setup.md) |
| 4.2 | [Testing Strategy](docs/04-2-testing-strategy.md) |
| 5 | [Glossary](docs/05-glossary.md) |

Once published on GitHub Wiki, these pages will mirror the file layout above.

---

## License

TBD.
