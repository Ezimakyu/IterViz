# M4: Editable Graph + Decision Provenance

You are implementing Milestone M4 for the Glasshouse project. Read these files first:
- ARCHITECTURE.md (sections 1-4 for system overview, API surface, contract schema — especially §4.3 for node fields and `decided_by`)
- TODO.md (M4 section for detailed tasks and acceptance criteria)
- SPEC.md (sections 1.2, 3.4 for decision provenance and UVDC)

## Prerequisites

M0, M1, M2, and M3 are complete. You have:
- **Frontend** (`frontend/`):
  - React Flow visualization with `Graph.tsx`, `NodeCard.tsx`, `EdgeLabel.tsx`
  - `QuestionPanel.tsx` for displaying Compiler questions and submitting answers
  - `ControlBar.tsx` with Verify button, UVDC score, iteration counter
  - `PromptInput.tsx` for initial prompt submission
  - Zustand store in `src/state/contract.ts` with `previousContract` for diff highlighting
  - API client in `src/api/client.ts`
- **Backend** (`backend/`):
  - `app/schemas.py` — Pydantic models for Contract, Node, Edge, Violation, Decision, etc.
  - `app/llm.py` — LLM wrapper with `call_structured()` using instructor
  - `app/architect.py` — `generate_contract()`, `refine_contract()`
  - `app/compiler.py` — `verify_contract()` with INV-001 through INV-007, UVDC calculation
  - `app/contract.py` — SQLite persistence with `create_session()`, `get_session()`, `update_contract()`, `add_decision()`, `add_verification_run()`
  - `app/api.py` — `POST /sessions`, `GET /sessions/{id}`, `POST /compiler/verify`, `POST /answers`, `POST /architect/refine`
  - `tests/` — existing unit tests for schemas, contract, compiler, API

## Environment

- Backend: conda environment `glasshouse` (Python 3.10), `cd backend && conda activate glasshouse`
- Frontend: Node.js 18+, `cd frontend && npm install`
- Run both: backend on port 8000, frontend on port 5173
- Model: `claude-opus-4-5` via Anthropic API (ensure `ANTHROPIC_API_KEY` is set)

## Goal

Allow users to directly edit node fields in the graph. Edits are tagged `decided_by: user` and flow back to the backend. The Compiler respects user-decided fields (no questions for them) and UVDC increases accordingly.

**Key concept — Decision Provenance**: Every load-bearing field carries `decided_by ∈ {user, prompt, agent}`. When a user directly edits a field in the UI, that field becomes `decided_by: user`. The Compiler will not question user-decided fields, and they count as "covered" in UVDC.

---

## Part 1: Backend — Node Update Endpoint

### 1.1 Update `app/schemas.py`

Add request/response models for node updates:

```python
class NodeUpdateRequest(BaseModel):
    """Request body for PATCH /nodes/{node_id}"""
    description: str | None = None
    responsibilities: list[str] | None = None
    assumptions: list[Assumption] | None = None
    # Structural fields like 'id', 'kind', 'name' are NOT editable

class NodeUpdateResponse(BaseModel):
    """Response for PATCH /nodes/{node_id}"""
    node: Node
    fields_updated: list[str]  # which fields were changed
    provenance_set: dict[str, str]  # field -> "user"
```

Ensure the `Assumption` model has these fields (check against ARCHITECTURE.md §4.3):

```python
class Assumption(BaseModel):
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    decided_by: Literal["user", "agent", "prompt"] = "agent"
    load_bearing: bool = False
```

Ensure `Node` has a top-level `decided_by` field for the node as a whole:

```python
class Node(BaseModel):
    id: str
    name: str
    kind: Literal["service", "store", "external", "ui", "job", "interface"]
    description: str
    responsibilities: list[str]
    assumptions: list[Assumption]
    confidence: float = Field(ge=0.0, le=1.0)
    open_questions: list[str] = []
    decided_by: Literal["user", "agent", "prompt"] = "agent"
    status: Literal["drafted", "in_progress", "implemented", "failed"] = "drafted"
    # ... other fields
```

### 1.2 Update `app/contract.py`

Add function to update a single node with provenance tracking:

