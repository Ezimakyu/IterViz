# 02 — Schemas and `update_node` (`backend/app/schemas.py` + `contract.py`)

This is the model + service layer for M4: the request/response schemas
that define the editable-field surface, and the `update_node` function
that mutates a contract in place and re-persists it.

## `NodeUpdateRequest` and `NodeUpdateResponse`

Both live in `backend/app/schemas.py` and are exported from `__all__`
so the API module can use them without touching the schema file again.

```python
class NodeUpdateRequest(BaseModel):
    """Body for ``PATCH /sessions/{session_id}/nodes/{node_id}``."""
    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = None
    responsibilities: Optional[list[str]] = None
    assumptions: Optional[list[Assumption]] = None


class NodeUpdateResponse(BaseModel):
    """Response for ``PATCH /sessions/{session_id}/nodes/{node_id}``."""
    model_config = ConfigDict(extra="allow", use_enum_values=True)

    node: Node
    fields_updated: list[str] = Field(default_factory=list)
    provenance_set: dict[str, str] = Field(default_factory=dict)
```

Why each field is the way it is:

- **`extra="forbid"` on the request.** A user editing the graph should
  not accidentally rename a node, change its kind, or repoint an edge.
  The forbid flag turns any attempt at sending `name`, `kind`, `id`, or
  any other structural field into a Pydantic 422. Tests exercise this:
  `test_patch_node_rejects_structural_fields` in `test_api.py` posts a
  body with `{"name": "..."}` and expects 422 with the offending key
  in `detail`.
- **`Optional[...] = None` on every editable field.** This is the
  PATCH semantic: only fields explicitly present (non-`None`) count as
  edits. Sending `{}` is a no-op and leaves the node untouched.
- **`fields_updated` and `provenance_set` on the response.** These
  let the frontend store know exactly which fields changed and what
  provenance they got, without diffing the previous contract. The
  store then merges `fields_updated` into `userEditedFields[nodeId]`
  for per-field highlighting in the popup.
- **`use_enum_values=True` on the response.** Without it the response
  would serialize `decided_by` as the enum object (`<DecidedBy.USER>`)
  in some code paths; this forces the JSON-friendly `"user"` string.

## `update_node()` in `contract.py`

The service function that backs the PATCH route:

```python
def update_node(
    session_id: str,
    node_id: str,
    updates: NodeUpdateRequest,
) -> tuple[Node, list[str], dict[str, str]]:
```

Behavior, in order:

1. **Resolve the session.** `get_session` raises
   `SessionNotFoundError` if the id is unknown — propagated up to the
   API layer where it becomes a 404.
2. **Find the node.** A linear scan over `contract.nodes`. If no node
   matches, raise `ValueError(f"node {node_id} not found in session {session_id}")`
   — also mapped to 404 in the API layer for consistency.
3. **Apply each editable field if it differs from the current value.**
   Equality is checked field-by-field:
   - `description`: simple `!=` on the new vs current string.
   - `responsibilities`: `list(updates.responsibilities) != list(node.responsibilities)`
     so element-by-element comparison ignores incidental sequence
     types.
   - `assumptions`: every entry in the new list is `model_copy`'d with
     `decided_by=DecidedBy.USER`, then `model_dump(mode="json")` on
     both sides drives the comparison so we don't get false positives
     from object identity.
   For each field that actually changed, push its name onto
   `fields_updated` and set `provenance_changes[name] = "user"`.
4. **If anything changed, flip `node.decided_by = DecidedBy.USER` and
   re-persist** via `update_contract`. This is the load-bearing
   guarantee for the Compiler: the edited node is now user-owned at
   the node level too, not just per-field. Then emit the
   `contract.node_updated` log line.
5. **If nothing changed, emit `contract.node_update_noop` at DEBUG
   level and return the node untouched.** No persistence call, no
   provenance flip.
6. **Return `(node, fields_updated, provenance_changes)`.**

## Structured logging

The structured log lines emitted from this layer:

```python
log.info(
    "contract.node_updated",
    extra={
        "session_id": session_id,
        "node_id": node_id,
        "fields_updated": ["description"],          # actual list
        "provenance_changes": {"description": "user"},
        "new_decided_by": "user",
    },
)
```

```python
log.debug(
    "contract.node_update_noop",
    extra={"session_id": session_id, "node_id": node_id},
)
```

These are the lines the M4 acceptance criteria call for under
*"Backend logs include `contract.node_updated`"*. Together with the
two new compiler log lines (`compiler.provenance_check_start` and
`compiler.uvdc_breakdown`), they give ops a complete trail from
"user clicked save" through "Compiler treated this node as
user-decided" to "UVDC went up by 1/25".

## Why assumption replacement marks every entry as `decided_by: user`

The user can't currently edit individual assumption objects from the
UI (the popup exposes description and responsibilities only), but the
backend supports replacing the whole list — both for symmetry with the
schema and because future UI work (M4.5 / M5) is expected to add a
list editor. The decision was: when the user replaces the list, every
entry — old or new — is now their choice. This is implemented with a
`model_copy(update={"decided_by": DecidedBy.USER})` rather than a
mutation so we don't accidentally edit shared objects, and so that the
provenance flag is set even if the frontend sent the entry with
`decided_by: agent` baked in.
