# 05 — Tests and Acceptance

Run from `backend/`:

```bash
conda activate glasshouse
pytest tests/ -v
```

Result on the merged tree: **39 passed in 1.83s** (16 from M1 + 23 from M2).

## Layout

```
backend/tests/
├── __init__.py
├── conftest.py          # M1 + M2 fixtures, side-by-side
├── test_schemas.py      # M1
├── test_llm.py          # M1
├── test_compiler.py     # M1
├── test_contract.py     # M2 — persistence
├── test_architect.py    # M2 — agent
└── test_api.py          # M2 — HTTP surface
```

## Fixtures (`conftest.py`)

The merged file keeps M1's compiler-oriented fixtures and adds M2's
contract-oriented ones with a clear divider:

**M1 — compiler / schema:**
- `seed_contracts_dir` — `Path` to `scripts/seed_contracts`.
- `sample_valid_contract` — parsed `valid_simple.json`.
- `sample_invalid_contracts` — every other seeded contract, keyed by stem.
- `mock_llm_client` / `mock_llm_client_failing` — canned `CompilerOutput`
  via `CannedLLMClient.chat.completions.create`.

**M2 — architect / persistence:**
- `make_sample_contract(prompt=...)` — factory returning a hand-built
  `Contract` with 3 nodes (UI, API, store) and 2 edges (UI→API data
  edge, API→store data edge), `meta.version=1`, `decisions=[]`.
- `sample_contract` — fixture wrapper around `make_sample_contract()`.
- `temp_db` — yields a `Path` to a per-test SQLite file. Implementation:
  ```python
  @pytest.fixture
  def temp_db(tmp_path: Path) -> Iterator[Path]:
      db_path = tmp_path / "test.db"
      contract_svc.set_db_path(db_path)
      try:
          yield db_path
      finally:
          contract_svc.set_db_path(None)
  ```
  Tests that touch SQLite take this fixture; the rest of the suite is
  unaffected.

The `_new_id()` helper is shared between `conftest.py` and the M2
modules so test contracts and production contracts use the same UUID
shape.

## `test_contract.py` (persistence — 6 tests)

Covers the full CRUD plus the validation pipeline:

- `test_create_session_persists` — round-trip insert + read.
- `test_get_session_missing_raises` — `SessionNotFoundError`.
- `test_create_session_duplicate_raises` — second insert with same
  `meta.id` → `ContractValidationError`.
- `test_update_contract_persists_changes` — bumps `meta.version`,
  `updated_at` advances.
- `test_validate_contract_rejects_garbage` — `{"foo": 1}` and a malformed
  JSON string both raise `ContractValidationError`.
- `test_list_sessions` — N inserts → N rows ordered by `created_at`.
- `test_temp_db_isolated` — sanity check that `temp_db` does not bleed
  into the default DB path.

## `test_architect.py` (agent — 4 tests)

The architect tests **never** call out to real LLM providers. The mocking
pattern:

```python
def fake_call_structured(*, response_model, system, user, **_):
    assert response_model is Contract
    return make_sample_contract(prompt="…")  # deterministic

@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setattr(architect, "call_structured", fake_call_structured)
```

Tests:

- `test_generate_contract_basic` — non-empty prompt → contract with
  `meta.prompt_history[0].content == prompt` and `len(nodes) >= 3`,
  `len(edges) >= 2`.
- `test_generate_contract_rejects_empty` — empty / whitespace prompt →
  `ValueError`.
- `test_refine_contract_appends_answers_and_bumps_version` — ensures
  `meta.version` increments by 1 and every supplied answer ends up in
  `decisions[]` even if the mocked LLM forgets to copy it.
- `test_refine_contract_does_not_drop_pre_existing_decisions` — calling
  `refine_contract` twice with the same answers does not produce
  duplicates (deduplicated by `Decision.id`).

## `test_api.py` (HTTP surface — 6 tests)

Uses FastAPI's `TestClient`. The `client` fixture:

- Spins up a fresh app with `create_app()`.
- Points `contract_svc` at a `temp_db`.
- Patches `architect.call_structured` so endpoints don't hit the network.

Tests:

- `test_health` — `GET /health` returns `{"status": "ok"}` (200).
- `test_post_sessions_returns_201_and_contract` — creates a session,
  asserts 201 + `len(nodes) >= 3` + `len(edges) >= 2`.
- `test_post_sessions_then_get` — creates, then `GET` returns the same
  contract by id.
- `test_get_unknown_session_404` — unknown session id → 404.
- `test_post_sessions_empty_prompt_422` — missing / empty `prompt` →
  422 from Pydantic.
- `test_refine_endpoint_round_trip` — creates session, posts an answer,
  asserts `diff["new_version"] == diff["previous_version"] + 1`,
  asserts the answer is reflected in the persisted contract.
- `test_refine_unknown_session_404` — refine on missing id → 404.

## Acceptance-criteria mapping

| Criterion (from M2 prompt) | Verified by |
| --- | --- |
| `pytest tests/ -v` passes | full run, 39 passed |
| `uvicorn app.main:app --reload` starts server | manual `uvicorn` boot; `/health` 200 |
| `POST /sessions` with prompt returns valid Contract JSON | `test_post_sessions_returns_201_and_contract` |
| Contract has ≥ 3 nodes, ≥ 2 edges | same test (asserted explicitly) |
| `GET /sessions/{id}` returns same contract | `test_post_sessions_then_get` |
| `DEBUG=1` shows LLM call timing in logs | `call_structured` emits `llm call completed` with `duration_ms`; `_request_logger` emits `http.request` with `duration_ms` |
