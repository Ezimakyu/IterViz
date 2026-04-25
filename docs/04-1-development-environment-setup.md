# 4.1 Development Environment Setup

This page describes how to get a working dev environment for IterViz.

---

## 4.1.1 Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Runtime for `iterviz-client` and `iterviz-server`. |
| Node.js | 20+ | Build the `iterviz-ui` frontend. |
| `make` (or `just`) | any recent | Run cross-package targets. |
| `ruff` | latest | Python lint. Installed per-package via `pyproject.toml`. |
| `mypy` | latest | Python type-check. Installed per-package via `pyproject.toml`. |

---

## 4.1.2 Repository layout

```
IterViz/
├── README.md
├── Makefile
├── packages/
│   ├── iterviz-client/
│   │   ├── pyproject.toml
│   │   ├── iterviz_client/
│   │   └── tests/
│   ├── iterviz-server/
│   │   ├── pyproject.toml
│   │   ├── iterviz_server/
│   │   └── tests/
│   └── iterviz-ui/
│       ├── package.json
│       ├── src/
│       └── tests/
└── tests/
    └── integration/
```

Each Python package has its own `pyproject.toml` (no top-level `setup.py`); each is installable in editable mode independently.

---

## 4.1.3 First-time setup

```bash
# clone the repo
git clone https://github.com/Ezimakyu/IterViz.git
cd IterViz

# install the Python packages in editable mode
pip install -e packages/iterviz-client
pip install -e packages/iterviz-server

# install the frontend deps and build the UI bundle
make build-ui
```

`make build-ui` produces a static bundle under `packages/iterviz-ui/dist/`, which `iterviz-server` serves as static assets. You only need to rebuild the UI when its source changes.

---

## 4.1.4 Running the dev server

The default user workflow is **auto-spawn**: `iterviz.init()` (or `with iterviz.run(...)`) starts a server subprocess automatically. There is no manual two-step "initialize the server, then call init" flow — that was removed from the plan.

For development, you may want to run the server manually so you can see its logs and attach a debugger. Use:

```bash
make dev-server
```

This starts `iterviz-server` in the foreground on `127.0.0.1:8765`, with hot-reload enabled. Then in your script:

```python
with iterviz.run("dev_run", server_url="ws://127.0.0.1:8765") as viz:
    ...
```

Passing `server_url` tells the SDK to connect to your manually-running server instead of auto-spawning a new one.

---

## 4.1.5 Dependency management

Each package owns its dependencies via `pyproject.toml` (Python) or `package.json` (Node). The `iterviz-client` package optionally depends on `iterviz-server` (via an extras_require / optional-dependencies group named `server`) to enable auto-spawn. End users who only want to connect to a remote server can install `iterviz-client` without the `server` extra.

| Package | Manifest | Key dev tools |
|---|---|---|
| `iterviz-client` | `packages/iterviz-client/pyproject.toml` | `ruff`, `mypy`, `pytest` |
| `iterviz-server` | `packages/iterviz-server/pyproject.toml` | `ruff`, `mypy`, `pytest`, framework choice from [2.3](02-3-rendering-engine-and-frontend-ui.md) |
| `iterviz-ui` | `packages/iterviz-ui/package.json` | ESLint, `tsc`, framework + chart lib choices from [2.3](02-3-rendering-engine-and-frontend-ui.md) |

Framework choices (FastAPI/aiohttp/Tornado for the backend; React/Preact/Svelte/Vanilla TS for the frontend; uPlot/Chart.js/D3/Recharts for charting; Vite/esbuild for the bundler) are **recommendations** — see [2.3](02-3-rendering-engine-and-frontend-ui.md) for the full decision matrix. The Phase 0 implementation session picks one option per layer.

---

## 4.1.6 `Makefile` (or `justfile`) targets

| Target | Purpose |
|---|---|
| `make build-ui` | Install frontend deps and build the static bundle into `packages/iterviz-ui/dist/`. |
| `make dev-server` | Run `iterviz-server` in the foreground with hot reload, useful for debugging. |
| `make test-all` | Run unit tests for all three packages plus `tests/integration/`. |
| `make lint` | Run `ruff` on all Python packages and ESLint on the UI. |
| `make typecheck` | Run `mypy` on all Python packages and `tsc --noEmit` on the UI. |

The `justfile` equivalent (if `just` is preferred) exposes the same targets under the same names.

---

## 4.1.7 Common pitfalls

* **Forgetting `make build-ui`.** Without a built UI bundle, the server returns a placeholder page. Re-run `make build-ui` after frontend changes.
* **Mismatched server versions.** If you `pip install -e` only one of the two Python packages, auto-spawn won't work. Install both for a full local dev loop.
* **Using `setup.py`.** Don't. Each Python package uses `pyproject.toml`.