```python
def update_node(
    session_id: str, 
    node_id: str, 
    updates: NodeUpdateRequest
) -> tuple[Node, list[str], dict[str, str]]:
    """
    Update node fields and set provenance to 'user' for changed fields.
    
    Args:
        session_id: The session containing the contract
        node_id: ID of the node to update
        updates: Fields to update (only non-None fields are applied)
    
    Returns:
        Tuple of (updated_node, fields_updated, provenance_changes)
    
    Raises:
        ValueError: If node_id not found
        ValidationError: If structural fields are in updates
    """
    contract = get_session(session_id)
    node = next((n for n in contract.nodes if n.id == node_id), None)
    if not node:
        raise ValueError(f"Node {node_id} not found")
    
    fields_updated = []
    provenance_changes = {}
    
    # Track which fields changed
    if updates.description is not None and updates.description != node.description:
        node.description = updates.description
        fields_updated.append("description")
        provenance_changes["description"] = "user"
    
    if updates.responsibilities is not None and updates.responsibilities != node.responsibilities:
        node.responsibilities = updates.responsibilities
        fields_updated.append("responsibilities")
        provenance_changes["responsibilities"] = "user"
    
    if updates.assumptions is not None:
        # For assumptions, mark each new/changed assumption as user-decided
        for assumption in updates.assumptions:
            assumption.decided_by = "user"
        node.assumptions = updates.assumptions
        fields_updated.append("assumptions")
        provenance_changes["assumptions"] = "user"
    
    # If any field was updated, mark the node as user-decided
    if fields_updated:
        node.decided_by = "user"
    
    # Persist the updated contract
    update_contract(session_id, contract)
    
    return node, fields_updated, provenance_changes
```

### 1.3 Add API Route in `app/api.py`

```python
@router.patch("/sessions/{session_id}/nodes/{node_id}")
async def update_node_endpoint(
    session_id: str, 
    node_id: str, 
    body: NodeUpdateRequest
) -> NodeUpdateResponse:
    """
    Update node fields and set provenance to 'user'.
    
    Editable fields: description, responsibilities, assumptions
    Non-editable fields: id, name, kind (structural)
    
    Returns the updated node with list of changed fields and provenance.
    """
    try:
        node, fields_updated, provenance_changes = update_node(
            session_id, node_id, body
        )
        logger.info(
            "api.node_updated",
            session_id=session_id,
            node_id=node_id,
            fields_updated=fields_updated,
            provenance_changes=provenance_changes
        )
        return NodeUpdateResponse(
            node=node,
            fields_updated=fields_updated,
            provenance_set=provenance_changes
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
```

### 1.4 Update `app/compiler.py` — Provenance-Aware Verification

Modify the Compiler to respect `decided_by: user` fields:

