# 01 — Overview

## Where M2 sits in the system

```
            POST /api/v1/sessions
              prompt: "..."
                        │
                        ▼
                ┌───────────────┐
                │   api.py      │  thin: validate + delegate
                └───────┬───────┘
                        │
            architect.generate_contract(prompt)
                        │   uses llm.call_structured(response_model=Contract)
                        ▼
                ┌───────────────┐
                │  Architect    │  prompts/architect.md → instructor
                └───────┬───────┘
                        │   Contract instance
                        ▼
            contract.create_session(contract)
                        │   Pydantic + jsonschema validation
                        ▼
                ┌───────────────┐
                │  SQLite       │  sessions(id, created_at, updated_at,
                └───────────────┘                  status, contract_json)
```

Subsequent reads (`GET /api/v1/sessions/{id}`) and refines
(`POST /api/v1/sessions/{id}/architect/refine`) flow through the same
service layer.

## End-to-end sequence

1. **HTTP in.** Client `POST`s `{"prompt": "..."}` to `/api/v1/sessions`. FastAPI
   binds the body to `CreateSessionRequest`; an empty/missing prompt produces
   `422` automatically.
2. **Architect.** `architect.generate_contract(prompt)` builds the user message,
   loads `prompts/architect.md`, and calls `call_structured(response_model=Contract)`.
   `instructor` enforces the `Contract` Pydantic schema on the LLM response.
3. **Post-processing.** The Architect prepends the user prompt to
   `meta.prompt_history`, fills `meta.id`/`meta.created_at` if the LLM omitted
   them, and pins `meta.version = 1` for fresh contracts.
4. **Persistence.** `contract.create_session(contract)` runs the contract through
   `validate_contract_payload` (Pydantic + JSON-Schema), then writes a single
   row to the `sessions` table keyed by `meta.id`.
5. **Response.** API returns `{session_id, contract}`.

Refinement (`refine_contract`) follows the same shape: load existing session,
re-prompt the Architect with `(previous contract JSON + user answers JSON)`,
make sure all answers land in `decisions[]`, bump `meta.version`, persist.

## Key design choices

- **One LLM seam.** `app.llm.call_structured` is the only place the
  `instructor`-patched provider client is constructed. Tests mock it with a
  one-line `monkeypatch.setattr` and never touch real provider SDKs.
- **`Contract` is the response model.** No glue layer; the LLM either produces
  a structurally valid `Contract` (with all the schema constraints from
  ARCHITECTURE.md §4) or `instructor` retries.
- **Two-pass write validation.** Every write goes through Pydantic *and* a
  separate JSON-Schema validation pass. Pydantic catches "wrong shape";
  JSON-Schema validation guards against future schema drift between the
  in-memory model and the on-disk JSON.
- **Stateless reads.** `get_session` re-validates on read so a manually edited
  DB row never produces an invalid `Contract` object inside the app.
- **No DB ORM.** Plain `sqlite3` keeps the dependency footprint tiny and
  lifecycle obvious. The `sessions` schema is one table; the column we read
  most (`contract_json`) is opaque text — an ORM buys nothing here.
- **DB path is overridable.** `set_db_path()` exists explicitly so tests can
  point at a per-test `tmp_path / "test.db"` without environment hacks.

## What M2 does NOT include

- The Compiler is not invoked from the API surface yet — that is M3 work.
- WebSocket streaming (`/api/v1/sessions/{id}/stream`) is not wired.
- Phase-2 routes (`/freeze`, `/implement`, agent registry) are intentionally
  absent; they belong to M5.
- The Architect prompt deliberately stops at "produce a Contract" — node-level
  invariant checking is the Compiler's job, not the Architect's.
