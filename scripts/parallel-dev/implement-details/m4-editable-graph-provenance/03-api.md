# 03 — API route (`backend/app/api.py`)

M4 adds exactly one new HTTP route. It lives in the same router as
M2/M3's session/verify/answers/refine routes and reuses the same
session-id path parameter convention.

## `PATCH /api/v1/sessions/{session_id}/nodes/{node_id}`

```python
@router.patch(
    "/sessions/{session_id}/nodes/{node_id}",
    response_model=NodeUpdateResponse,
)
def update_node_endpoint(
    session_id: str, node_id: str, body: NodeUpdateRequest
) -> NodeUpdateResponse:
```

The handler does three things:

1. Log the call (`api.update_node_called`) so we have a request-level
   audit even if `update_node` raises.
2. Delegate to `contract.update_node(session_id, node_id, body)`.
3. Log the result (`api.node_updated`) with the same `fields_updated`
   and `provenance_changes` that the response carries, then return a
   `NodeUpdateResponse`.

## Error mapping

| Source | HTTP | Body |
| --- | --- | --- |
| `SessionNotFoundError` | `404` | `{"detail": "session <id> not found"}` |
| `ValueError("node ... not found ...")` | `404` | `{"detail": "node <id> not found in session <sid>"}` |
| Pydantic `extra="forbid"` violation | `422` | standard FastAPI validation error with the offending key |
| Pydantic type / missing-field validation | `422` | standard FastAPI validation error |

Both "missing" cases fold to 404 because the response shape is the
same to the frontend: the resource isn't there. The 404 detail string
is just enough to disambiguate in the React DevTools / network panel
without surfacing internal state.

## Why `PATCH` and not `PUT`

PATCH is the right verb for *"update only the fields I sent"*. PUT
would imply replace-the-whole-node semantics, which is a footgun: a
client that omits `responsibilities` would silently delete them. PATCH
combined with `Optional[...] = None` on the Pydantic body means the
default mode is "keep existing values".

## Why the route is under `/sessions/{id}/nodes/{node_id}` and not `/contracts/...`

Sessions are the only persistence boundary in the system — there is no
standalone `/contracts/{id}` namespace. Anchoring node updates to a
session id matches the rest of the API:

- `POST /sessions` → create a contract
- `GET /sessions/{id}` → fetch
- `POST /sessions/{id}/compiler/verify` → run Compiler
- `POST /sessions/{id}/answers` → record decisions
- `POST /sessions/{id}/architect/refine` → refine
- **`PATCH /sessions/{id}/nodes/{node_id}` ← M4 new**

This also avoids any race where the user edits one revision of a
contract while a refine call is producing the next: both go through
the same `contract_svc.update_contract` persistence layer.

## Round-trip example (taken from the live test run)

Request:

```http
PATCH /api/v1/sessions/sess-3a.../nodes/dm-reader-svc HTTP/1.1
Content-Type: application/json

{
  "description": "Reads unread DMs from Slack since the last marker timestamp."
}
```

Response (200):

```json
{
  "node": {
    "id": "dm-reader-svc",
    "name": "DM Reader Service",
    "kind": "service",
    "decided_by": "user",
    "description": "Reads unread DMs from Slack since the last marker timestamp.",
    "responsibilities": [...],
    "assumptions": [...],
    "confidence": 0.62,
    "status": "drafted",
    ...
  },
  "fields_updated": ["description"],
  "provenance_set": {"description": "user"}
}
```

Backend log lines emitted in order (DEBUG=1):

```
api.update_node_called          session_id=sess-3a... node_id=dm-reader-svc
contract.node_updated           session_id=... node_id=dm-reader-svc
                                fields_updated=["description"]
                                provenance_changes={"description":"user"}
                                new_decided_by="user"
api.node_updated                session_id=... node_id=dm-reader-svc
                                fields_updated=["description"]
                                provenance_changes={"description":"user"}
```

Then on the next `Verify`:

```
compiler.provenance_check_start session_id=... total_nodes=8
                                user_decided_nodes=1
                                agent_decided_nodes=7
                                prompt_decided_nodes=0
compiler.uvdc_breakdown         session_id=... total=25 user_or_prompt=5
                                uvdc=0.20
```
