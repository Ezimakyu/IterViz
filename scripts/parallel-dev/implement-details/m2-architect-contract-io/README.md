# M2 — Architect Agent + Contract I/O — Implementation Details

This directory documents how Milestone **M2** was actually built. It is the
working reference for the Architect agent, the SQLite-backed contract store,
and the FastAPI surface that wires them together.

> Source PR: [#3](https://github.com/Ezimakyu/IterViz/pull/3) — merged on top
> of M1 (PR #4) so M1 schemas / LLM wrapper / logger are the canonical
> versions.

## What landed

| Path | Purpose |
| --- | --- |
| `backend/app/prompts/architect.md` | Architect system prompt + 3 few-shot examples |
| `backend/app/architect.py` | `generate_contract` / `refine_contract` |
| `backend/app/contract.py` | SQLite persistence + Pydantic + JSON-Schema validation |
| `backend/app/api.py` | `POST /api/v1/sessions`, `GET /api/v1/sessions/{id}`, `POST .../architect/refine` |
| `backend/app/main.py` | FastAPI factory, CORS, JSON request-logger middleware, lifespan-driven `init_db()` |
| `backend/app/schemas.py` *(extension)* | `CreateSessionRequest/Response`, `GetSessionResponse`, `RefineRequest/Response`, `ContractMeta = Meta` alias |
| `backend/app/llm.py` *(extension)* | Generic `call_structured(response_model=…)` next to M1's `call_compiler` |
| `backend/requirements.txt` *(extension)* | `jsonschema` (used by `validate_contract_payload`) |
| `backend/tests/conftest.py` *(extension)* | `sample_contract` factory + `temp_db` fixture (alongside M1 fixtures) |
| `backend/tests/test_contract.py` | Persistence round-trip, missing/duplicate, garbage-in rejection |
| `backend/tests/test_architect.py` | Architect with `call_structured` mocked |
| `backend/tests/test_api.py` | TestClient covering 201 / 200 / 404 / 422 + refine |

## File guide in this directory

| File | What it covers |
| --- | --- |
| `01-overview.md` | High-level picture: data flow, end-to-end sequence, design choices |
| `02-architect-agent.md` | Prompt design, generation + refinement, invariants enforced in code |
| `03-contract-persistence.md` | Schema, CRUD, validation guarantees, threading model |
| `04-api-and-app-factory.md` | Routes, request/response models, middleware, lifespan |
| `05-tests-and-acceptance.md` | Test layout, fixture strategy, acceptance-criteria mapping |
| `06-merge-with-m1.md` | What conflicted with M1 and how it was resolved |

## Acceptance summary

- `pytest tests/ -v` → **39 passed in 1.83s** (16 from M1 + 23 from M2).
- `DEBUG=1 uvicorn app.main:app --reload` boots cleanly; `/health` returns `{"status": "ok"}`; structured JSON logs include `app.startup`, `http.request` (with `duration_ms`), and `llm call completed` (with per-call `duration_ms` and `response_model`).
- `POST /api/v1/sessions` runs the Architect, persists the contract, and returns `{session_id, contract}` with **≥ 3 nodes and ≥ 2 edges** (asserted by `test_post_sessions_returns_201_and_contract`).
- `GET /api/v1/sessions/{id}` returns the same contract (`test_post_sessions_then_get`).
