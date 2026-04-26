# 05 — REST API and WebSocket

This document covers the HTTP and WS surface added in M5: 11 new REST
routes in `backend/app/api.py`, the WebSocket endpoint in
`backend/app/main.py`, and the `ConnectionManager` + `broadcast_*`
helpers in `backend/app/ws.py`.

## REST routes

All routes are mounted under the existing `/api/v1` prefix.

| Method | Path | Handler | Purpose |
| --- | --- | --- | --- |
| `POST` | `/agents` | `register_agent` | Register an external agent (returns `agent_id`) |
| `GET` | `/agents` | `list_agents` | List every registered agent (status auto-updates if stale) |
| `GET` | `/sessions/{session_id}/assignments?agent_id=...` | `get_assignment` | Poll for the next available (PENDING) assignment for `agent_id`; bumps the agent's heartbeat |
| `POST` | `/sessions/{session_id}/nodes/{node_id}/claim` | `claim_node` | Claim a node for an agent (verifies node exists *before* mutating state) |
| `POST` | `/sessions/{session_id}/nodes/{node_id}/status` | `report_node_status` | Report progress (broadcasts `node_progress`) |
| `POST` | `/sessions/{session_id}/nodes/{node_id}/implementation` | `submit_implementation` | Submit completed work (verifies node, completes assignment, updates contract, broadcasts `node_status_changed=implemented`) |
| `POST` | `/sessions/{session_id}/nodes/{node_id}/release` | `release_node` | Release a claimed node back to PENDING |
| `POST` | `/sessions/{session_id}/freeze` | `freeze_session` | Lock the contract (delegates to `orchestrator.freeze_contract`) |
| `POST` | `/sessions/{session_id}/implement` | `implement_session` | Create assignments + (internal mode only) schedule `run_implementation_internal` as a `BackgroundTask` |
| `GET` | `/sessions/{session_id}/generated` | `download_generated` | Stream a zip of the session's output dir; uses `BackgroundTask` to delete the temp file after the response is sent |

### Defensive ordering in `claim_node` and `submit_implementation`

Both routes verify the target node exists in the contract *before*
calling the assignments service. This was a Devin-Review-driven fix:
without the check, an unknown `node_id` in `claim_node` could leave an
agent marked `active`/bound to an assignment that never produced a
node-status broadcast, leaving the UI permanently waiting. The pattern:

```python
target_node = next((n for n in contract.nodes if n.id == node_id), None)
if target_node is None:
    return ClaimNodeResponse(success=False, error="Node not found")
# only NOW touch assignments / agents / WS
```

### `download_generated` — zip + temp-file cleanup + path-traversal guard

```python
@router.get("/sessions/{session_id}/generated")
def download_generated(session_id: str) -> FileResponse:
    try:
        output_dir = orchestrator_svc.get_generated_files_dir(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = Path(tmp.name); tmp.close()
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in output_dir.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(output_dir))

    return FileResponse(
        str(tmp_path),
        media_type="application/zip",
        filename=f"generated_{session_id}.zip",
        background=BackgroundTask(tmp_path.unlink, missing_ok=True),
    )
```

Two hardenings:

1. **Path-traversal guard** is in `get_generated_files_dir` (see
   `04-orchestrator-and-integration.md`). Without it, a request to
   `/api/v1/sessions/%2E%2E/generated` would zip
   `backend/generated/..` (i.e. the entire `backend/` tree) and leak
   source code, the SQLite database, and any keys checked into the
   repo.
2. **Temp-zip cleanup** uses `BackgroundTask(tmp_path.unlink,
   missing_ok=True)` so the OS temp directory doesn't accumulate one
   zip per download. This was the first Devin Review's "temp zip
   leak" fix.

## WebSocket endpoint — `/api/v1/sessions/{session_id}/stream`

Defined inline in `create_app` so it shares the FastAPI lifespan and
middleware:

