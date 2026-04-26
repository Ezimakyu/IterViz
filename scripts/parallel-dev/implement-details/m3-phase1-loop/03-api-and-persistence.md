# 03 — API surface + persistence

M3 adds three POST routes on top of M2's `POST /sessions` and
`GET /sessions/{id}`. They are the only HTTP entrypoints the frontend
needs to drive the full Phase 1 loop.

## Routes

### `POST /api/v1/sessions/{session_id}/compiler/verify`

- **Body:** none.
- **Response:** `CompilerResponse` — `{ verdict, violations[], questions[], intent_guess, uvdc_score, confidence_updates[] }`.
- **Side effect:** persists a `VerificationRun` on
  `contract.verification_log[]` via `add_verification_run(session_id, output)`.
- **Failure modes:**
  - `404` if `session_id` is unknown (`SessionNotFoundError`).
  - `503` if `verify_contract` raises `RuntimeError` (typically
    "Compiler unavailable: ANTHROPIC_API_KEY missing"). The frontend
    can swap to `verify_contract(use_llm=False)` mode if it sees this.

The handler is intentionally thin: load session, call
`compiler_svc.verify_contract(...)`, persist the run, serialize.

### `POST /api/v1/sessions/{session_id}/answers`

- **Body:** `AnswersRequest = { decisions: Decision[] }`.
- **Response:** `ContractResponse = { contract }` with the
  newly-appended decisions visible.
- **Side effect:** every `Decision` in the request body is appended to
  `contract.decisions[]` via `add_decision(session_id, decision)`. Each
  call bumps the contract version implicitly via `update_contract`.
- **Failure modes:** `404` if session is unknown; `422` if the body
  fails Pydantic validation (e.g. missing `question` or `answer`).

### `POST /api/v1/sessions/{session_id}/architect/refine`

- **Body:** `RefineRequest = { answers?: Decision[] }`.
- **Response:** `RefineResponse = { contract, diff? }`.
- **Side effect:** the Architect rewrites the contract; the new
  version is persisted via `update_contract`.
- **Body-optional contract:** when `answers` is omitted, the API uses
  whatever lives in `contract.decisions[]`. The frontend therefore
  doesn't have to track which decisions are "new since last refine"
  — the canonical sequence is *answers → refine*, and refine reads
  the latest persisted state.

The split between `/answers` and `/architect/refine` is deliberate.
Persisting decisions before kicking off the Architect means a
mid-flight 5xx during refine still leaves the user's answers safely
recorded. The frontend's `submitAnswersAndRefine` thunk only commits
the new contract to the Zustand store after refine succeeds, but the
backend keeps the answer history regardless.

## Persistence helpers (`backend/app/contract.py`)

Two new helpers were added on top of M2's CRUD layer:

### `add_decision(session_id, decision)`

```python
def add_decision(session_id: str, decision: Decision) -> Session:
    session = get_session(session_id)            # 404 if unknown
    session.contract.decisions.append(decision)
    update_contract(session_id, session.contract)
    return get_session(session_id)
```

`Decision` carries `id`, `question`, `answer`, `answered_at`,
`affects[]`, `source_violation_id`. The `source_violation_id` field is
optional but populated by the frontend when the user answers a
specific question card — useful for audit and for the LLM-free
deterministic-suppression path.

### `add_verification_run(session_id, compiler_output)`

```python
def add_verification_run(session_id: str, output: CompilerOutput) -> Session:
    session = get_session(session_id)
    run = VerificationRun(
        id=_new_id(),
        run_at=_now_iso(),
        verdict=output.verdict,
        violations=output.violations,
        questions=output.questions,
        intent_guess=output.intent_guess,
        uvdc_score=output.uvdc_score,
    )
    session.contract.verification_log.append(run)
    update_contract(session_id, session.contract)
    return get_session(session_id)
```

`VerificationRun` is the audit trail: each Verify click produces one
entry, ordered by `run_at`. The integration test
`test_verification_log_persisted` covers this round-trip via the API.

### Default-empty fields

`Contract` Pydantic models initialise `decisions: list[Decision] = []`
and `verification_log: list[VerificationRun] = []`. Sessions created
under M2 (which never wrote either field) round-trip cleanly through
M3's helpers because the JSON payload is deserialised into the new
default empty list.

## Threading + transactional model

Inherited unchanged from M2:

- A single `sqlite3` connection per request is opened and closed
  inside each helper.
- Every write is `Pydantic-validated → JSON-Schema-validated →
  written` in one statement.
- Reads re-validate so a manually-edited DB row never produces an
  invalid `Contract` inside the app.
- `set_db_path()` is exposed for tests; the integration tests use
  `tmp_path / "test.db"` to keep state isolated.

There is no row-level locking. The Phase 1 loop is single-writer in
practice (one user driving one session via the frontend) and the M3
demo does not parallelise refines. This is the TOCTOU comment from
Devin Review — acknowledged as a follow-up rather than a blocker for
the demo.
