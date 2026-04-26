# 03 — Agents and assignments

This document covers the two in-memory registries that mediate Phase 2
work distribution:

- `backend/app/agents.py` — who is connected and what they're doing.
- `backend/app/assignments.py` — what work units exist and what state
  they're in.

Both modules are deliberately in-memory dicts protected by a
`threading.Lock`. M5 is a hackathon-shaped slim demo path; production
would replace these with SQLite (mirroring `app.contract`) and likely
move the WebSocket connection registry to Redis.

## `agents.py` — external agent registry

### Data model

`Agent` (in `schemas.py`):

| Field | Type | Notes |
| --- | --- | --- |
| `id` | `str` | UUID4, generated on register |
| `name` | `str` | Caller-supplied display name |
| `type` | `AgentType` | `devin` / `cursor` / `claude_code` / `custom` |
| `registered_at` | `datetime` | Set on register |
| `last_seen_at` | `datetime` | Bumped by `get_agent` / `heartbeat` / status / assignment changes |
| `status` | `AgentStatus` | `idle` / `active` / `disconnected` |
| `current_assignment` | `Optional[str]` | Set by `set_agent_assignment` |

### Stale detection

`DISCONNECT_THRESHOLD = timedelta(seconds=60)`. Every read path
(`get_agent`, `list_agents`) calls `_check_status(agent)` while
holding the lock. If `now - last_seen_at > 60s` and the agent isn't
already marked `DISCONNECTED`, the function flips its status and logs
`agents.disconnected`. There is no background task — staleness is
recomputed lazily on every read, which keeps the module dependency-free.

### Heartbeats

`get_agent` and `heartbeat` (which is just an alias) both bump
`last_seen_at` to `utcnow()`. External agents are expected to call
`POST /api/v1/agents/{id}` (which routes to `get_agent` indirectly via
the agent listing) at least every 60 seconds to stay marked `idle` or
`active`.

### Tested by

- `test_register_agent_assigns_id_and_idle_status` — UUID id, `IDLE`
  status, `registered_at` ≈ `last_seen_at`.
- `test_get_agent_updates_last_seen` — `last_seen_at` advances after a
  read.
- `test_get_agent_unknown_returns_none`.
- `test_list_agents_returns_all`.
- `test_disconnect_after_threshold` — monkeypatches `last_seen_at` to
  more than 60s ago and asserts `DISCONNECTED`.
- `test_set_agent_status_changes_status`.
- `test_set_agent_assignment_marks_active` — binding an
  assignment id flips status to `ACTIVE`; passing `None` flips back to
  `IDLE`.

## `assignments.py` — per-node work units

### Storage shape

```python
_assignments: dict[str, dict[str, Assignment]] = {}
# session_id -> { assignment_id -> Assignment }
```

This nested-dict layout means `get_assignments_for_session` is O(n) in
the session's assignments (not in the global count) and
`clear_session` is O(1).

### Lifecycle

```
create_assignment       PENDING (assigned_to=None)
        │
        │ claim_assignment(node_id, agent_id)
        ▼
        IN_PROGRESS (assigned_to=agent_id, assigned_at=now)
        │
        ├── complete_assignment(node_id, agent_id, files, actual_interface)
        │       └─→ COMPLETED (result populated)
        ├── fail_assignment(node_id)
        │       └─→ FAILED
        └── release_assignment(node_id, agent_id)
                └─→ PENDING (assigned_to=None)
```

### `_find_by_node_locked` — the TOCTOU fix

Originally `claim_assignment` looked the assignment up via
`get_assignment_for_node` (which acquires the lock, returns, releases),
then re-acquired the lock to mutate. That gave a window where two
concurrent agents could each see the same `PENDING` assignment and
both transition it to `IN_PROGRESS`.

The fix is `_find_by_node_locked`: a private helper that does the
same lookup but **assumes the caller already holds `_lock`**. Every
mutating function (`claim_assignment`, `complete_assignment`,
`release_assignment`, `fail_assignment`) does its lookup + state check
+ mutation in a single `with _lock:` block via this helper. This is
covered by `test_double_claim_returns_none`.

### `complete_assignment` ownership check

`complete_assignment` returns `None` (and logs
`assignments.complete_wrong_agent`) if the assignment's `assigned_to`
doesn't match the agent submitting work. This prevents one agent from
overwriting another's claimed assignment via the REST API.
`test_complete_wrong_agent_fails` pins this: agent A claims, agent B
calls complete with the same node_id, the call returns `None`, and
the assignment stays `IN_PROGRESS` under A.

### Status enums

`AssignmentStatus` is `pending | in_progress | completed | failed`.
The orchestrator and the WebSocket layer both compare against the enum's
`.value` because pydantic's `use_enum_values=True` flattens enums to
strings on serialization.

### Tested by

- `test_create_assignment_starts_pending`
- `test_get_available_filters_by_status` — only `PENDING` shows up in
  `get_available_assignments`.
- `test_claim_marks_in_progress`
- `test_double_claim_returns_none` — TOCTOU regression.
- `test_complete_records_implementation` — completion writes
  `assignment.result.implementation.file_paths` etc.
- `test_complete_wrong_agent_fails` — ownership check.
- `test_release_resets_to_pending`.