```python
@app.websocket("/api/v1/sessions/{session_id}/stream")
async def _ws_stream(websocket: WebSocket, session_id: str) -> None:
    await ws_svc.manager.connect(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()       # drains pings
    except WebSocketDisconnect:
        pass
    finally:
        await ws_svc.manager.disconnect(session_id, websocket)
```

### `finally`-block disconnect

This was the first Devin Review's "WebSocket disconnect leak" fix.
Originally `disconnect` was called inside the `except WebSocketDisconnect`
block, so any *other* exception (e.g. a `RuntimeError` from a slow
client, a network reset that raised something other than
`WebSocketDisconnect`) left the connection registered in
`ConnectionManager._connections` forever. Moving it to `finally`
guarantees cleanup on any exit path.

### Server-to-client only

The endpoint receives text but throws it away. The protocol is
strictly server → client; clients don't need to send anything beyond
the initial WebSocket handshake. `receive_text()` is there only to
keep the connection alive and to surface a `WebSocketDisconnect`
exception cleanly when the client closes.

## `ws.py` — `ConnectionManager` + `broadcast_*` helpers

### Storage

```python
self._connections: dict[str, list[WebSocket]] = {}
self._lock = asyncio.Lock()
```

One list of WebSockets per `session_id`. Empty session lists are
removed on disconnect so the dict doesn't grow unbounded over
long-lived deployments.

### `connect`, `disconnect`, `broadcast`

- `connect`: `await websocket.accept()`, then under the lock append to
  the per-session list.
- `disconnect`: under the lock, remove the WS (idempotent — `try /
  except ValueError: pass`), and pop the session list when it's empty.
- `broadcast(session_id, message)`:
  1. Snapshot the list under the lock.
  2. `model_dump(mode="json")` + `json.dumps`.
  3. `await connection.send_text(data_str)` for each connection.
  4. Collect `Exception`-raising connections into `dead`, then
     `disconnect` each one. This is what self-heals against silently
     dropped client connections — the next broadcast prunes them.

### Broadcast helpers

Each helper wraps a single `WSMessage` subtype so callers don't
construct models inline:

| Helper | Message |
| --- | --- |
| `broadcast_node_status_changed(session, node_id, status, [agent_id, agent_name])` | `WSNodeStatusChanged` |
| `broadcast_node_claimed(session, node_id, agent_id, agent_name)` | `WSNodeClaimed` |
| `broadcast_node_progress(session, node_id, agent_id, progress, [message])` | `WSNodeProgress` |
| `broadcast_agent_connected(session, agent_id, agent_name, [agent_type])` | `WSAgentConnected` |
| `broadcast_implementation_complete(session, success, nodes_implemented, nodes_failed)` | `WSImplementationComplete` |
| `broadcast_integration_result(session, mismatches)` | `WSIntegrationResult` |
| `broadcast_error(session, error_msg, [details])` | `WSError` |

Every WS message is a discriminated union via `WSMessage = Annotated[
Union[...], Field(discriminator="type")]` so the frontend can
`switch(msg.type)` over a typed union.

### Tested by

- `test_connect_disconnect_lifecycle` — register one connection, then
  remove; underlying list is cleaned up.
- `test_broadcast_sends_to_all_connections` — three fake WS clients,
  each receives the same message.
- `test_broadcast_skips_other_sessions` — broadcasting to session A
  doesn't reach session B's connection.

## REST tests

API-level coverage for M5 lives in `backend/tests/test_api.py`:

- `test_register_and_list_agent` — POST `/agents` returns an id; that
  agent appears in `GET /agents`.
- `test_freeze_then_implement_external` — POSTs `/freeze`, then
  `/implement` in `external` mode, then walks the full external-agent
  protocol (claim → implementation submit) and asserts the zip output
  is produced.
- `test_implement_requires_frozen` — POST `/implement` on a drafting
  contract returns 400.
- `test_freeze_unknown_session_404`.
- `test_get_assignment_returns_null_when_no_session_assignments` — the
  polling endpoint returns `assignment=null` rather than 404 when a
  session simply has no work for the requesting agent.
