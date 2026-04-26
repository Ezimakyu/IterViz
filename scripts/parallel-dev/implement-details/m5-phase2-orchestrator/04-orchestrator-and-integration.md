# 04 — Orchestrator: assignment fan-out, internal subagent loop, integration pass

This document covers the "dynamic" half of `backend/app/orchestrator.py`
— the bits that actually move work through the system after Freeze:

1. `create_assignments` — fan out one assignment per node (idempotent).
2. `_run_subagent` — call the LLM (or fall back) to implement one node.
3. `run_implementation_internal` — sequentially walk every assignment.
4. `run_integration_pass` — verify edge schemas vs actual exports.
5. `get_generated_files_dir` — path-traversal-hardened lookup.

## `create_assignments(session_id) -> list[Assignment]`

```
status guard: must be VERIFIED (otherwise ValueError)
    │
    ▼
existing = get_assignments_for_session(session_id)
if existing: return existing            ←── idempotency
    │
    ▼
for node in contract.nodes:
    inc, out = get_neighbor_interfaces(node, contract)
    create_assignment(session_id, node, contract, inc, out)
```

### Why "every node, not just leaves"

`identify_leaf_nodes` is exposed but `create_assignments` deliberately
implements every node. The demo wants to show all six rings flipping
green; if only leaves were implemented, non-leaf nodes would stay
"drafted" forever and the integration pass would refuse to compare
their actual interfaces against declared edge schemas.

### Idempotency

The `if existing: return existing` short-circuit was added in response
to a Devin Review pass that flagged duplicate assignment creation when
the user clicks **Implement** twice (or when external mode is started
twice). Without it, the second call fans out a second set of
assignments, but `_find_by_node_locked` (used by `claim_assignment`,
`complete_assignment`, etc.) only ever finds the first match — so the
duplicates would silently accumulate as unreachable PENDING records
visible in `get_available_assignments`.

The chosen strategy is "return existing" rather than "transition status
to IMPLEMENTING for both modes" because external mode needs the
contract to remain in `verified` state while external agents poll and
claim — flipping to `IMPLEMENTING` would prematurely lock new claims
out of `get_available_assignments`.

Tested by `test_create_assignments_is_idempotent`.

## `run_implementation_internal(session_id) -> None`

Sequential, by design, for demo simplicity. The structure:

```
contract.meta.status = IMPLEMENTING; persist

for assignment in get_assignments_for_session(session_id):
    node = assignment.payload.node
    claimed = claim_assignment(session_id, node.id, "internal")
    if claimed is None: continue                     ← skip if not claimable
    broadcast(node_status_changed=in_progress)
    update node.status in contract; persist

    try:
        impl = await _run_subagent(assignment)        ← LLM or mock
        write impl.files into generated/<session>/<node>/
        complete_assignment(...)
        update node.status=implemented; persist
        broadcast(node_status_changed=implemented)
        nodes_implemented++
    except Exception:
        fail_assignment(...)
        update node.status=failed; persist
        broadcast(node_status_changed=failed)
        nodes_failed++

mismatches = await run_integration_pass(session_id)

contract.meta.status = COMPLETE; persist
write generated/<session>/contract.json

broadcast(implementation_complete{success=nodes_failed==0, ...})
```

### `claim_assignment` before `_run_subagent`

