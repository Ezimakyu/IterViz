# 03 — Contract Persistence (`app/contract.py`)

SQLite-backed persistence for sessions. Every Architect run produces a
`Contract`; this module is responsible for writing, reading, updating,
and validating those contracts on disk.

## SQL schema

One table — kept deliberately small so the contract JSON can evolve
without migrations:

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,    -- session id == contract.meta.id
    created_at    TEXT NOT NULL,       -- ISO-8601 UTC
    updated_at    TEXT NOT NULL,
    status        TEXT NOT NULL,       -- mirrored from contract.meta.status
    contract_json TEXT NOT NULL        -- full contract JSON blob
);
```

The session id is intentionally the same as `contract.meta.id` so the two
identifiers can never drift. `status` is denormalized out of the JSON
blob purely so future endpoints can filter sessions without parsing
JSON.

## Database path resolution

`get_db_path()` resolves in this order:

1. `set_db_path(path)` override (used by the `temp_db` test fixture).
2. `GLASSHOUSE_DB` environment variable.
3. `backend/glasshouse.db` default — the file is gitignored.

`init_db()` is idempotent (`CREATE TABLE IF NOT EXISTS`) and is called by
both the FastAPI lifespan (`app.startup`) and from each CRUD function
defensively, so stand-alone callers (CLIs, tests, scripts) don't have to
remember to bootstrap the DB.

## Public surface

```python
class Session:
    id: str
    created_at: str
    updated_at: str
    status: str
    contract: Contract
    def to_dict(self) -> dict[str, Any]: ...

class ContractValidationError(ValueError): ...
class SessionNotFoundError(LookupError): ...

def init_db() -> None: ...
def get_db_path() -> Path: ...
def set_db_path(path: str | Path | None) -> None: ...

def validate_contract_payload(
    payload: Contract | dict[str, Any] | str,
) -> Contract: ...

def create_session(contract: Contract) -> Session: ...
def get_session(session_id: str) -> Session: ...
def update_contract(session_id: str, contract: Contract) -> Session: ...
def list_sessions() -> list[Session]: ...
def delete_session(session_id: str) -> None: ...
```

The custom errors give the API layer something specific to map to HTTP
codes (`SessionNotFoundError → 404`, `ContractValidationError → 422`)
without coupling the persistence layer to FastAPI.

## Validation pipeline (`validate_contract_payload`)

Every write goes through both layers:

1. **Pydantic.** If the payload is a `dict` / `str`, run
   `Contract.model_validate(...)` to catch shape errors early.
2. **JSON-Schema.** Generate `Contract.model_json_schema()` once (cached
   in `_CONTRACT_JSON_SCHEMA`), then `jsonschema.validate(as_dict, schema)`.

The double pass exists for two reasons:

- Pydantic models can drift from the JSON-Schema view (e.g. adding
  computed fields, extra="allow"); validating both prevents writing
  contracts that are valid as Python objects but malformed as JSON.
- `validate_contract_payload` is also the function used to read rows back
  in (`_row_to_session` calls it on `contract_json`), so a contract that
  fails schema validation can never be returned from the persistence
  layer regardless of how it got into the row.

## CRUD specifics

### `create_session(contract)`

- Calls `init_db()` (idempotent), then `validate_contract_payload(contract)`.
- Refuses to insert if a row already exists for `contract.meta.id` (raises
  `ContractValidationError`). This protects against accidentally
  overwriting a session by re-running the Architect with a recycled
  `meta.id`.
- Stamps `created_at = updated_at = now()` (UTC ISO-8601) on the row.
- Logs `contract.create_session` with `session_id` and `status`.

### `get_session(session_id)`

- Reads one row by primary key, raises `SessionNotFoundError` if missing.
- Re-runs `validate_contract_payload` on the stored JSON via
  `_row_to_session`, so a manually edited DB row never produces an
  invalid `Contract` in memory.

### `update_contract(session_id, contract)`

- Validates the new contract.
- Refuses to update non-existent rows (`SessionNotFoundError`).
- Preserves the original `created_at`; only `updated_at`, `status`, and
  `contract_json` are mutated.
- Logs the new `version` so refinement traffic is easy to trace.

### `list_sessions()` / `delete_session(session_id)`

Convenience helpers used by tests and the upcoming admin tooling. Both
re-validate on read.

## Threading model

`_lock` is a module-level `threading.Lock`. All writes (`init_db`,
`create_session`, `update_contract`, `delete_session`) acquire it before
opening the SQLite connection. Reads do not — SQLite serializes them on
its own and we want concurrent `GET /sessions/{id}` requests to proceed
in parallel.

The lock specifically protects:

- The `CREATE TABLE IF NOT EXISTS` race during cold-start when multiple
  workers boot simultaneously.
- The "`SELECT existing → INSERT/UPDATE`" pattern in `create_session` /
  `update_contract` so two concurrent writers can't both pass the
  existence check.

## Why no ORM?

- The schema is one table with one opaque JSON column. An ORM would buy
  nothing and would obscure the validation semantics, which are the
  whole point of this module.
- Plain `sqlite3.connect()` keeps the dependency footprint at zero
  beyond `jsonschema`.
- All "interesting" structure already lives in the Pydantic `Contract` —
  putting an ORM in front of it would just give us a second source of
  truth for the schema.
