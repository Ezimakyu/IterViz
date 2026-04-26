# 04 — API and App Factory

## `app/api.py` — route handlers

Routes live under the `/api/v1` prefix. Handlers are intentionally thin:
they validate input, delegate to `architect` / `contract` services, and
serialize the result.

```python
router = APIRouter(prefix="/api/v1", tags=["sessions"])
```

### `POST /api/v1/sessions` → 201

- Body: `CreateSessionRequest(prompt: str, min_length=1, extra="forbid")`
- Action:
  1. `architect_svc.generate_contract(request.prompt)` — `ValueError`
     from the architect maps to **400 Bad Request**.
  2. `contract_svc.create_session(contract)` — persists.
- Response: `CreateSessionResponse(session_id, contract)` with HTTP 201.

### `GET /api/v1/sessions/{session_id}` → 200 / 404

- `contract_svc.get_session(session_id)` — `SessionNotFoundError` maps
  to **404 Not Found**.
- Response: `GetSessionResponse(contract)`.

### `POST /api/v1/sessions/{session_id}/architect/refine` → 200 / 404

- Body: `RefineRequest(answers: list[Decision], extra="forbid")`
- Action:
  1. Load existing session (404 on miss).
  2. `architect_svc.refine_contract(session.contract, request.answers)`.
  3. `contract_svc.update_contract(session_id, updated)`.
- Response:
  ```python
  RefineResponse(
      contract=persisted.contract,
      diff={
          "previous_version": session.contract.meta.version,
          "new_version":      persisted.contract.meta.version,
          "n_decisions":      len(persisted.contract.decisions),
      },
  )
  ```

`diff` is intentionally a small dict (not a structural diff) — the
frontend renders the new contract directly; `diff` is purely for
inspection in tests and logs.

## API request / response models (`app/schemas.py`)

Five M2-specific models extend the M1 schema without modifying any of
M1's existing models:

```python
ContractMeta = Meta  # back-compat alias

class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1)

class CreateSessionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    session_id: str
    contract: Contract

class GetSessionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    contract: Contract

class RefineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[Decision]

class RefineResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    contract: Contract
    diff: dict[str, Any] = Field(default_factory=dict)
```

`extra="forbid"` on requests gives FastAPI a free 422 if a client sends
unknown fields. `extra="allow"` on responses lets us add fields later
without breaking older clients.

## `app/main.py` — app factory

```python
def create_app() -> FastAPI: ...
app = create_app()  # uvicorn target: app.main:app
```

`create_app()` is the single entry point — never instantiate `FastAPI`
directly elsewhere — so middleware and lifespan stay consistent across
processes and tests.

### Lifespan (`_lifespan`)

```python
@asynccontextmanager
async def _lifespan(_app):
    contract_svc.init_db()
    log.info("app.startup", extra={"db_path": str(contract_svc.get_db_path())})
    try:
        yield
    finally:
        log.info("app.shutdown")
```

- Runs `init_db()` so the `sessions` table exists before the first
  request.
- Logs `app.startup` / `app.shutdown` with the active DB path so
  operators can confirm which database the process is using.

### CORS

```python
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEFAULT_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Vite's dev server runs on `5173`; both `localhost` and `127.0.0.1` are
included to avoid origin-mismatch surprises during local development.
The list is conservative — adding production origins later is one config
change.

### Request logging middleware

```python
@app.middleware("http")
async def _request_logger(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start) * 1000)
    log.info(
        "http.request",
        extra={
            "method":      request.method,
            "path":        request.url.path,
            "status":      response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response
```

Combined with the structured JSON logger from M1
(`backend/app/logger.py`), every request produces a single log line with
method / path / status / duration that downstream tooling can parse
directly.

### `/health`

Defined inline in `create_app()`, returns `{"status": "ok"}`. Kept under
the `meta` tag, intentionally unauthenticated, intentionally not under
`/api/v1` so probes don't have to track API versions.

## LLM seam (`app/llm.py` — `call_structured`)

M2 added `call_structured(response_model=…, system=…, user=…)` next to
M1's `call_compiler`. This is the single function the Architect uses, and
it's where `instructor` enforces Pydantic on the response. Highlights:

- Provider is resolved through `_resolve_provider` (env-driven; M1's
  helper).
- For Anthropic, `max_tokens` is forwarded; OpenAI defaults are inherited.
- Logs `llm call started` (debug, with system / user previews) and
  `llm call completed` (info, with `provider`, `model`, `response_model`,
  `duration_ms`) — `DEBUG=1` users see both lines.

Tests mock this single function and never touch real provider SDKs.

## Loaded prompt resolution (`load_prompt`)

```python
def load_prompt(name: str) -> str:
    path = Path(__file__).parent / "prompts" / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(...)
    return path.read_text(encoding="utf-8")
```

Used by `architect.py: _system_prompt()`. Future agents drop a
`prompts/<name>.md` file and call `load_prompt("<name>")`.