```python
def _check_provenance_violations(contract: Contract) -> list[Violation]:
    """
    INV-007: Check for dangling assumptions (decided_by: agent + load_bearing: true).
    
    IMPORTANT: Skip fields/assumptions where decided_by == 'user' or 'prompt'.
    Only flag agent-decided load-bearing fields.
    """
    violations = []
    
    for node in contract.nodes:
        # Skip entire node if user-decided
        if node.decided_by == "user":
            continue
        
        # Check load-bearing assumptions
        for assumption in node.assumptions:
            if (assumption.load_bearing and 
                assumption.decided_by == "agent" and
                not _has_question_for_assumption(contract, node.id, assumption.text)):
                violations.append(Violation(
                    id=str(uuid4()),
                    type="provenance",
                    severity="warning",
                    message=f"Load-bearing assumption on node '{node.name}' was decided by agent without user confirmation: '{assumption.text[:50]}...'",
                    affects=[node.id],
                    suggested_question=f"Do you agree with this assumption: {assumption.text}?"
                ))
    
    return violations

def calculate_uvdc(contract: Contract) -> float:
    """
    Calculate User-Visible Decision Coverage.
    
    UVDC = (fields decided by user or prompt) / (total load-bearing fields)
    
    Load-bearing fields:
    - node.kind (always load-bearing)
    - node.responsibilities (always load-bearing)  
    - assumptions where load_bearing=True
    - edge.payload_schema for data/event edges
    """
    total_load_bearing = 0
    user_or_prompt_decided = 0
    
    for node in contract.nodes:
        # Count kind as load-bearing
        total_load_bearing += 1
        if node.decided_by in ("user", "prompt"):
            user_or_prompt_decided += 1
        
        # Count responsibilities as load-bearing
        total_load_bearing += 1
        if node.decided_by in ("user", "prompt"):
            user_or_prompt_decided += 1
        
        # Count load-bearing assumptions
        for assumption in node.assumptions:
            if assumption.load_bearing:
                total_load_bearing += 1
                if assumption.decided_by in ("user", "prompt"):
                    user_or_prompt_decided += 1
    
    for edge in contract.edges:
        if edge.kind in ("data", "event") and edge.payload_schema:
            total_load_bearing += 1
            if edge.decided_by in ("user", "prompt"):
                user_or_prompt_decided += 1
    
    if total_load_bearing == 0:
        return 1.0
    
    return user_or_prompt_decided / total_load_bearing

def verify_contract(contract: Contract, use_llm: bool = True) -> CompilerOutput:
    """
    Run verification with provenance-aware checks.
    
    Key behavior changes for M4:
    1. Provenance violations skip user-decided fields
    2. UVDC calculation counts user-decided fields as covered
    3. Questions are not generated for user-decided fields
    4. Log provenance state for each node
    """
    # ... existing invariant checks ...
    
    # Log provenance state for debugging
    for node in contract.nodes:
        logger.debug(
            "compiler.node_provenance",
            node_id=node.id,
            name=node.name,
            decided_by=node.decided_by,
            assumption_count=len(node.assumptions),
            user_decided_assumptions=sum(1 for a in node.assumptions if a.decided_by == "user")
        )
    
    uvdc_score = calculate_uvdc(contract)
    logger.info("compiler.uvdc_calculated", uvdc_score=uvdc_score)
    
    # ... rest of verification ...
```

---

## Part 2: Frontend — Inline Editing

### 2.1 Update `src/api/client.ts`

Add the node update API call:

```typescript
export interface NodeUpdateRequest {
  description?: string;
  responsibilities?: string[];
  assumptions?: Assumption[];
}

export interface NodeUpdateResponse {
  node: Node;
  fields_updated: string[];
  provenance_set: Record<string, string>;
}

export async function updateNode(
  sessionId: string,
  nodeId: string,
  updates: NodeUpdateRequest
): Promise<NodeUpdateResponse | ApiError> {
  const response = await fetch(
    `${API_BASE}/sessions/${sessionId}/nodes/${nodeId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    }
  );
  
  if (!response.ok) {
    const error = await response.json();
    return { error: true, status: response.status, message: error.detail };
  }
  
  return response.json();
}
```

### 2.2 Update `src/state/contract.ts`

Add state and actions for tracking user edits:

```typescript
interface ContractStore {
  // ... existing state ...
  
  // Track which nodes/fields have been user-edited (for highlighting)
  userEditedFields: Record<string, string[]>; // nodeId -> fieldNames[]
  
  // Actions
  updateNodeField: (nodeId: string, field: string, value: any) => Promise<void>;
  clearUserEdits: () => void;
}

export const useContractStore = create<ContractStore>((set, get) => ({
  // ... existing state ...
  userEditedFields: {},
  
  updateNodeField: async (nodeId: string, field: string, value: any) => {
    const { sessionId, contract } = get();
    if (!sessionId || !contract) return;
    
    const updates: NodeUpdateRequest = {};
    if (field === 'description') updates.description = value;
    if (field === 'responsibilities') updates.responsibilities = value;
    if (field === 'assumptions') updates.assumptions = value;
    
    set({ isLoading: true, error: null });
    
    const result = await updateNode(sessionId, nodeId, updates);
    
    if ('error' in result) {
      set({ isLoading: false, error: result.message });
      return;
    }
    
    // Update the contract with the new node
    const updatedNodes = contract.nodes.map(n => 
      n.id === nodeId ? result.node : n
    );
    
    set({
      contract: { ...contract, nodes: updatedNodes },
      isLoading: false,
      userEditedFields: {
        ...get().userEditedFields,
        [nodeId]: [...(get().userEditedFields[nodeId] || []), ...result.fields_updated]
      }
    });
  },
  
  clearUserEdits: () => set({ userEditedFields: {} }),
}));
```

### 2.3 Update `src/components/NodeCard.tsx`

Add inline editing capabilities:

```tsx
import { useState, useCallback } from 'react';
import { useContractStore } from '../state/contract';

