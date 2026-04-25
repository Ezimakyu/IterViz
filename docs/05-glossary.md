# 5. Glossary

| Term | Definition |
|---|---|
| **Iter** | A single discrete step in a repetitive computational process — one epoch of training, one solver iteration, one pipeline tick. |
| **Viz** | The graphical (browser-based) representation of metrics produced during a Run. |
| **Run** | A single execution session of any iterative process observed by IterViz. Identified by a unique `run_id` (UUID), a user-provided `name`, a `created_at` timestamp, a `status` (`running` / `completed` / `failed`), and an optional free-form `metadata` dict. The `TimeSeriesStore` is keyed by `run_id`, and the UI exposes Run-level operations (list, overlay, compare). |
| **Telemetry Collector** | The `iterviz-server` subsystem that accepts incoming WebSocket frames from the SDK, validates them, and routes them into the store. |
| **TimeSeriesStore** | The `iterviz-server` storage layer. In Phase 1 it is an in-memory bounded ring buffer per `(run_id, metric_name)` pair; in Phase 2b a SQLite backend is added. |
| **Iteration History** | The accumulated time-series data for a metric within a Run, retained up to the configured `window_size`. |
| **State Changes** | Modifications to user-observed variables between iterations of a Run; in IterViz these are surfaced via `viz.log({...})` calls. |
| **Marker Log** | A concise, human-readable log line emitted to stdout at key lifecycle events (server started, dashboard URL, run created, receiving metrics, run completed). Designed to confirm IterViz is operational without cluttering the terminal. Five marker lines per session. |
| **Fire-and-forget Mode** | The default error-handling strategy of the SDK: every exception in the telemetry path is caught at the SDK boundary, logged to stderr (or `~/.iterviz/logs/` for debug), and **never propagated** to the host process. Visualization failures must not crash the user's loop. |
| **Context Manager API** | The Pythonic `with iterviz.run("name") as viz:` interface. It guarantees that the Run is initialized on entry and finalized on exit, even when the body raises. The recommended way to use IterViz. |
| **Decorator API** | The `@iterviz.track("name")` decorator, which wraps a function in an implicit `with iterviz.run("name") as viz:` block and injects `viz` as an argument. |
| **Procedural API** | The lower-level `iterviz.init()` / `iterviz.log()` / `iterviz.finalize()` triplet, retained as a fallback for cases where a context manager is awkward. |
| **Zero-config** | The default operating mode of IterViz. Metric chart types are auto-detected from the first observed payload (scalar → line, array → histogram), the layout is an auto-grid, `window_size` defaults to 1000, and `refresh_interval_ms` defaults to 200 ms. No configuration file is required. |
| **LTTB (Largest Triangle Three Buckets)** | A downsampling algorithm that preserves the visual shape of a time series while reducing the number of points. Planned as a transform in Phase 2a. |
| **Auto-spawn** | The default behavior of `iterviz.init()` / `iterviz.run()`: if no server is reachable, the SDK launches a local `iterviz-server` subprocess and opens the dashboard. Disabled by passing an explicit `server_url`. |
| **Run overlay** | A Phase 2b UI feature that lets the user select multiple Runs and overlay the same metric across them in a single chart for comparison. |
