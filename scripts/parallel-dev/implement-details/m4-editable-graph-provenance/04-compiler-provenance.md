# 04 — Compiler updates (`backend/app/compiler.py`)

M4 leaves the structural invariants `INV-001..INV-006` and the
ranking + 5-question cap untouched. The changes concentrate on three
spots:

1. **Provenance skip** in `_provenance_violations` — nodes/edges where
   `decided_by == "user"` no longer produce provenance violations.
2. **INV-007 exemption** — load-bearing assumptions hanging off a
   user-decided node are no longer surfaced as questions.
3. **New structured logs** — `compiler.provenance_check_start`,
   `compiler.node_provenance_detail`, and `compiler.uvdc_breakdown`
   give ops + frontend a complete view of how provenance moved each
   verify pass.

UVDC's formula is unchanged; what changed is that user edits now feed
into the numerator because `update_node` flips `decided_by` to `user`.

## `_provenance_violations` — the user-decided skip

Before M4 every node and edge with `decided_by == "agent"` produced a
`PROVENANCE` violation. The M4 version short-circuits at the top of
each loop:

```python
for node in contract.nodes:
    if _enum_value(node.decided_by) == "user":
        continue            # M4: user has signed off on this node
    if _enum_value(node.decided_by) == "agent":
        out.append(Violation(... type=ViolationType.PROVENANCE ...))

    for assumption in node.assumptions:
        if assumption.load_bearing and _enum_value(assumption.decided_by) == "agent":
            out.append(Violation(... PROVENANCE ...))

for edge in contract.edges:
    if _enum_value(edge.decided_by) == "user":
        continue
    if _enum_value(edge.decided_by) == "agent":
        out.append(Violation(... PROVENANCE ...))
```

The skip is at the node/edge level, not per-field. As described in
`01-overview.md`, that is intentional: "the user took the time to edit
this node, stop pestering them about it" applies to the whole
element, including its agent-tagged assumptions. INV-007 follows the
exact same rule, so the two stay in sync.

## INV-007 — provenance-aware version

```python
def check_inv007_dangling_assumptions(contract: Contract) -> list[Violation]:
    """INV-007: load_bearing & decided_by=agent assumptions must surface a question.

    M4 provenance behavior: user-decided nodes/edges are exempt entirely.
    """
    out: list[Violation] = []

    def _check(element_id, element_name, assumptions, open_questions):
        for a in assumptions or []:
            if not a.load_bearing:
                continue
            if _enum_value(a.decided_by) != "agent":
                continue
            if open_questions:
                continue
            out.append(Violation(... INV-007 ...))

    for node in contract.nodes:
        if _enum_value(node.decided_by) == "user":
            continue                 # ← M4 addition
        _check(node.id, node.name, node.assumptions, node.open_questions)

    by_id = {n.id: n for n in contract.nodes}
    for edge in contract.edges:
        if _enum_value(edge.decided_by) == "user":
            continue                 # ← M4 addition
        ...
```

## `compiler.provenance_check_start` log line

Emitted exactly once per `verify_contract` call, just before the
deterministic invariants run:

```python
user_decided_nodes = sum(
    1 for n in contract.nodes if _enum_value(n.decided_by) == "user"
)
agent_decided_nodes = sum(
    1 for n in contract.nodes if _enum_value(n.decided_by) == "agent"
)
prompt_decided_nodes = sum(
    1 for n in contract.nodes if _enum_value(n.decided_by) == "prompt"
)
log.info(
    "compiler.provenance_check_start",
    extra={
        "session_id": contract.meta.id,
        "total_nodes": len(contract.nodes),
        "user_decided_nodes": user_decided_nodes,
        "agent_decided_nodes": agent_decided_nodes,
        "prompt_decided_nodes": prompt_decided_nodes,
    },
)
```

This is the line the M4 acceptance criteria call out: between two
verifies, `user_decided_nodes` should grow by exactly the number of
nodes the user edited (or the number of nodes whose assumptions the
user replaced). The end-to-end run saw it move from `0 → 1` after
editing one description, exactly as expected.

A per-node `compiler.node_provenance_detail` line at DEBUG level
follows for ops-side investigation:

```python
for node in contract.nodes:
    log.debug(
        "compiler.node_provenance_detail",
        extra={
            "node_id": node.id,
            "node_name": node.name,           # ← was "name", caused 500
            "decided_by": _enum_value(node.decided_by),
            "load_bearing_assumptions": ...,
            "user_decided_assumptions": ...,
        },
    )
```

The `node_name` key is a deliberate workaround for `LogRecord.name`
collision; see `07-bugs-found-and-fixed.md` for the full story.

## `compute_uvdc` and the `compiler.uvdc_breakdown` log

`_uvdc_components` is unchanged from M3 — it counts every node's
`decided_by`, every load-bearing assumption's `decided_by`, and every
edge's `decided_by` plus its load-bearing assumptions. The
`user_or_prompt` numerator is the count of those with
`decided_by ∈ {"user", "prompt"}`.

What's new is the structured log line:

```python
total, user_or_prompt = _uvdc_components(contract)
uvdc = (user_or_prompt / total) if total else 1.0

log.info(
    "compiler.uvdc_breakdown",
    extra={
        "session_id": getattr(contract.meta, "id", None),
        "total": total,
        "user_or_prompt": user_or_prompt,
        "uvdc": uvdc,
    },
)
```

This pairs directly with `provenance_check_start` to give the full
"how much did UVDC move and why" snapshot per pass.

The end-to-end run produced two breakdowns:

```
# Pass 1 (baseline)
compiler.uvdc_breakdown total=25 user_or_prompt=4 uvdc=0.16

# Pass 2 (after editing one node's description)
compiler.uvdc_breakdown total=25 user_or_prompt=5 uvdc=0.20
```

`5/25 = 0.20`, which is exactly what the ControlBar rendered.

## Already-answered suppression composes cleanly

The M3 `_already_answered` filter still runs after the three
violation lists are computed. For M4, by the time
`_already_answered` looks at provenance violations they are already
gone — the user-decided-skip happened first. For invariant
violations, `_already_answered` only suppresses INV-001..006 if a
matching `Decision` is on the contract, and only suppresses
PROVENANCE (which by M4's rules can no longer fire on user-decided
nodes anyway). This means there is no double-counting and the
question list shrinks monotonically along the same dimensions UVDC
grows: every user edit removes at least one provenance violation
from a previously agent-decided node, never adds one.

## What did **not** change

- `INVARIANT_CHECKS` tuple still lists the same 7 IDs in the same
  order.
- `MAX_QUESTIONS = 5` is unchanged.
- `rank_violations` ranking and tier semantics are untouched.
- The LLM passes (`_call_llm_passes`) are not aware of provenance —
  they receive the raw contract and may still propose questions about
  user-decided nodes if the prompt elicits them. Those questions then
  flow into the same `_already_answered` filter and, if their
  `affects` list points at a user-decided node, are suppressed there.
  No M4 acceptance criterion relies on the LLM honoring provenance.