interface NodeCardProps {
  data: Node;
  isNew?: boolean;
  isChanged?: boolean;
}

export function NodeCard({ data, isNew, isChanged }: NodeCardProps) {
  const { updateNodeField, userEditedFields } = useContractStore();
  const [editingField, setEditingField] = useState<string | null>(null);
  const [editValue, setEditValue] = useState<string>('');
  
  // Check if this node has user-edited fields
  const nodeUserEdits = userEditedFields[data.id] || [];
  const isUserEdited = nodeUserEdits.length > 0 || data.decided_by === 'user';
  
  const handleStartEdit = (field: string, currentValue: string) => {
    setEditingField(field);
    setEditValue(currentValue);
  };
  
  const handleEndEdit = async (field: string) => {
    if (editValue.trim() && editValue !== getFieldValue(field)) {
      await updateNodeField(data.id, field, editValue);
    }
    setEditingField(null);
    setEditValue('');
  };
  
  const getFieldValue = (field: string): string => {
    if (field === 'description') return data.description;
    if (field === 'responsibilities') return data.responsibilities.join(', ');
    return '';
  };
  
  const isFieldUserEdited = (field: string): boolean => {
    return nodeUserEdits.includes(field);
  };
  
  // Border color based on provenance
  const getBorderClass = () => {
    if (isUserEdited) return 'ring-2 ring-blue-500'; // User-edited: blue
    if (isNew) return 'ring-2 ring-green-500';       // New: green
    if (isChanged) return 'ring-2 ring-yellow-500';  // Changed: yellow
    return '';
  };
  
  return (
    <div className={`bg-slate-800 rounded-lg p-3 min-w-[200px] ${getBorderClass()}`}>
      {/* Header with name and badges */}
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-semibold text-white truncate">{data.name}</h3>
        <div className="flex gap-1">
          {isUserEdited && (
            <span className="px-1.5 py-0.5 text-xs bg-blue-600 text-white rounded">
              USER
            </span>
          )}
          {/* ... existing badges (kind, status) ... */}
        </div>
      </div>
      
      {/* Editable description field */}
      <div className="mb-2">
        <label className="text-xs text-slate-400 mb-1 block">Description</label>
        {editingField === 'description' ? (
          <textarea
            className="w-full bg-slate-700 text-white text-sm p-2 rounded border border-blue-500 focus:outline-none"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={() => handleEndEdit('description')}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleEndEdit('description');
              }
              if (e.key === 'Escape') {
                setEditingField(null);
              }
            }}
            autoFocus
            rows={3}
          />
        ) : (
          <p
            className={`text-sm text-slate-300 cursor-pointer hover:bg-slate-700 p-1 rounded ${
              isFieldUserEdited('description') ? 'border-l-2 border-blue-500 pl-2' : ''
            }`}
            onClick={() => handleStartEdit('description', data.description)}
            title="Click to edit"
          >
            {data.description || 'Click to add description...'}
          </p>
        )}
      </div>
      
      {/* Editable responsibilities field */}
      <div className="mb-2">
        <label className="text-xs text-slate-400 mb-1 block">Responsibilities</label>
        {editingField === 'responsibilities' ? (
          <textarea
            className="w-full bg-slate-700 text-white text-sm p-2 rounded border border-blue-500 focus:outline-none"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={() => {
              // Parse comma-separated responsibilities
              const responsibilities = editValue.split(',').map(r => r.trim()).filter(Boolean);
              updateNodeField(data.id, 'responsibilities', responsibilities);
              setEditingField(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setEditingField(null);
            }}
            autoFocus
            rows={2}
            placeholder="Comma-separated responsibilities"
          />
        ) : (
          <ul
            className={`text-sm text-slate-300 cursor-pointer hover:bg-slate-700 p-1 rounded ${
              isFieldUserEdited('responsibilities') ? 'border-l-2 border-blue-500 pl-2' : ''
            }`}
            onClick={() => handleStartEdit('responsibilities', data.responsibilities.join(', '))}
            title="Click to edit"
          >
            {data.responsibilities.length > 0 ? (
              data.responsibilities.map((r, i) => (
                <li key={i} className="truncate">• {r}</li>
              ))
            ) : (
              <li className="italic text-slate-500">Click to add responsibilities...</li>
            )}
          </ul>
        )}
      </div>
      
      {/* Confidence bar */}
      <ConfidenceBar confidence={data.confidence} />
      
      {/* Assumptions (collapsed by default, expandable) */}
      {/* ... existing assumption rendering with user-edit highlighting ... */}
    </div>
  );
}
```

### 2.4 Update `src/components/Graph.tsx`

Add provenance highlighting mode:

```tsx
import { useState } from 'react';
import { useContractStore } from '../state/contract';

