# SPEC.md — Glasshouse (working name)

> Epistemic Architecture Verification: a Human–AI collaboration tool that forces a strict, mathematically-grounded "contract" phase before any code is written, and keeps the contract live during code generation.

This document defines the product. See [ARCHITECTURE.md](ARCHITECTURE.md) for the system design and schemas, and [TODO.md](TODO.md) for milestone breakdown.

---

## 1. Problem

AI coding agents commit to implementation prematurely. Given an ambiguous prompt, they invent details, pick stacks, and infer requirements without surfacing those decisions to the user. The cost shows up later as hallucinated APIs, mis-scoped components, and architectures that don't survive contact with real requirements.

We treat this as one specific failure: **decisions the agent silently made that should have surfaced to the user**. The fix is not "make the agent smarter." The fix is to (a) make every load-bearing decision visible in a shared artifact, (b) prove that artifact is internally consistent before writing code, and (c) keep that artifact live as the single source of truth during implementation.

### 1.1 Three named failure modes we explicitly target

1. **Silent assumption** — the agent picks Postgres without asking, hard-codes a 30-day retention window, assumes the user has an OpenAI key. Each assumption is a coin flip the user never saw.
2. **Under-specified surface** — "user logs in" appears in the plan, but failure modes (wrong password, MFA, account locked, OAuth callback failure) are absent. The agent will invent handling, inconsistently, in code.
3. **Unobserved coupling** — two components share state, queue, or schema that nobody declared as an edge. The agent wires them up at codegen time and the user never sees the dependency.

### 1.2 Reframe: hallucination as un-surfaced decision

Conventional anti-hallucination work focuses on grounding the model in retrieved facts. We claim that for *project planning*, the relevant "facts" are the user's intent and constraints — and they are not retrievable; they live in the user's head. So the only valid grounding move is to extract them through targeted questions.

Our north-star metric:

> **User-Visible Decision Coverage (UVDC)** = (count of load-bearing graph fields whose `decided_by` is `user` or `prompt`) / (count of load-bearing graph fields total).

A graph cannot be "compiled" with UVDC < 1.0 on load-bearing fields. Non-load-bearing fields (e.g., the agent picked `uuid4` over `nanoid` for an internal id generator) may remain `decided_by: agent` — we are not pedantic where the user genuinely should not care.

### 1.3 The visualization claim

The graph is not an output, not a sketch, not a debugging aid. The graph is **the interface where the user's mental model and the agent's mental model are forced into the same shape**. Every disagreement between the two models becomes a visible gap (an open question, a low-confidence node, a failed invariant). This is the angle that distinguishes us from "LLM with a planning step" products: the visualization is the contract, and the contract is editable on both sides.

---

## 2. User flow

We trace one canonical example end-to-end.

**Sample prompt**: *"Build a Slack bot that summarizes my unread DMs every weekday morning at 8am and posts the summary to a private channel."*

### Step 0 — Submit prompt
User pastes prompt into the web UI and clicks **Architect**.

### Step 1 — Architect emits draft contract
The Architect agent produces an `architecture_contract.json` with ~6 nodes (Slack OAuth, DM Reader, Summarizer LLM, Scheduler, Post-to-Channel, Config Store) and edges between them. Every node carries `confidence`, `assumptions`, and an empty `open_questions` list. Visualizer renders it as a non-overlapping DAG using a deterministic layout (dagre/elk).

### Step 2 — Blind Compiler verifies
The Compiler — which **has never seen the user's prompt** — runs four passes (see §3). For our example, it might produce:

- *Intent reconstruction*: "This system fetches Slack data, summarizes it, and writes a Slack message on a schedule." ✓ matches Architect's stated intent.
- *Invariant violation*: edge `Scheduler → DM Reader` has no payload schema.
- *Failure-rollout violation*: edge `Slack OAuth → DM Reader` has no handler for `auth_expired`.
- *Provenance violation*: node `Summarizer LLM` has `model: "gpt-4o"` with `decided_by: agent` — a load-bearing choice the user never made.