This was a bug caught during the first Devin Review pass: the original
loop went straight from `get_assignments_for_session` to `_run_subagent`
to `complete_assignment`, never claiming. `complete_assignment` requires
`assigned_to == agent_id` (so external agents can't overwrite each
other's work), so internal completions silently failed and assignments
stayed `PENDING` forever. The fix is the explicit
`assignments_svc.claim_assignment(session_id, node.id, "internal")`
between the broadcast and the subagent call.

### Path-traversal sanitization on subagent filenames

LLM output is *not* trusted. Each `impl["files"][i]["filename"]` is
funnelled through:

```python
safe_name = Path(str(raw_name)).name or f"file_{i}.py"
```

`Path(...).name` strips every directory component, so an LLM that
returns `"../../etc/evil.py"` writes `evil.py` into the per-node output
dir, never escapes. This is regression-tested by
`test_internal_run_marks_assignments_completed`, which feeds a
malicious filename through a monkeypatched `_run_subagent` and asserts
that every resulting file path resolves under the generated root.

### `contract.meta.status` transitions

The internal loop walks the contract through three statuses:

```
verified  →  implementing  →  complete
            (set before     (set after the
             the loop)       integration pass)
```

`COMPLETE` is set *after* `run_integration_pass` so the contract.json
that gets written into the output directory captures the final state
including all `Implementation` records and (if any) integration
mismatches.

## `_run_subagent(assignment) -> dict`

The LLM call:

- Loads the system prompt from `backend/app/prompts/subagent.md` via
  `llm.load_prompt("subagent")`. Falls back to a default sentence if
  the file is missing.
- Builds a user message containing the node's name / kind /
  description / responsibilities, the `incoming` and `outgoing`
  `NeighborInterface` lists serialized as JSON, and the contract's
  `meta.stated_intent`.
- Calls `llm.call_structured(response_model=_SubagentOutput, ...)` via
  `asyncio.to_thread` (the LLM client is sync).
- `_SubagentOutput` is `extra="allow"` so the LLM can include extra
  fields (e.g. `tests`, `dependencies`) without breaking the parse.

### Mock fallback

Wrapped in `try / except Exception`. On any failure (no API key, rate
limit, network, parse failure) the function logs
`orchestrator.subagent_llm_failed` and returns a deterministic mock:

```python
{
  "files": [{"filename": f"{safe_module}.py", "content": "<stub with main()>"}],
  "exports": ["main"],
  "imports": [],
  "public_functions": [{"name": "main", "signature": "def main() -> None"}],
  "notes": "Mock implementation (LLM unavailable).",
}
```

This was a hard requirement for the demo: the recorded E2E run
completed end-to-end with no `ANTHROPIC_API_KEY` configured, producing
small but well-formed Python stubs for every node.

## `run_integration_pass(session_id) -> list[IntegrationMismatch]`

After every node is either implemented or failed, this pass walks
every `DATA` / `EVENT` edge:

- Skip edges whose source or target node has no `implementation` (i.e.
  failed nodes). They are not flagged again — the original failure
  already shows up via `node_status_changed=failed`.
- If `edge.payload_schema` is non-empty *and* the source's
  `actual_interface.exports` is empty, append an
  `IntegrationMismatch{severity=warning}` describing the gap.

The pass intentionally stays weak — string-name match, no type
comparison — so the demo can complete green. The `IntegrationMismatch`
records get broadcast via `broadcast_integration_result` so the UI
surfaces them once richer checks are added in M6.

## `get_generated_files_dir(session_id) -> Path`

Hardened lookup behind `GET /api/v1/sessions/{id}/generated`:

```python
generated_root = get_generated_dir().resolve()
candidate = (generated_root / session_id).resolve()
if candidate != generated_root and generated_root not in candidate.parents:
    raise ValueError(f"Invalid session id: {session_id}")
if candidate == generated_root:
    raise ValueError(f"Invalid session id: {session_id}")
if not candidate.exists():
    raise ValueError(f"No generated files for session {session_id}")
return candidate
```

Three guards in order:

1. `candidate` must sit strictly below `generated_root` — rejects
   `..`, `../sibling`, absolute paths like `/etc`.
2. `candidate` cannot equal the root itself — rejects an empty
   session_id that resolves to the root and would zip the entire
   generated tree.
3. The directory must actually exist on disk — preserves the original
   404 behavior for unknown sessions.

Regression-tested by `test_get_generated_files_dir_rejects_traversal`,
which asserts each of `..`, `../sibling`, `../../etc`, and `/etc`
raises `ValueError`. See `08-bugs-found-and-fixed.md` § "Path
traversal in `download_generated`" for the exploit and history.
