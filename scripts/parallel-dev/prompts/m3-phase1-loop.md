# M3: Phase 1 Loop End-to-End

You are implementing Milestone M3 for the Glasshouse project. Read these files first:
- ARCHITECTURE.md (sections 1-4 for system overview, API surface, contract schema)
- TODO.md (M3 section for detailed tasks and acceptance criteria)
- SPEC.md (sections 2-4 for user flow, Compiler verification passes, question ranking)

## Prerequisites

M0, M1, and M2 are complete. You have:
- **Frontend** (`frontend/`): React Flow visualization with `Graph.tsx`, `NodeCard.tsx`, `EdgeLabel.tsx`
- **Backend** (`backend/`):
  - `app/schemas.py` — Pydantic models for Contract, Violation, CompilerOutput
  - `app/llm.py` — LLM wrapper with `call_structured()` using instructor
  - `app/architect.py` — `generate_contract()`, `refine_contract()`
  - `app/contract.py` — SQLite persistence with `create_session()`, `get_session()`, `update_contract()`
  - `app/api.py` — `POST /sessions`, `GET /sessions/{id}`
  - `app/prompts/architect.md`, `app/prompts/compiler.md`
  - `tests/` — existing unit tests

## Environment

- Backend: conda environment `glasshouse` (Python 3.10), `cd backend && conda activate glasshouse`
- Frontend: Node.js 18+, `cd frontend && npm install`
- Run both: backend on port 8000, frontend on port 5173

## Goal

Wire the full Architect ↔ Compiler ↔ Q&A loop. The frontend renders the contract, displays Compiler questions, posts user answers, and re-renders the updated contract.

**Evaluation approach**: Run exactly 3 fixed iterations and measure confidence score improvements rather than requiring convergence. Log extensively for debugging.

## LLM Configuration

**Model**: Use `claude-opus-4-5` (Claude Opus 4.5) exclusively for all Compiler evaluation.

**API Key handling**: At startup, check for `ANTHROPIC_API_KEY` environment variable. If not set:
1. Prompt the user to enter their Anthropic API key
2. Provide instructions: "Get your API key from https://console.anthropic.com/settings/keys"
3. Optionally save to `.env` file (with user confirmation)

In `app/llm.py`, ensure the default provider is Anthropic with `claude-opus-4-5`:
```python
DEFAULT_MODEL = "claude-opus-4-5"
DEFAULT_PROVIDER = "anthropic"
```

---

## Part 1: Backend — Compiler Module

### 1.1 Create `app/compiler.py`

```python
def verify_contract(contract: Contract) -> CompilerOutput:
    """
    Run the Blind Compiler verification on a contract.
    
    1. Run deterministic invariant checks (INV-001 through INV-007)
    2. Call LLM for intent reconstruction
    3. Call LLM for failure-scenario pass (edges crossing trust boundaries)
    4. Call LLM for decision provenance pass
    5. Merge all violations, rank by severity, emit top 5 questions
    """
```

**Invariant checks (deterministic Python, no LLM):**

| ID | Check | Error if... |
|----|-------|-------------|
| INV-001 | `orphaned_node` | Node has no incoming AND no outgoing edges (unless `is_terminal: true`) |
| INV-002 | `unconsumed_output` | A `data` edge has no target node |
| INV-003 | `user_input_terminates` | A `ui` node doesn't reach any `store` or `external` node |
| INV-004 | `missing_payload_schema` | A `data` or `event` edge has `payload_schema: null` |
| INV-005 | `low_confidence_unflagged` | Node/edge has `confidence < 0.6` but `open_questions` is empty |
| INV-006 | `cyclic_data_dependency` | Cycle exists among `kind: data` edges |
| INV-007 | `dangling_assumption` | Assumption has `decided_by: agent` AND `load_bearing: true` but no question |

**LLM passes (use `call_structured` from `app/llm.py`):**