The Compiler emits **3–5 questions**, severity-ranked, capped hard at 5:

1. "Which LLM should the Summarizer use? Options: GPT-4o, Claude Sonnet, local Llama. (Affects: cost, latency, data egress.)"
2. "When the Slack OAuth token expires, should the bot re-prompt you, fail silently, or attempt refresh? (Affects: Slack OAuth, DM Reader, Config Store.)"
3. "What payload does the Scheduler send to the DM Reader? Just a trigger, or a date range?"

### Step 3 — User answers inline
Each question is anchored to its offending node/edge in the visualization. User answers them in a side panel. Each answer is recorded in `decisions[]` with timestamps and the violation it resolved.

### Step 4 — Architect re-emits diff
Architect updates the contract (not regenerates from scratch — diff-based update). Updated fields are flagged `decided_by: user`. Visualizer highlights the diff.

### Step 5 — Loop
Compiler re-runs. New violations produce new questions. Loop terminates when Compiler emits zero violations and intent reconstruction matches. Target: ≤ 3 iterations for a small project.

### Step 6 — Freeze
User clicks **Freeze Contract**. The contract is hashed, version-bumped, and locked. Status transitions `verified → implementing`.

### Step 7 — Phase 2 dispatch
Orchestrator inspects leaf nodes (those without `sub_graph_ref`) and creates assignments. Each assignment includes:
- A frozen snapshot of the contract.
- The assigned `node_id`.
- The declared interfaces (`payload_schema`) of incoming and outgoing edges.

**Two worker modes are supported:**

1. **Internal subagents** (default): Orchestrator calls the LLM directly and writes results to the contract.
2. **External agents** (Devin, Cursor, Claude Code, etc.): Orchestrator creates an assignment; external agent polls for it, works autonomously, then reports status back via API.

Regardless of mode, agents do **not** receive each other's outputs in flight. They write only to their own `nodes[].implementation` block (append-only) and to files under `generated/<session_id>/<node_id>/`.

### Step 8 — Live updates
The UI receives WebSocket events as each node moves `drafted → in_progress → implemented`. The user watches the graph fill in. When a node completes, its card expands to show the file path and the `actual_interface` the subagent produced.

### Step 9 — Integration pass
After the batch completes, an Integrator agent compares each edge's declared `payload_schema` against the `actual_interface` of its endpoints. Mismatches become a fresh round of Compiler violations — which means **the user sees them**, not an in-flight subagent. This is intentional (see §5).

### Step 10 — Output
User downloads `generated/<session_id>/` containing the files plus a copy of the final `architecture_contract.json`. Any downstream agent (Devin, Windsurf, Claude Code) can ingest the contract to extend the project.

---

## 2.1 External Agent Coordination

Glasshouse can serve as a **coordination layer** for multiple external agents working in parallel. This enables a human operator to visualize live progress across agents that may be running in different terminals, machines, or cloud environments.

### External agent workflow

1. **Registration**: External agent calls `POST /agents` with its name/type. Receives an `agent_id`.
2. **Poll for assignment**: Agent calls `GET /sessions/{id}/assignments?agent_id={agent_id}`. If the orchestrator has assigned a node to this agent, it receives the assignment payload.
3. **Claim and work**: Agent calls `POST /sessions/{id}/nodes/{node_id}/claim` to confirm it's starting. Status changes to `in_progress`. The UI shows this live.
4. **Report progress** (optional): Agent can call `POST /sessions/{id}/nodes/{node_id}/status` with progress updates (e.g., percentage, current step).
5. **Submit implementation**: When done, agent calls `POST /sessions/{id}/nodes/{node_id}/implementation` with file paths and actual interface. Status changes to `implemented`.
6. **UI updates live**: Every status change broadcasts via WebSocket. The user watches nodes turn from gray → yellow → green across all agents.

### Why this matters

When building complex systems, a single agent often can't hold the full context. By splitting work across multiple specialized agents (one for frontend, one for backend, one for infra), you get:
- **Parallelism**: Agents work simultaneously on independent nodes.
- **Visibility**: The user sees exactly what each agent is doing in real-time.
- **Coordination without collision**: The frozen contract + append-only writes prevent agents from stepping on each other.
- **Graceful failure**: If one agent fails, others continue. The user can reassign the failed node.

