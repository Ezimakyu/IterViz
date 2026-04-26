# 02 — Blind Compiler prompt (`backend/app/prompts/compiler.md`)

The prompt is the most-edited file in M1. It went through ~6 revisions
during eval iteration; this doc records the final structure and the
specific hardenings each model required.

## Structure

```
1. Identity / blindness clause
2. The four verification passes
   2a. Pass 1 — Intent reconstruction          (type: intent_mismatch)
   2b. Pass 2 — Invariant checks INV-001..007  (type: invariant)
   2c. Pass 3 — Failure-scenario rollouts      (type: failure_scenario)
   2d. Pass 4 — Decision provenance            (type: provenance)
3. Question budget and ranking (max 5, priority-ordered)
4. Verdict rule
5. Few-shot examples (3 of them, deliberately small)
6. Final self-check
```

## Identity / blindness clause

> *"You have NOT seen the user's original prompt. You will never receive
> it. You may not request it. You may not guess at it beyond what the
> contract itself reveals. If you find yourself wanting more context than
> the contract provides, that desire is itself a finding — emit a
> question."*

This is load-bearing. Without it, even strong models try to reconstruct
the prompt before doing the actual passes, which inflates the question
budget and produces "what was the user's original goal" questions —
explicitly forbidden by SPEC.md §3.

## Pass 1 — Intent reconstruction

The model must:
1. Read the graph in isolation.
2. Write a single sentence in `intent_guess` describing what the system
   *appears* to do.
3. Compare against `meta.stated_intent`.
4. Emit one `intent_mismatch` violation **only** if the meanings differ
   (different domain, different actor, different output).

The most common failure mode here was **conflating structural defects
with intent mismatch**. We added an explicit guardrail:

> *"What is NOT an intent_mismatch: structural defects in a graph whose
> purpose still matches the stated intent. If the graph implements the
> right system but has a bug (e.g. a cyclic data dependency, a missing
> failure handler, a misnamed but obvious node), do not call that an
> intent mismatch. Reserve `intent_mismatch` for cases where, if the
> contract were implemented exactly as drawn, the user would say 'this
> is the wrong product.'"*

## Pass 2 — Invariant checks

Seven invariants from SPEC.md, with one critical addition we discovered
during eval — the **connectivity verification block**:

> *"Many false positives come from claiming a node has no edges when it
> actually does. Before emitting any violation that depends on edge
> connectivity (INV-001, INV-002, INV-003, INV-006), scan the entire
> `edges[]` array and count occurrences of `source == node.id` or
> `target == node.id`. Do this for every candidate node. If the count is
> > 0, the node is connected — do not flag it."*

This block was added after observing `gpt-4o-mini` repeatedly claim that
clearly-connected nodes were orphaned. It helps every model and is now
the second thing the model reads after the identity clause.

The seven invariants:

| ID | Name | Severity | What it checks |
|---|---|---|---|
| INV-001 | orphaned_node | error | every node has ≥1 edge (exempts `external` and `is_terminal`) |
| INV-002 | unconsumed_output | error | every outgoing edge terminates at a defined node |
| INV-003 | user_input_terminates | error | every `kind: ui` reaches a `store` or `external` transitively |
| INV-004 | missing_payload_schema | error | every `kind: data` edge has non-null `payload_schema` |
| INV-005 | low_confidence_unflagged | warning | `confidence < 0.6` requires at least one `open_questions` entry |
| INV-006 | cyclic_data_dependency | error | no directed cycle restricted to `kind: data` edges |
| INV-007 | dangling_assumption | error | load-bearing + `decided_by:agent` must surface a question |

Each invariant rule is required to be cited in the violation `message`
(e.g. `"... (INV-001)"`). The matcher uses this for `rule_substr`.

## Pass 3 — Failure-scenario rollouts

The dangerous pass. Without explicit gating, weaker models flag every
edge with a failure_scenario violation. We added a **trust-boundary check**:

> *"An edge crosses a trust boundary ONLY if you can find at least one
> node in `nodes[]` that satisfies: `node.id == edge.source` AND
> `node.kind == external`, OR `node.id == edge.target` AND
> `node.kind == external`. Internal-to-internal edges (service↔service,
> service↔store, service↔ui, etc.) do not cross a trust boundary.
> **Never emit a `failure_scenario` violation on a non-trust-boundary
> edge.** Skip them silently in Pass 3."*

For trust-boundary edges, the model enumerates failure modes from the
fixed `FailureType` taxonomy (`timeout`, `auth_failure`, `rate_limit`,
`partial_data`, `schema_drift`, `unavailable`) and only emits when the
graph has no handler.

## Pass 4 — Decision provenance

Walks every node and edge. For each load-bearing field
(`node.kind`, `node.responsibilities`, `edge.kind`,
`edge.payload_schema` when `edge.kind=data`, any assumption with
`load_bearing: true`), if `decided_by == "agent"`, emit a provenance
violation. `user` and `prompt` are acceptable.

## Question budget + priority ladder

Max 5 questions, ranked:

1. Intent-reconstruction mismatch (always rank 1 if present).
2. Invariant violations of severity `error`.
3. Unhandled trust-boundary failures.
4. Provenance violations.
5. Invariant violations of severity `warning`.

Within a tier, prefer questions on more central/connected nodes. Excess
questions are silently deferred. Each question must be one sentence,
end with `?`, and never ask "what was your original prompt?".

## Verdict

`verdict: "fail"` if any violation has `severity: "error"`.
`verdict: "pass"` only when violations are all warnings or empty.

This is the same constraint enforced by Pydantic's
`_verdict_consistency` validator; the prompt teaches the model to emit
self-consistent output, and the schema rejects any drift.

## Few-shot examples

Three small examples are inlined at the end of the prompt:

1. **Clean contract, no violations** — establishes that an empty
   `violations[]` is the correct steady state.
2. **Orphaned node + missing payload schema** — shows the canonical
   shape of two simultaneous invariant violations and how the message
   cites the rule ID.
3. **Silent agent decision on a load-bearing field** — provenance
   pattern with `decided_by: agent`.

These were chosen specifically to cover the three most-confused
violation types: `invariant`, `provenance`, and the empty case.

## Final self-check

The last paragraph instructs the model to re-walk its own emitted
violations before finalizing, and delete any whose justification it
cannot now restate. This single block dropped `gpt-4o`'s false-positive
rate substantially during tuning and is cheap (no extra LLM call — it's
in the same generation).