1. **Intent reconstruction**: Compiler guesses what the system does from the graph alone. Compare against `meta.stated_intent`. Semantic mismatch = violation.
2. **Failure-scenario pass**: For each edge where source or target is `kind: external`, check if failure modes (timeout, auth_failure, rate_limit, etc.) are handled.
3. **Provenance pass**: Find all fields with `decided_by: agent` that are load-bearing. Each should have a suggested question.

**Question generation:**
- Rank violations: intent_mismatch > error-severity > failure_scenario > provenance > warning-severity
- Within each tier, sort by node/edge centrality (more edges = higher priority)
- Emit top 5 questions max (defer the rest to next pass)
- Calculate UVDC score: `(user/prompt decided fields) / (total load-bearing fields)`

**Confidence updates:**
- After each pass, the Compiler must return `NodeConfidenceUpdate` for each node it evaluated
- Capture the `reasoning` field explaining why confidence changed (or didn't)
- This reasoning is critical for debugging — make sure the LLM prompt requests explicit explanations

### 1.2 Add API Routes in `app/api.py`

```python
@router.post("/sessions/{session_id}/compiler/verify")
async def verify_session(session_id: str) -> CompilerResponse:
    """
    Run Compiler on current contract.
    Returns: { verdict, violations, questions, intent_guess, uvdc_score }
    Persists verification run to contract.verification_log[]
    """

@router.post("/sessions/{session_id}/answers")
async def submit_answers(session_id: str, body: AnswersRequest) -> ContractResponse:
    """
    Record user answers in contract.decisions[]
    Input: { decisions: [{ question, answer, affects }] }
    Returns: { contract } with updated decisions
    """

@router.post("/sessions/{session_id}/architect/refine")
async def refine_session(session_id: str, body: RefineRequest) -> ContractResponse:
    """
    Pass recent answers to Architect, get updated contract.
    Input: { answers: Decision[] } (optional, can pull from contract.decisions)
    Returns: { contract, diff } with updated nodes/edges
    """
```

### 1.3 Update `app/contract.py`

Add these functions:
- `add_decision(session_id, decision: Decision)` — append to `decisions[]`
- `add_verification_run(session_id, compiler_output: CompilerOutput)` — append to `verification_log[]`
- Ensure `decisions[]` and `verification_log[]` are initialized as empty lists on contract creation

### 1.4 Update `app/schemas.py` (if needed)

Ensure these models exist and match ARCHITECTURE.md §4.7-4.8:
- `Decision` — id, question, answer, answered_at, affects, source_violation_id
- `VerificationRun` — id, run_at, verdict, violations, questions, intent_guess, uvdc_score

**Add for confidence tracking:**

```python
class NodeConfidenceUpdate(BaseModel):
    """Returned by Compiler LLM for each node it evaluates."""
    node_id: str
    new_confidence: float  # 0.0-1.0
    reasoning: str  # explains why confidence changed

class ConfidenceSnapshot(BaseModel):
    """Snapshot of all node confidences at a point in time."""
    pass_number: int
    timestamp: str  # ISO8601
    nodes: list[NodeConfidenceUpdate]

class ConfidenceReport(BaseModel):
    """Final report after all passes complete."""
    session_id: str
    total_passes: int
    initial_snapshot: ConfidenceSnapshot
    final_snapshot: ConfidenceSnapshot
    per_pass_snapshots: list[ConfidenceSnapshot]
    summary: ConfidenceSummary

class ConfidenceSummary(BaseModel):
    nodes_improved: int
    nodes_unchanged: int  # were already at 1.0
    nodes_degraded: int   # confidence decreased - flag for investigation
    average_delta: float
    degraded_node_ids: list[str]  # for easy lookup
```

### 1.5 Update `app/llm.py` for API Key Prompting

```python
import os
from getpass import getpass

DEFAULT_MODEL = "claude-opus-4-5"
DEFAULT_PROVIDER = "anthropic"

def ensure_api_key() -> str:
    """Ensure ANTHROPIC_API_KEY is set, prompting user if needed."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if key:
        return key
    
    print("\n" + "="*60)
    print("ANTHROPIC_API_KEY not found in environment.")
    print("Get your API key from: https://console.anthropic.com/settings/keys")
    print("="*60 + "\n")
    
    key = getpass("Enter your Anthropic API key: ")
    
    save = input("Save to .env file? (y/n): ").lower().strip()
    if save == 'y':
        with open(".env", "a") as f:
            f.write(f"\nANTHROPIC_API_KEY={key}\n")
        print("Saved to .env")
    
    os.environ["ANTHROPIC_API_KEY"] = key
    return key
```

Call `ensure_api_key()` at module load or in `app/main.py` startup.

---

## Part 2: Frontend — Wire to Live Backend

### 2.1 Create `src/api/client.ts`

```typescript
const API_BASE = 'http://localhost:8000/api/v1';

export async function createSession(prompt: string): Promise<{ session_id: string; contract: Contract }>;
export async function getSession(sessionId: string): Promise<{ contract: Contract }>;
export async function verifyContract(sessionId: string): Promise<CompilerResponse>;
export async function submitAnswers(sessionId: string, decisions: Decision[]): Promise<{ contract: Contract }>;
export async function refineContract(sessionId: string): Promise<{ contract: Contract; diff?: ContractDiff }>;
```

Handle errors gracefully — return typed error responses, don't throw on 4xx.

### 2.2 Create `src/state/contract.ts`

Zustand store:
```typescript
interface ContractStore {
  sessionId: string | null;
  contract: Contract | null;
  violations: Violation[];
  questions: string[];
  uvdcScore: number;
  isLoading: boolean;
  error: string | null;
  previousContract: Contract | null;  // for diff highlighting
  
  // Actions
  setSession: (sessionId: string, contract: Contract) => void;
  setVerificationResult: (result: CompilerResponse) => void;
  updateContract: (contract: Contract) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}
```

### 2.3 Create `src/components/PromptInput.tsx`

- Large textarea for user prompt
- "Architect" button that calls `createSession(prompt)`
- Loading state while Architect runs
- On success: set session in store, navigate/show Graph

### 2.4 Create `src/components/ControlBar.tsx`

Horizontal bar with:
- "Verify" button → calls `verifyContract(sessionId)`
- UVDC score display (e.g., "Coverage: 72%")
- Iteration count display
- Buttons disabled during loading

### 2.5 Create `src/components/QuestionPanel.tsx`

Side panel (right side) showing:
- List of Compiler questions (max 5)
- Each question shows:
  - Question text
  - "Affects: Node X, Edge Y" links (clicking highlights in graph)
  - Answer textarea
- "Submit Answers" button → calls `submitAnswers()` then `refineContract()`
- Clear questions after successful refine

### 2.6 Update `src/components/Graph.tsx`

- Load contract from Zustand store instead of static JSON
- **Diff highlighting**: compare `contract` vs `previousContract`:
  - Yellow border on nodes/edges that changed since last verify
  - New nodes get a "NEW" badge
- Re-layout on contract change (dagre)

### 2.7 Update `src/App.tsx`

Layout:
```
┌────────────────────────────────────────────────────────┐
│  ControlBar                                            │
├────────────────────────────────────┬───────────────────┤
│                                    │                   │
│           Graph                    │  QuestionPanel    │
│                                    │                   │
│                                    │                   │
└────────────────────────────────────┴───────────────────┘
```

If no session: show `PromptInput` fullscreen.

---

## Part 3: Tests

### 3.1 Create `tests/test_compiler.py`

```python
# Test each invariant individually
def test_inv001_orphaned_node(): ...
def test_inv002_unconsumed_output(): ...
def test_inv003_user_input_terminates(): ...
def test_inv004_missing_payload_schema(): ...
def test_inv005_low_confidence_unflagged(): ...
def test_inv006_cyclic_data_dependency(): ...
def test_inv007_dangling_assumption(): ...

# Test valid contracts pass
def test_valid_contract_passes_all_invariants(): ...

# Test violation ranking
def test_violations_ranked_by_severity(): ...

# Test question cap
def test_max_five_questions(): ...

# Test UVDC calculation
def test_uvdc_score_calculation(): ...
```

Use fixtures from `tests/fixtures/` or create new ones.

### 3.2 Update `tests/test_api.py`

```python
def test_verify_returns_violations_for_invalid_contract(): ...
def test_verify_returns_empty_violations_for_valid_contract(): ...
def test_submit_answers_records_decisions(): ...
def test_refine_updates_contract_with_answers(): ...
def test_verification_log_persisted(): ...
```

### 3.3 Create `tests/test_phase1_loop.py` (integration)

```python
def test_three_pass_confidence_improvement():
    """
    Run exactly 3 fixed iterations and track confidence improvements.
    
    1. Create session with test prompt
    2. Record initial confidence for each node
    3. For i in range(3):
       a. Verify → get violations + questions
       b. Submit answers for all questions  
       c. Refine → updated contract
       d. Record confidence for each node after this pass
    4. Generate confidence report (see below)
    """

def test_answered_questions_dont_reappear():
    """
    After answering a question, the same question should not
    appear in subsequent verification runs.
    """

def generate_confidence_report(initial: dict, final: dict, per_pass: list[dict]) -> ConfidenceReport:
    """
    Generate a detailed report for debugging:
    
    For each node:
    - initial_confidence: float
    - final_confidence: float  
    - delta: float (final - initial)
    - improved: bool
    - per_pass_deltas: list[float]
    - critic_reasoning: list[str]  # reasoning from each Compiler pass
    
    Summary:
    - nodes_improved: int
    - nodes_unchanged: int (confidence was already 1.0)
    - nodes_degraded: int (flag these for investigation)
    - average_improvement: float
    """
```

**Confidence tracking requirements:**

1. **Before first pass**: Snapshot all node confidence values
2. **After each pass**: Record new confidence values and the Compiler's reasoning
3. **Final report** (logged as structured JSON):

```python
{
    "session_id": "...",
    "prompt_preview": "Build a Slack bot...",
    "passes": 3,
    "summary": {
        "nodes_improved": 4,
        "nodes_unchanged": 1,  # already at 100%
        "nodes_degraded": 1,   # FLAGGED for investigation
        "average_delta": 0.15
    },
    "nodes": [
        {
            "node_id": "n1",
            "name": "Slack OAuth",
            "initial": 0.7,
            "final": 0.95,
            "delta": 0.25,
            "status": "improved",
            "per_pass": [
                {"pass": 1, "confidence": 0.8, "delta": 0.1, "reasoning": "Added retry logic"},
                {"pass": 2, "confidence": 0.9, "delta": 0.1, "reasoning": "User specified OAuth scope"},
                {"pass": 3, "confidence": 0.95, "delta": 0.05, "reasoning": "Clarified token storage"}
            ]
        },
        {
            "node_id": "n2", 
            "name": "Summarizer",
            "initial": 0.8,
            "final": 0.75,
            "delta": -0.05,
            "status": "DEGRADED",  # investigate this
            "per_pass": [...]
        }
    ]
}
```

4. **Nodes to ignore**: Skip nodes where `initial_confidence == 1.0` (already perfect)
5. **Flagged nodes**: Any node where `final < initial` should be logged at WARN level

---

## Part 4: Logging

Add comprehensive logging throughout:

```python
# In compiler.py
logger.info("compiler.verify_start", session_id=session_id, pass_number=pass_num)
logger.debug("compiler.invariant_check", invariant="INV-001", passed=True)
logger.info("compiler.llm_pass", pass_name="intent_reconstruction", duration_ms=1234, model="claude-opus-4-5")
logger.info("compiler.verify_complete", violations=len(violations), questions=len(questions))

# Confidence tracking (critical for debugging)
logger.info("compiler.confidence_snapshot", 
    session_id=session_id,
    pass_number=pass_num,
    nodes=[{
        "node_id": n.id,
        "name": n.name,
        "confidence": n.confidence,
        "delta_from_initial": n.confidence - initial_confidences[n.id]
    } for n in contract.nodes]
)

# Critic reasoning capture
logger.info("compiler.critic_reasoning",
    session_id=session_id,
    pass_number=pass_num,
    node_id=node_id,
    reasoning=llm_response.reasoning,  # capture this from the LLM response
    confidence_before=before,
    confidence_after=after
)

# Flag degraded nodes
for node in degraded_nodes:
    logger.warning("compiler.confidence_degraded",
        session_id=session_id,
        node_id=node.id,
        name=node.name,
        initial=initial_conf,
        final=final_conf,
        delta=final_conf - initial_conf,
        reasoning=node.last_critic_reasoning
    )

# In api.py
logger.info("api.verify_called", session_id=session_id)
logger.info("api.answers_submitted", session_id=session_id, count=len(decisions))

# Final confidence report
logger.info("compiler.confidence_report",
    session_id=session_id,
    total_passes=3,
    nodes_improved=count_improved,
    nodes_unchanged=count_unchanged,
    nodes_degraded=count_degraded,
    average_delta=avg_delta
)
```

**Critic reasoning capture**: When calling the LLM for each verification pass, ensure the response model includes a `reasoning` field that explains why confidence changed:

```python
class NodeConfidenceUpdate(BaseModel):
    node_id: str
    new_confidence: float
    reasoning: str  # e.g., "User clarified auth flow, reducing ambiguity"
```

---

## Acceptance Criteria

1. `pytest tests/ -v` — all tests pass
2. At startup, if `ANTHROPIC_API_KEY` not set, user is prompted to enter it
3. Start backend: `DEBUG=1 uvicorn app.main:app --reload`
4. Start frontend: `npm run dev`
5. Paste canned prompt: "Build a Slack bot that summarizes unread DMs daily."
6. Click Architect → Graph renders with ≥4 nodes
7. Click Verify → QuestionPanel shows 3-5 questions
8. Logs show Compiler timing, violation details, and critic reasoning
9. Answer one question, click Submit
10. Graph updates; changed nodes highlighted yellow
11. Complete exactly 3 full passes (Verify → Answer → Refine)
12. **Confidence report generated** showing:
    - Per-node confidence deltas
    - Nodes flagged if confidence decreased
    - Critic reasoning for each pass
13. Majority of nodes show confidence improvement (or were already at 100%)

---

## Deliverables Checklist

**Backend:**
- [ ] `backend/app/compiler.py`
- [ ] Updated `backend/app/api.py` (3 new routes)
- [ ] Updated `backend/app/contract.py` (add_decision, add_verification_run)
- [ ] `backend/tests/test_compiler.py`
- [ ] `backend/tests/test_phase1_loop.py`
- [ ] Updated `backend/tests/test_api.py`

**Frontend:**
- [ ] `frontend/src/api/client.ts`
- [ ] `frontend/src/state/contract.ts`
- [ ] `frontend/src/components/PromptInput.tsx`
- [ ] `frontend/src/components/ControlBar.tsx`
- [ ] `frontend/src/components/QuestionPanel.tsx`
- [ ] Updated `frontend/src/components/Graph.tsx` (diff highlighting)
- [ ] Updated `frontend/src/App.tsx` (layout)

---

## Commit Strategy

Create commits as you complete major pieces:
1. `feat(m3): add compiler module with invariant checks`
2. `feat(m3): add compiler API routes`
3. `feat(m3): add frontend API client and state`
4. `feat(m3): add PromptInput and ControlBar components`
5. `feat(m3): add QuestionPanel and wire loop`
6. `test(m3): add compiler and integration tests`
7. `feat(m3): complete Phase 1 loop end-to-end`