---

## 3. The four Blind Compiler verification passes

The Compiler is a separate model invocation with **temperature 0**, **strict JSON-schema-enforced output**, and a system prompt that explicitly forbids it from requesting or referencing the user's original prompt. Its only inputs are (a) the contract JSON and (b) its own prompt template.

### 3.1 Intent reconstruction
The Compiler writes a single sentence describing what it believes the system does, derived only from the graph. The Architect agent (which *does* know the user's intent) compares this against the stated intent. A semantic mismatch is a hard fail. Useful when the graph is structurally fine but means something different from what the user asked for.

*Failure example*: Graph compiles to "an email triage tool" but Architect's stated intent is "Slack DM summarizer." Cause: the user's `Post-to-Channel` node was mislabeled as `Send Email`.

### 3.2 Invariant checks
Hard structural rules enforced as deterministic Python (not LLM judgment) over the contract JSON. Each invariant has an id, a severity, and a fix hint.

- `INV-001 orphaned_node` — every node must have at least one incoming or outgoing edge (except sources/sinks tagged as such).
- `INV-002 unconsumed_output` — every output edge of a node must terminate at another node or external sink.
- `INV-003 user_input_terminates` — every node of kind `ui` must reach at least one node of kind `store` or `external` (i.e., user actions go somewhere).
- `INV-004 missing_payload_schema` — every edge of kind `data` must declare `payload_schema`.
- `INV-005 low_confidence_unflagged` — any node or edge with `confidence < 0.6` must have at least one entry in `open_questions`.
- `INV-006 cyclic_data_dependency` — no cycles among `kind: data` edges (control/event cycles allowed).
- `INV-007 dangling_assumption` — every assumption with `decided_by: agent` and `load_bearing: true` must surface a question.

### 3.3 Failure-scenario rollouts
For each edge crossing a trust boundary (any edge whose target or source is `kind: external`), the Compiler enumerates failure modes from a fixed taxonomy (`timeout`, `auth_failure`, `rate_limit`, `partial_data`, `schema_drift`, `unavailable`) and asks: "Is there a node or edge that handles this?" If not, the failure is recorded in `failure_scenarios[]` with `expected_handler: "unhandled"` and becomes a violation.

*Failure example*: Edge `Slack OAuth → DM Reader` has no handler for `auth_failure`. The Compiler asks: "What happens when the Slack token expires?"

### 3.4 Decision provenance
Every node and edge field marked `load_bearing: true` in the schema must carry `decided_by ∈ {user, prompt, agent}`. If `decided_by: agent`, the field automatically generates an `open_question` of the form "Did you intend X for {field}, or should it be Y/Z?" The Compiler will not pass until UVDC = 1.0 over load-bearing fields.

The list of load-bearing fields is fixed in the schema (see [ARCHITECTURE.md §4](ARCHITECTURE.md)) — examples: `node.kind`, `node.responsibilities`, `edge.payload_schema`, anything in `assumptions[]` that the Architect tagged as load-bearing.

---

## 4. Question budget and ranking

The Compiler may produce **at most 5 questions per iteration**, drawn from violations. Ranking:

1. Intent-reconstruction mismatches (always rank 1 if present).
2. Invariant violations of severity `error`.
3. Unhandled trust-boundary failures.
4. Provenance violations (load-bearing agent decisions).
5. Invariant violations of severity `warning`.

Within each tier, questions are sorted by graph centrality (more-connected nodes first). Questions exceeding the budget are deferred to the next iteration; they are not dropped.

Hard cap of 5 exists because user attention is the scarce resource. If we ask 12 questions, the user disengages.

---

## 5. Phase 2: live graph during implementation

The novelty in Phase 2 is *what we deliberately do not do*: we do not give in-flight subagents updates to the graph. Each subagent works from a frozen snapshot. This sounds like a regression but it solves a real problem.

**The revision-loop problem**: if subagent A depends on subagent B, and B finishes first and writes its `actual_interface`, and A is still running, then "updating A with B's interface" requires either (a) interrupting A's LLM context (unsupported by current chat-completion APIs without restarting) or (b) queueing a revision after A finishes. Option (b) means A finishes against the *declared* interface, then potentially has to redo work because B's actual interface differs. If A and B are mutually dependent, you get oscillation.

**Our resolution**:

- The contract's declared `payload_schema` is the source of truth that all subagents code against. Nobody waits on anybody.
- Subagent outputs are append-only: a subagent writes only to its own node's `implementation` block. It cannot mutate the structural graph.
- After all subagents finish a batch, the **Integrator** agent diffs each subagent's `actual_interface` against the declared `payload_schema`. Mismatches are surfaced as Compiler violations to the user, not as auto-revisions.
- The user decides whether to (a) update the contract (the actual interface was better) and re-run the affected leaf nodes, or (b) ask the offending subagent to conform.

This means the user is in the loop for any structural drift during implementation. That is by design — it is the same anti-hallucination principle as Phase 1.

**Recursive decomposition**: if a node is too large for a single subagent (heuristic: estimated > N lines, or > M responsibilities), the orchestrator instantiates a child contract for that node and re-runs the entire Phase 1 loop on it. The child contract becomes the node's `sub_graph_ref`. This is general but bounded for the demo: one level deep.

---

## 6. Out of scope (explicit)

We are not building, in this hackathon:

- **Code execution / runtime sandbox** — generated files are written to disk; we do not run them.
- **Production deploy / hosting** — the demo runs on localhost.
- **Multi-user / auth / persistence beyond a single SQLite file** — sessions are anonymous and local.
- **Editing of generated code through the UI** — Phase 2 is one-shot; revisions go through the contract.
- **Support for arbitrary languages** — subagents emit Python (single language keeps the integrator pass tractable for the demo).
- **Live collaboration** — single-user only.
- **Cost/usage tracking** — we will burn LLM credits at demo time without metering.

---

## 7. Demo script (3 minutes)

| Time | Action | What the audience sees |
|------|--------|------------------------|
| 0:00 | Paste canned prompt: "Build a CLI tool that watches a directory for new CSV files and uploads each to a configurable S3 bucket, emailing me on failure." | Empty UI, prompt textarea |
| 0:15 | Click **Architect** | Graph appears with ~5 nodes, layout is clean, each node shows confidence bar |
| 0:30 | Compiler runs | Three violations appear as red badges on offending nodes; right panel shows 3 questions |
| 0:45 | User answers question 1 (which S3 client lib?) inline | Node updates, badge clears |
| 1:00 | User answers question 2 (what counts as a "new" file — modtime, mtime+size, inotify?) | Edge gains payload schema, badge clears |
| 1:15 | User answers question 3 (email failure scope — per-file, per-batch?) | New node added by Architect, Compiler re-runs, passes |
| 1:30 | Click **Freeze** → **Implement** | Node statuses transition `drafted → in_progress` (yellow), one by one |
| 2:00 | First subagent finishes | Node turns green, expands to show filename and `actual_interface` |
| 2:30 | All subagents finish, Integrator passes | Download button appears |
| 2:45 | Click download | Browser downloads `generated/<session>.zip` containing 3–4 .py files + final contract.json |
| 3:00 | Show the contract.json — every field has `decided_by` populated | UVDC = 1.0 displayed |

If the live LLM calls misbehave at demo time, we have a **canned-trace fallback**: replay a recorded session that drives the same UI through the same states. This is implemented as a `--replay` flag on the backend.

---

## 8. Success criteria for the hackathon

The submission succeeds if, in the demo:

1. Compiler catches at least one of each of the four violation types.
2. The user resolves all violations in ≤ 3 loop iterations.
3. Phase 2 produces ≥ 2 generated files whose interfaces match the frozen contract.
4. The audience can articulate the core thesis ("the agent asked instead of guessed") from the demo alone.
5. UVDC = 1.0 on the final contract, displayed prominently.
