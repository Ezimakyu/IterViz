# 01 — Overview

## Where M4 sits in the system

M4 is the milestone that turns the Architect-drafted contract into a
**living artifact** the user owns. Before M4 the user could only refine
a contract by answering questions on the QuestionPanel; load-bearing
fields stayed `decided_by: agent` until that loop produced an explicit
`Decision`. M4 lets the user click any node's description or
responsibilities directly on the graph, edit it inline, and have the
Compiler immediately treat that field — and the node it lives on — as
user-decided so it stops asking questions about it. The User-Visible
Decision Coverage (UVDC) score reflects the change on the next Verify.

```
                     M3 already in place
                     ───────────────────
                     POST /sessions      → Contract v1
                     POST /verify        → questions, UVDC
                     POST /answers       → Decision[]
                     POST /architect/refine → Contract v2
                                                │
                                                ▼
              ┌──────────────────────────────────────┐
              │ User clicks a node, opens popup      │
              │ Sees description, responsibilities   │
              └──────────────┬───────────────────────┘
                             │ click description
                             ▼
              ┌──────────────────────────────────────┐
              │ NodeDetailsPopup → textarea          │   M4 new
              │ blur / Cmd+Enter to commit           │
              └──────────────┬───────────────────────┘
                             │ updateNodeField thunk
                             ▼
        PATCH /api/v1/sessions/{id}/nodes/{node_id}     M4 new
                             │
                             ▼
                contract.update_node(...)               M4 new
            ┌────────────────┴─────────────────────────┐
            │ Apply non-None fields                    │
            │ Tag fields_updated[] in provenance_set   │
            │ Flip node.decided_by → user              │
            │ Replace assumptions with decided_by=user │
            │ Persist contract; emit                   │
            │   contract.node_updated                  │
            └────────────────┬─────────────────────────┘
                             │ NodeUpdateResponse
                             ▼
              ┌──────────────────────────────────────┐
              │ Frontend store: previousContract =   │
              │ contract; userEditedFields[id] +=    │
              │ fields_updated; node.decided_by      │
              │ refreshed                            │
              └──────────────┬───────────────────────┘
                             │ click Verify again
                             ▼
        POST /sessions/{id}/compiler/verify
                             │
                             ▼
            verify_contract(contract)                   M4 extends M3
            ┌────────────────┴──────────────────────┐
            │ compiler.provenance_check_start log   │
            │ INV-007 + _provenance_violations skip │
            │   any node/edge with decided_by=user  │
            │ compute_uvdc() now counts user-tagged │
            │   fields → score rises monotonically  │
            │ compiler.uvdc_breakdown log line      │
            └────────────────┬──────────────────────┘
                             │ CompilerOutput
                             ▼
              ┌──────────────────────────────────────┐
              │ Coverage % strictly ↑ if a previously│
              │ agent-decided node was edited        │
              │ QuestionPanel: no question references │
              │ the edited node                      │
              │ NodeCard: blue ring + USER badge     │
              │ Provenance view toggle dims others   │
              └──────────────────────────────────────┘
```

## Design choices

**Provenance is a node-level identity, not just a field-level tag.**
When the user edits *any* load-bearing field on a node, the entire node
becomes user-owned (`decided_by` flips to `user`). The Compiler stops
asking about it — about its kind, about its agent-tagged assumptions,
about its outgoing edges' provenance. The justification: if the user
took the time to write the description, they have signed off on the
node's existence. This also matches how UVDC is counted: nodes are the
unit of "decided by" credit. Per-field tracking is layered on top in
the frontend store as `userEditedFields` so we can render the blue
left-border and the `USER-EDITED` header badge, but the source of truth
for the Compiler is `node.decided_by`.

**Editable fields are deliberately small.** Only `description`,
`responsibilities`, and `assumptions` are accepted on the PATCH body.
Structural fields (`id`, `name`, `kind`) are bookkeeping that drives
the graph's layout and identity, and editing them without renumbering
edges is not what M4 is about. Pydantic's `extra="forbid"` config
rejects them with a 422 so the frontend cannot accidentally send them.

**No-ops do not flip provenance.** Setting `description` to its
existing value is silently ignored. Doing otherwise would let an
accidental click-then-blur permanently mark a node as user-decided
even when the user didn't actually change anything.

**Already-answered suppression composes with provenance skip.** M3's
`_already_answered` filter still runs after `_provenance_violations`
and INV-007 are computed; an edited node short-circuits before that
filter ever sees its violations. This means UVDC monotonicity is a
strict guarantee: editing a node can only ever increase the user's
share of decided fields, never decrease it (proved by
`test_uvdc_monotonic_after_user_edit` in `test_compiler.py`).

**The provenance view is purely cosmetic.** It is a frontend-only
toggle on `useContractStore.provenanceView` that adds `opacity-60` to
non-user-edited nodes and shows a small legend. It does not call the
backend, does not change UVDC, does not filter the question list. It
is the "where am I in this contract?" lens.

## Files touched

```
backend/app/schemas.py                        +34
backend/app/contract.py                       +88
backend/app/api.py                            +53
backend/app/compiler.py                       +106 / -2
backend/tests/test_contract.py                +176
backend/tests/test_api.py                     +119
backend/tests/test_compiler.py                +156
frontend/src/api/client.ts                    +33
frontend/src/state/contract.ts                +69
frontend/src/components/NodeDetailsPopup.tsx  +225 / -19
frontend/src/components/NodeCard.tsx          +20
frontend/src/components/Graph.tsx             +39
                                       ─────────────
                                       +1118 / -21
```
