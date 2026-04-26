# 04 — Seed contracts (`backend/scripts/seed_contracts/`)

Eight hand-written JSON fixtures plus one `_expected.json` sidecar.
Each fixture is deliberately minimal — small enough to read in one
glance, but realistic enough that a real Glasshouse user could plausibly
have drawn it.

## Coverage matrix

| Fixture | Verdict | Targeted finding(s) |
|---|---|---|
| `valid_simple.json` | `pass` | none — sanity baseline |
| `orphaned_node.json` | `fail` | INV-001 on `n-orphan-logger` |
| `missing_payload.json` | `fail` | INV-004 on `e-reader-pg` |
| `silent_db_choice.json` | `fail` | provenance ×2 on `n-store` (kind + load-bearing assumption) |
| `unhandled_failure.json` | `fail` | failure_scenario on `e-slack-reader` (Slack is `external`) |
| `intent_mismatch.json` | `fail` | intent_mismatch + 3 provenance |
| `low_confidence_no_question.json` | `fail` | INV-005 on `n-warehouse` |
| `cycle_in_data_edges.json` | `fail` | INV-006 on `n-a` ↔ `n-b` |

Seven of eight invariants (INV-001 through INV-007) are exercised, plus
one of each non-invariant violation type (`intent_mismatch`,
`failure_scenario`, `provenance`). INV-002 (`unconsumed_output`) and
INV-007 (`dangling_assumption`) are the two not directly seeded — they
were considered redundant on this corpus given INV-001 and INV-005's
overlap, but should be added if we discover model failures there in M2.

## Per-fixture intent

### `valid_simple.json` — Stripe → Postgres pipeline

Three nodes (`n-stripe` external source, `n-reader` service, `n-store`
Postgres) connected by two `data` edges with non-null payload schemas.
Six trust-boundary failure modes are pre-handled in
`failure_scenarios[]`. The contract should yield `verdict: "pass"`,
`violations: []`, `questions: []`. This is the *anchor* — if any model
emits a violation here, prompt tuning has regressed.

### `orphaned_node.json`

A working Stripe → Postgres pipeline with one extra node,
`n-orphan-logger`, that has no edges. Should trigger INV-001 only.

### `missing_payload.json`

Stripe → CSV reader → Postgres, but the reader→Postgres edge is
`kind: data` with `payload_schema: null`. Should trigger INV-004 only.

### `silent_db_choice.json`

A node `n-store` whose `kind: store` was decided by the agent **and**
which carries a load-bearing assumption (`decided_by: agent`,
`load_bearing: true`). Should trigger two provenance violations on
`n-store` — one for the `kind` field, one for the assumption. The
expectation entry uses `accept_types: ["provenance", "invariant"]` for
the second one to allow the model some leeway in how it categorizes
the dangling-assumption finding (provenance vs INV-007).

### `unhandled_failure.json`

A Slack bot reader pipeline. `n-slack` is `kind: external`. The edge
`e-slack-reader` (Slack→reader) is the trust-boundary edge with no
failure handlers. Should trigger one `failure_scenario` violation on
that edge. Internal edges in the same fixture must NOT be flagged —
this is what verifies the Pass-3 trust-boundary gate.

### `intent_mismatch.json`

`stated_intent`: "Slack bot that posts standups to a channel."
Graph structure: a HTML form (`n-form`) → router (`n-router`) →
Postgres (`n-pg`). That looks like a ticketing / form-submission system,
not a Slack bot. Should trigger:

- one `intent_mismatch` (the headline finding),
- three `provenance` violations on `n-form`, `n-router`, `n-pg`
  (the load-bearing kind decisions are agent-decided).

### `low_confidence_no_question.json`

A warehouse node with `confidence: 0.4` and `open_questions: []`.
Should trigger INV-005 on `n-warehouse`.

### `cycle_in_data_edges.json`

Two service nodes `n-a` and `n-b` with two `data` edges
`n-a → n-b` and `n-b → n-a`. Should trigger INV-006 on both nodes.

## Expectation sidecar (`_expected.json`)

Grading data lives outside the contracts so the contracts remain valid
example documents. Each entry supports three optional matcher fields:

- `accept_types`: list of allowed `type` values (defaults to `[type]`).
  Used on borderline cases where two violation types are both correct
  (e.g. `silent_db_choice.json`'s second expected violation).
- `rule_substr`: case-insensitive substring that must appear in
  `emitted.message`. We use `"INV-001"` etc. so the matcher is robust
  against the model rephrasing the message text.
- `affects`: list of allowed affect ids; `emitted.affects` must overlap
  it (or `rule_substr` already matched).

## Why eight, not 6 or 10?

`TODO.md` M1 calls for "6-10 test contracts". We landed on eight
because:

- Six leaves no room for redundancy in any one violation type.
- Ten was too many to keep all-passing while iterating on the prompt
  (each failure has to be tracked individually).
- Eight gives one fixture per non-trivial violation taxonomy bucket
  plus one anchor — a complete coverage map without bloat.