export function Graph() {
  const { contract, previousContract, userEditedFields } = useContractStore();
  const [highlightMode, setHighlightMode] = useState<'diff' | 'provenance'>('diff');
  
  // Compute which nodes are new, changed, or user-edited
  const getNodeHighlightProps = (node: Node) => {
    const isNew = previousContract && !previousContract.nodes.find(n => n.id === node.id);
    const isChanged = previousContract?.nodes.find(n => 
      n.id === node.id && JSON.stringify(n) !== JSON.stringify(node)
    );
    const isUserEdited = userEditedFields[node.id]?.length > 0 || node.decided_by === 'user';
    
    if (highlightMode === 'provenance') {
      return { isUserEdited, isNew: false, isChanged: false };
    }
    return { isNew, isChanged, isUserEdited };
  };
  
  return (
    <div className="relative h-full">
      {/* Highlight mode toggle */}
      <div className="absolute top-4 left-4 z-10 flex gap-2 bg-slate-800 rounded-lg p-1">
        <button
          className={`px-3 py-1 text-sm rounded ${
            highlightMode === 'diff' ? 'bg-slate-600 text-white' : 'text-slate-400'
          }`}
          onClick={() => setHighlightMode('diff')}
        >
          Diff View
        </button>
        <button
          className={`px-3 py-1 text-sm rounded ${
            highlightMode === 'provenance' ? 'bg-slate-600 text-white' : 'text-slate-400'
          }`}
          onClick={() => setHighlightMode('provenance')}
        >
          Provenance View
        </button>
      </div>
      
      {/* Legend */}
      <div className="absolute top-4 right-4 z-10 bg-slate-800 rounded-lg p-2 text-xs">
        {highlightMode === 'diff' ? (
          <>
            <div className="flex items-center gap-2 mb-1">
              <div className="w-3 h-3 rounded ring-2 ring-green-500" />
              <span className="text-slate-300">New</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded ring-2 ring-yellow-500" />
              <span className="text-slate-300">Changed</span>
            </div>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2 mb-1">
              <div className="w-3 h-3 rounded ring-2 ring-blue-500" />
              <span className="text-slate-300">User-edited</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded bg-slate-700" />
              <span className="text-slate-300">Agent-decided</span>
            </div>
          </>
        )}
      </div>
      
      {/* React Flow canvas */}
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        // ... rest of props
      >
        {/* ... controls, background, etc. */}
      </ReactFlow>
    </div>
  );
}
```

---

## Part 3: Tests

### 3.1 Update `tests/test_contract.py`

```python
import pytest
from app.contract import update_node, get_session
from app.schemas import NodeUpdateRequest

