# 02 — Architect Agent

The Architect is the only agent that ever sees the user's natural-language
prompt. It produces a complete `Contract` (defined in
`backend/app/schemas.py`) which downstream agents (Compiler, Subagents, …)
work from.

## Files

- `backend/app/architect.py` — Python module
- `backend/app/prompts/architect.md` — system prompt (loaded by name)

## Public surface

```python
def generate_contract(prompt: str) -> Contract: ...
def refine_contract(contract: Contract,
                    answers: Iterable[Decision]) -> Contract: ...
```

Both functions go through `app.llm.call_structured(response_model=Contract,
…)`, which is the single seam where `instructor` enforces the Pydantic
schema on the LLM response.

## `generate_contract(prompt)`

1. Reject empty / whitespace-only prompts with `ValueError` so the API
   layer can surface a 400 instead of generating a phantom contract.
2. Build the user message:
   ```
   User prompt:
   """
   <prompt>
   """

   Produce the full Contract JSON now. Required minimums: at least 3 nodes
   and at least 2 edges.
   ```
3. Call `call_structured(response_model=Contract, system=load_prompt("architect"),
   user=user_message)`.
4. Post-process the LLM's contract before returning it:
   - Generate `meta.id` if absent.
   - Inject the original prompt into `meta.prompt_history` (as a
     `PromptHistoryEntry(role="user", ...)`), de-duplicating against any
     entry the LLM may already have written.
   - Backfill `meta.created_at` and refresh `meta.updated_at` (UTC).
   - Force `meta.version = 1` for fresh contracts.
5. Log `architect.generate.complete` with `contract_id`, `n_nodes`, `n_edges`.

This guarantees the API can rely on `meta.prompt_history` containing the
verbatim prompt without trusting the model to do it.

## `refine_contract(contract, answers)`

The LLM does the heavy lifting (editing affected nodes/edges in place,
preserving ids, marking resolved fields `decided_by="user"`), but the
Python wrapper enforces three invariants regardless of what the model
returns:

1. **Every supplied answer ends up in `decisions[]`.** After the call we
   diff `{a.id for a in answers}` against `updated.decisions` and append
   any missing ones.
2. **`meta.id` is preserved** — never replaced by a fresh id even if the
   LLM emits one.
3. **`meta.version = old.version + 1`**, `meta.updated_at` is refreshed,
   `meta.created_at` is preserved.

The user message embeds both the previous contract and the new answers as
JSON so the model has everything it needs in one shot:

```
Refine the previous contract using the supplied user answers.
Preserve every node and edge id; update fields in place; mark
resolved fields decided_by="user" and bump their confidence.

Previous contract JSON: <…>
User answers JSON:      <…>

Return the full updated Contract JSON.
```

## System prompt (`prompts/architect.md`)

The prompt covers four things, in order:

1. **Role.** Architect is the only agent with prompt access; the Blind
   Compiler will never see the prompt, so every load-bearing decision
   must surface as graph structure.
2. **Inputs / outputs.** Free-text prompt (+ optional previous contract +
   decisions). Output is one JSON object that conforms to `Contract`.
3. **Hard requirements** (these match the Pydantic schema):
   - `meta.stated_intent` is one sentence.
   - `meta.prompt_history` always contains the original user prompt.
   - `nodes` ≥ 3, `edges` ≥ 2.
   - Every node has `id`, `name`, `kind`, `description`, 1–4
     `responsibilities`, `confidence`, `decided_by`, `status="drafted"`,
     plus 1–3 `assumptions`.
   - Edges of kind `data` / `event` populate `payload_schema` (object with
     `type`, `properties`, `required`).
   - `decided_by` semantics: `prompt` if user explicitly asked, `user` if
     it came from a recorded `Decision`, `agent` if inferred (with
     `load_bearing: true` on assumptions that change behavior if wrong).
   - Lower confidence (≤ 0.6) on nodes/edges that hide an unresolved
     decision; add a corresponding `open_questions` entry.
4. **Refinement mode.** When given a previous contract + decisions:
   update in place, preserve ids, set `decided_by="user"` and bump
   confidence on resolved fields, append answers to `decisions[]`, bump
   `meta.version`, do **not** invent new nodes unless an answer creates one.

### Few-shot examples

Three examples cover the surface area we care about:

1. **Small CLI tool** — happy path; shows minimal 3-node / 2-edge graph
   and `payload_schema` on a data edge.
2. **Slack bot** — multi-service example with at least one external node
   and event-kind edges, demonstrating `load_bearing` assumptions and
   `open_questions` for unresolved infra choices.
3. **Refinement pass** — same contract with a `Decision` flipping an
   open question to a concrete answer; demonstrates id preservation and
   `meta.version` increment.

Examples are kept under JSON fences (`jsonc`) and the prompt explicitly
notes "your own output must be the full JSON, no commentary" so models
don't leak markdown when responding for real.

## Why a separate prompt file?

`prompts/architect.md` is loaded by `app.llm.load_prompt("architect")` from
`app/prompts/<name>.md`. Three reasons it isn't inlined in Python:

- **Version control diffs are readable.** Reviewers can see prompt edits
  on their own line; they don't compete with code edits.
- **Future agents share the loader.** M3+ will add `compiler.md`,
  `subagent.md`, etc. — same loader, same conventions.
- **Tests don't accidentally mock the prompt.** Tests mock
  `call_structured`, not `load_prompt`, so prompt drift is caught the
  next time someone re-records a fixture.
