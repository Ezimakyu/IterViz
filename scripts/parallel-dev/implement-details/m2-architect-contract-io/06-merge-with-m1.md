# 06 — Merge resolution with M1

M1 (PR #4) and M2 (PR #3) were developed in parallel by separate agents
with no shared base beyond the architecture docs. M1 landed first and
introduced the canonical `Contract` schemas, structured logger, and
`call_compiler` LLM wrapper. M2 had been carrying its own draft copies
of those modules, which meant six files conflicted on merge.

This page documents the resolution so future cross-milestone merges
don't have to re-derive it.

## Conflicting files

| File | Source of truth | What was kept / changed |
| --- | --- | --- |
| `backend/app/__init__.py` | M1 | Keep M1 (their version exports the canonical schema names) |
| `backend/app/logger.py` | M1 | Keep M1 (structured JSON logger used by every module) |
| `backend/app/schemas.py` | M1 base + M2 *append* | Keep M1's full schema, append M2's API request/response models at the bottom |
| `backend/app/llm.py` | M1 base + M2 *append* | Keep M1's `call_compiler`, add `call_structured` + `load_prompt` next to it |
| `backend/pyproject.toml` | M1 | Keep M1; add `jsonschema` to `backend/requirements.txt` |
| `backend/tests/conftest.py` | merged | Keep M1's seed-contract / `mock_llm_client` fixtures, add M2's `make_sample_contract` / `sample_contract` / `temp_db` |

Single merge commit: `d037602` on `feat/m2-architect-contract-io`.

## Why M1 schemas win

- **`CompilerOutput` is M1's contract.** M3 will wire the Compiler
  through this exact type; switching to M2's draft would have forced a
  second migration later.
- **Enum types matter for the Compiler.** M1 defines `NodeKind`,
  `EdgeKind`, `DecidedBy`, `Severity`, `Verdict`, `ViolationType` as
  `Enum`s. M2's draft used plain strings; replacing M2's drafts with
  M1's enums was strictly additive (the architect prompt already enforces
  the same string values).
- **`extra="allow"` on most models.** This was already M1's convention,
  which made it safe for M2 to add new top-level models without touching
  the existing ones.

## What M2 had to adapt to M1's schemas

1. **Datetime, not ISO strings.** M1's `Meta` typed timestamps as
   `Optional[datetime]`. The architect was switched to use
   `datetime.now(timezone.utc)` (`_now()` helper) and to assign the
   datetime object directly:
   ```python
   contract.meta.created_at = contract.meta.created_at or _now()
   contract.meta.updated_at = _now()
   ```
   Pydantic serializes them to ISO-8601 on dump (`model_dump(mode="json")`),
   so the persisted JSON shape is unchanged.
2. **`Decision.id` is required.** Tests and refinement logic now pass an
   explicit `id=_new_id()` everywhere a `Decision` is constructed.
3. **`PromptHistoryEntry.timestamp` is a `datetime`.** Same change — pass
   `timestamp=_now()` instead of an ISO string.

## What M2 added on top of M1 (purely additive)

### `app/schemas.py`

Appended at the bottom (no edits to anything above):

- `ContractMeta = Meta` (back-compat alias for the M2 API code)
- `CreateSessionRequest`, `CreateSessionResponse`
- `GetSessionResponse`
- `RefineRequest`, `RefineResponse`

`__all__` updated to include the new names.

### `app/llm.py`

Appended next to M1's `call_compiler`:

- `load_prompt(name)` — reads `app/prompts/<name>.md`.
- `call_structured(*, response_model, system, user, ...)` — generic
  Pydantic-validated chat completion. Logs `llm call started` (debug)
  and `llm call completed` (info, with `provider`, `model`,
  `response_model`, `duration_ms`).

### `backend/requirements.txt`

Added `jsonschema` (used by `validate_contract_payload`). No other
dependency changes.

### `tests/conftest.py`

Two clearly-divided sections:

- `# M1 — Seed contracts + canned compiler client`
- `# M2 — Architect / persistence fixtures`

Both halves run independently; nothing in M1's tests needed any change.

## Verification after merge

- `pytest tests/ -v` → **39 passed in 1.83s** (16 M1 + 23 M2).
- `DEBUG=1 uvicorn app.main:app --reload` boots; `/health` returns
  `{"status": "ok"}`.
- The single merge commit (`d037602`) on `feat/m2-architect-contract-io`
  was the only thing pushed; PR #3 went from "conflicts with main" to
  "Mergeable" and merged cleanly.

## Notes for future cross-milestone merges

- **Always treat the earlier-merged milestone's schemas/logger/llm as
  canonical.** They're load-bearing for downstream milestones; the later
  PR rebases its own logic onto them.
- **Append API models at the bottom of `schemas.py`.** Keeps diffs
  readable and avoids touching enum / model definitions other milestones
  rely on.
- **Add new LLM helpers next to existing ones in `llm.py`.** Don't
  consolidate into a "mega" function; the per-agent helpers keep prompts
  and response models close together.
- **Split `conftest.py` by milestone with comments.** Different
  milestones produce different fixture flavors (canned-LLM vs
  hand-built); keeping them visually separated makes drift obvious.