class TestUpdateNode:
    """Tests for update_node() with provenance tracking."""
    
    def test_update_node_sets_user_provenance(self, session_with_contract):
        """Updating a field sets decided_by to 'user'."""
        session_id = session_with_contract
        contract = get_session(session_id)
        node_id = contract.nodes[0].id
        original_description = contract.nodes[0].description
        
        updates = NodeUpdateRequest(description="User-provided description")
        node, fields_updated, provenance = update_node(session_id, node_id, updates)
        
        assert node.description == "User-provided description"
        assert "description" in fields_updated
        assert provenance["description"] == "user"
        assert node.decided_by == "user"
    
    def test_update_node_preserves_unchanged_provenance(self, session_with_contract):
        """Unchanged fields keep their original provenance."""
        session_id = session_with_contract
        contract = get_session(session_id)
        node_id = contract.nodes[0].id
        original_responsibilities = contract.nodes[0].responsibilities.copy()
        
        # Only update description, not responsibilities
        updates = NodeUpdateRequest(description="New description")
        node, fields_updated, provenance = update_node(session_id, node_id, updates)
        
        assert node.responsibilities == original_responsibilities
        assert "responsibilities" not in fields_updated
        assert "responsibilities" not in provenance
    
    def test_update_node_assumptions_sets_user_provenance(self, session_with_contract):
        """Updating assumptions marks each assumption as user-decided."""
        session_id = session_with_contract
        contract = get_session(session_id)
        node_id = contract.nodes[0].id
        
        new_assumptions = [
            Assumption(text="User assumption 1", confidence=0.9, load_bearing=True),
            Assumption(text="User assumption 2", confidence=0.8, load_bearing=False),
        ]
        updates = NodeUpdateRequest(assumptions=new_assumptions)
        node, fields_updated, provenance = update_node(session_id, node_id, updates)
        
        assert all(a.decided_by == "user" for a in node.assumptions)
        assert "assumptions" in fields_updated
        assert provenance["assumptions"] == "user"
    
    def test_update_node_invalid_id_raises(self, session_with_contract):
        """Updating non-existent node raises ValueError."""
        session_id = session_with_contract
        
        updates = NodeUpdateRequest(description="test")
        with pytest.raises(ValueError, match="not found"):
            update_node(session_id, "nonexistent-id", updates)
    
    def test_update_node_no_changes(self, session_with_contract):
        """Updating with same values doesn't change provenance."""
        session_id = session_with_contract
        contract = get_session(session_id)
        node = contract.nodes[0]
        original_decided_by = node.decided_by
        
        # Update with same description
        updates = NodeUpdateRequest(description=node.description)
        updated_node, fields_updated, provenance = update_node(
            session_id, node.id, updates
        )
        
        assert len(fields_updated) == 0
        assert len(provenance) == 0
        # decided_by should NOT change since no actual change was made
```

### 3.2 Update `tests/test_compiler.py`

```python
class TestProvenanceAwareVerification:
    """Tests for Compiler respecting decided_by: user."""
    
    def test_user_decided_node_skips_provenance_violations(self, valid_contract):
        """Nodes with decided_by: user don't generate provenance violations."""
        contract = valid_contract
        # Set first node to user-decided with a load-bearing assumption
        contract.nodes[0].decided_by = "user"
        contract.nodes[0].assumptions = [
            Assumption(
                text="Critical choice",
                confidence=0.5,
                decided_by="user",  # user decided, so no violation
                load_bearing=True
            )
        ]
        
        result = verify_contract(contract, use_llm=False)
        
        # Should NOT have provenance violation for user-decided assumption
        provenance_violations = [v for v in result.violations if v.type == "provenance"]
        assert not any(
            contract.nodes[0].id in v.affects for v in provenance_violations
        )
    
    def test_agent_decided_load_bearing_generates_violation(self, valid_contract):
        """Agent-decided load-bearing assumptions generate violations."""
        contract = valid_contract
        contract.nodes[0].decided_by = "agent"
        contract.nodes[0].assumptions = [
            Assumption(
                text="Critical assumption made by agent",
                confidence=0.5,
                decided_by="agent",  # agent decided, should flag
                load_bearing=True
            )
        ]
        
        result = verify_contract(contract, use_llm=False)
        
        provenance_violations = [v for v in result.violations if v.type == "provenance"]
        assert any(contract.nodes[0].id in v.affects for v in provenance_violations)
    
    def test_uvdc_counts_user_decided_as_covered(self, valid_contract):
        """UVDC calculation includes user-decided fields as covered."""
        contract = valid_contract
        
        # Set half the nodes to user-decided
        for i, node in enumerate(contract.nodes):
            if i % 2 == 0:
                node.decided_by = "user"
                for assumption in node.assumptions:
                    assumption.decided_by = "user"
        
        uvdc = calculate_uvdc(contract)
        
        # Should have higher UVDC than if all agent-decided
        assert uvdc > 0
    
    def test_uvdc_mixed_provenance(self, valid_contract):
        """UVDC correctly handles mixed user/agent/prompt provenance."""
        contract = valid_contract
        
        # Node 0: user-decided
        contract.nodes[0].decided_by = "user"
        contract.nodes[0].assumptions = [
            Assumption(text="A", confidence=0.8, decided_by="user", load_bearing=True)
        ]
        
        # Node 1: prompt-decided (also counts as covered)
        contract.nodes[1].decided_by = "prompt"
        contract.nodes[1].assumptions = [
            Assumption(text="B", confidence=0.8, decided_by="prompt", load_bearing=True)
        ]
        
        # Node 2: agent-decided (not covered)
        contract.nodes[2].decided_by = "agent"
        contract.nodes[2].assumptions = [
            Assumption(text="C", confidence=0.8, decided_by="agent", load_bearing=True)
        ]
        
        uvdc = calculate_uvdc(contract)
        
        # 2 out of 3 nodes + their assumptions covered
        assert 0.5 < uvdc < 1.0
    
    def test_no_questions_for_user_decided_fields(self, contract_with_violations):
        """Questions are not generated for user-decided fields."""
        contract = contract_with_violations
        
        # Mark the node that would normally generate a question as user-decided
        for node in contract.nodes:
            node.decided_by = "user"
            for assumption in node.assumptions:
                assumption.decided_by = "user"
        
        result = verify_contract(contract, use_llm=False)
        
        # Should have fewer violations/questions since user already decided
        provenance_violations = [v for v in result.violations if v.type == "provenance"]
        assert len(provenance_violations) == 0
