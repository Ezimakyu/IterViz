# 02 — Freeze, leaf detection, neighbor interfaces

This document covers the "static" half of the orchestrator — everything
that runs once, synchronously, before assignments fan out: locking the
contract, identifying which nodes are leaves, and snapshotting each
node's neighbor interfaces into the assignment payload.

All three pieces live in `backend/app/orchestrator.py` (lines 67–193).

## `freeze_contract(session_id) -> Contract`

Locks a verified contract for implementation. Three things happen:

1. **Status guard.** The function reads `session.contract.meta.status`,
   normalizes it (it round-trips through pydantic's `use_enum_values=True`
   so it can be either an enum or a string), and:
   - If it is already `verified`, log `orchestrator.already_frozen` and
     return the contract unchanged. **Idempotent.**
   - If it is anything other than `drafting`, raise
     `ValueError(f"Cannot freeze contract in status: {current_status}")`.
2. **Hash.** Computes
   `sha256(contract.model_dump_json(exclude_none=True))` and writes it
   into `meta.frozen_hash`. The hash is over the *current* JSON
   representation including the still-`drafting` status — that is fine
   because the only consumer is the user-facing fingerprint shown in
   the UI; it isn't used to detect tampering.
3. **Mutate + persist.** Sets `meta.status = VERIFIED`,
   `meta.frozen_at = utcnow()`, and `meta.version = (version or 1) + 1`,
   then calls `contract_svc.update_contract(session_id, contract)` which
   persists to SQLite via the M2 contract module.

The returned contract is the **persisted** one (re-read after update) so
the caller doesn't see stale fields if the persistence layer ever
modifies the contract on write.

### Why "status: verified" not "status: frozen"

The status taxonomy was extended in M5 but `verified` was reused as the
"frozen" state to avoid a migration. The downstream guards
(`create_assignments`, `implement_session`) check for `verified`, not a
new `frozen` value.

### Tested by

- `test_freeze_sets_status_and_hash` — after freeze the contract has
  `status == verified`, a non-empty `frozen_hash`, and a non-`None`
  `frozen_at`.
- `test_freeze_twice_is_idempotent` — calling `freeze_contract` a second
  time returns the same `frozen_hash`.

## `identify_leaf_nodes(contract) -> list[Node]`

Returns nodes with no outgoing `data` or `control` edges. The
implementation is a single pass:

```python
non_leaf_ids = set()
for edge in contract.edges:
    kind = edge.kind if isinstance(edge.kind, str) else edge.kind.value
    if kind in (EdgeKind.DATA.value, EdgeKind.CONTROL.value):
        non_leaf_ids.add(edge.source)
return [n for n in contract.nodes if n.id not in non_leaf_ids]
```

Two subtleties worth calling out:

- **`event` edges don't disqualify a leaf.** Asynchronous
  event-publication edges are explicitly excluded from
  `non_leaf_ids`, so a node that only emits events to others is still a
  leaf. The fixture in `test_identify_leaf_nodes_ignores_event_edges`
  pins this: with one `EVENT` edge `a → b`, both `a` and `b` come back
  as leaves.
- **Status is a string after pydantic round-trip.** The `isinstance`
  guard handles both enum and string forms because
  `Contract` uses `use_enum_values=True` which turns enums into raw
  strings on serialization but keeps them as enums on direct
  construction.

`identify_leaf_nodes` is **not** what `create_assignments` uses to pick
nodes — every node gets implemented. The helper is exposed for
downstream tooling that might want leaf-only execution and for
`AssignmentPayload`'s neighbor-interface metadata.

### Tested by

- `test_identify_leaf_nodes_returns_terminal` — UI → API → DB fixture;
  `Database` is the only leaf.
- `test_identify_leaf_nodes_handles_isolated` — a contract with edges
  but at least one disconnected node still returns that node as a leaf.
- `test_identify_leaf_nodes_ignores_event_edges` — described above.

## `get_neighbor_interfaces(node, contract) -> (incoming, outgoing)`

Builds the per-node view of "what data is flowing in and out of me",
returned as `(list[NeighborInterface], list[NeighborInterface])`. This
is what gets snapshotted into `AssignmentPayload.neighbor_interfaces`
so the subagent can see the declared payload schemas of its neighbors
without having to re-walk the contract.

For each edge:

- If `edge.target == node.id`: append a `NeighborInterface` from the
  source node into `incoming`.
- Else if `edge.source == node.id`: append one for the target node into
  `outgoing`.

Each `NeighborInterface` carries:

- `edge_id`, `node_id`, `node_name` (the *other* end of the edge)
- `payload_schema` (whatever the architect declared on the edge — may be
  `None`)

This is intentionally lightweight: no traversal beyond direct
neighbors, no inference of types from upstream-of-upstream nodes.

### Tested by

- `test_get_neighbor_interfaces_returns_in_and_out` — given a fixture
  where `API → Database`, the API node has zero incoming and one
  outgoing (`Database`).

## Why hash *after* setting `frozen_at` would be wrong

The order in `freeze_contract` is:

1. Compute `frozen_hash` from the current `model_dump_json`.
2. Write `frozen_hash` and `frozen_at` into `meta`.

If the order were reversed (write `frozen_at` first, then hash), every
freeze would produce a different hash because `frozen_at` is a wall-clock
timestamp. The current order means the hash represents the contract's
*content* at the moment of freeze, independent of when freeze happened.
This matters for the idempotency test: a second freeze would be a no-op
(it returns early via the status guard), but if it weren't, it would
still produce the same hash because the contract content is unchanged.