```

### 3.3 Update `tests/test_api.py`

```python
class TestNodeUpdateEndpoint:
    """Tests for PATCH /sessions/{id}/nodes/{node_id}."""
    
    def test_patch_node_updates_and_sets_provenance(self, client, session_with_contract):
        """PATCH updates the node and sets provenance to user."""
        session_id = session_with_contract
        contract = client.get(f"/api/v1/sessions/{session_id}").json()["contract"]
        node_id = contract["nodes"][0]["id"]
        
        response = client.patch(
            f"/api/v1/sessions/{session_id}/nodes/{node_id}",
            json={"description": "User-edited description"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["node"]["description"] == "User-edited description"
        assert "description" in data["fields_updated"]
        assert data["provenance_set"]["description"] == "user"
        assert data["node"]["decided_by"] == "user"
    
    def test_patch_node_invalid_id_returns_404(self, client, session_with_contract):
        """PATCH with invalid node_id returns 404."""
        session_id = session_with_contract
        
        response = client.patch(
            f"/api/v1/sessions/{session_id}/nodes/invalid-node-id",
            json={"description": "test"}
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_patch_node_invalid_session_returns_404(self, client):
        """PATCH with invalid session_id returns 404."""
        response = client.patch(
            "/api/v1/sessions/invalid-session/nodes/any-node",
            json={"description": "test"}
        )
        
        assert response.status_code == 404
    
    def test_patch_node_multiple_fields(self, client, session_with_contract):
        """PATCH can update multiple fields at once."""
        session_id = session_with_contract
        contract = client.get(f"/api/v1/sessions/{session_id}").json()["contract"]
        node_id = contract["nodes"][0]["id"]
        
        response = client.patch(
            f"/api/v1/sessions/{session_id}/nodes/{node_id}",
            json={
                "description": "New description",
                "responsibilities": ["Responsibility 1", "Responsibility 2"]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "description" in data["fields_updated"]
        assert "responsibilities" in data["fields_updated"]
        assert data["node"]["responsibilities"] == ["Responsibility 1", "Responsibility 2"]
    
    def test_verify_after_user_edit_increases_uvdc(self, client, session_with_contract):
        """Verifying after user edit should show increased UVDC."""
        session_id = session_with_contract
        
        # Get initial UVDC
        verify_response_1 = client.post(
            f"/api/v1/sessions/{session_id}/compiler/verify"
        )
        uvdc_before = verify_response_1.json()["uvdc_score"]
        
        # User edits a node
        contract = client.get(f"/api/v1/sessions/{session_id}").json()["contract"]
        node_id = contract["nodes"][0]["id"]
        client.patch(
            f"/api/v1/sessions/{session_id}/nodes/{node_id}",
            json={"description": "User-confirmed description"}
        )
        
        # Verify again
        verify_response_2 = client.post(
            f"/api/v1/sessions/{session_id}/compiler/verify"
        )
        uvdc_after = verify_response_2.json()["uvdc_score"]
        
        # UVDC should have increased (or stayed same if already high)
        assert uvdc_after >= uvdc_before
```

---

## Part 4: Logging

Add comprehensive provenance logging:

```python
# In contract.py
logger.info(
    "contract.node_updated",
    session_id=session_id,
    node_id=node_id,
    fields_updated=fields_updated,
    provenance_changes=provenance_changes,
    new_decided_by=node.decided_by
)

# In compiler.py
logger.info(
    "compiler.provenance_check_start",
    session_id=contract.meta.id,
    total_nodes=len(contract.nodes),
    user_decided_nodes=sum(1 for n in contract.nodes if n.decided_by == "user"),
    agent_decided_nodes=sum(1 for n in contract.nodes if n.decided_by == "agent")
)

logger.debug(
    "compiler.node_provenance_detail",
    node_id=node.id,
    name=node.name,
    decided_by=node.decided_by,
    load_bearing_assumptions=sum(1 for a in node.assumptions if a.load_bearing),
    user_decided_assumptions=sum(1 for a in node.assumptions if a.decided_by == "user")
)

# After UVDC calculation
logger.info(
    "compiler.uvdc_breakdown",
    session_id=contract.meta.id,
    total_load_bearing_fields=total_load_bearing,
    user_or_prompt_decided=user_or_prompt_decided,
    uvdc_score=uvdc_score
)
```

---

## Acceptance Criteria

1. `pytest tests/ -v` — all tests pass (including new M4 tests)
2. Start backend: `DEBUG=1 uvicorn app.main:app --reload`
3. Start frontend: `npm run dev`
4. Generate contract from prompt
5. Click a node's description field, edit it, blur to save
6. **Field shows blue border** (indicating user-edited)
7. The node shows a "USER" badge
8. Click Verify
9. **Compiler output does not include a question about the user-edited field**
10. **UVDC score (displayed in ControlBar) reflects the user edit** (should increase)
11. Toggle to "Provenance View" — user-edited nodes have blue border, others don't
12. Logs show:
    - `contract.node_updated` with fields_updated and provenance_changes
    - `compiler.provenance_check_start` with user vs agent counts
    - `compiler.uvdc_breakdown` showing the calculation

---

## Deliverables Checklist

**Backend:**
- [ ] Updated `backend/app/schemas.py` (NodeUpdateRequest, NodeUpdateResponse, Assumption.decided_by)
- [ ] Updated `backend/app/contract.py` (update_node function)
- [ ] Updated `backend/app/api.py` (PATCH /nodes/{node_id} endpoint)
- [ ] Updated `backend/app/compiler.py` (provenance-aware verification, UVDC calculation)
- [ ] Updated `backend/tests/test_contract.py` (5 new tests)
- [ ] Updated `backend/tests/test_compiler.py` (5 new tests)
- [ ] Updated `backend/tests/test_api.py` (5 new tests)

**Frontend:**
- [ ] Updated `frontend/src/api/client.ts` (updateNode function)
- [ ] Updated `frontend/src/state/contract.ts` (userEditedFields, updateNodeField action)
- [ ] Updated `frontend/src/components/NodeCard.tsx` (inline editing, blue border for user-edited)
- [ ] Updated `frontend/src/components/Graph.tsx` (provenance view toggle, legend)

---

## Commit Strategy

Create commits as you complete major pieces:
1. `feat(m4): add node update endpoint with provenance tracking`
2. `feat(m4): update compiler for provenance-aware verification`
3. `feat(m4): add frontend inline editing for NodeCard`
4. `feat(m4): add provenance view toggle in Graph`
5. `test(m4): add provenance and node update tests`
6. `feat(m4): complete editable graph with decision provenance`
