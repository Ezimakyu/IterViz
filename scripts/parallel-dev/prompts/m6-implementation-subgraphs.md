# M6: Implementation Subgraphs — Live Node Implementation Planning

You are implementing Milestone M6 for the Glasshouse project. Read these files first:
- ARCHITECTURE.md (sections 1-6 for system overview, API surface, contract schema, Phase 2 concurrency)
- TODO.md (M5-M6 sections for context on Phase 2 orchestration)
- SPEC.md (sections 2.1, 5 for external agent coordination, Phase 2 live graph)

## Prerequisites

M0 through M5 are complete (or M4/M5 in parallel branches, M3 is the baseline). You have:
- **Frontend** (`frontend/`): React Flow visualization with `Graph.tsx`, `NodeCard.tsx`, `EdgeLabel.tsx`, `QuestionPanel.tsx`, `ControlBar.tsx`, `AgentPanel.tsx`
- **Backend** (`backend/`):
  - `app/schemas.py` — Pydantic models for Contract, Node, Edge, Agent, Assignment, etc.
  - `app/orchestrator.py` — Phase 2 freeze, dispatch, and integration logic
  - `app/ws.py` — WebSocket for live status updates
  - `app/agents.py`, `app/assignments.py` — External agent coordination
  - `tests/` — Existing unit and integration tests

## Environment

- Backend: conda environment `glasshouse` (Python 3.10), `cd backend && conda activate glasshouse`
- Frontend: Node.js 18+, `cd frontend && npm install`
- LLM: Claude Opus 4.5 via Anthropic API (`ANTHROPIC_API_KEY` required)
- Run both: backend on port 8000, frontend on port 5173

## Goal

When parallel agents are implementing nodes from the verified "big picture" graph, generate a **subgraph** for each node that shows implementation-specific planning details. This subgraph acts as a live "implementation planner" showing progress as the agent works through the node.

**Core principle**: The big picture graph has been verified to have sufficient detail (UVDC = 1.0) for unambiguous implementation. Therefore, subgraphs do NOT require another verification loop — they are derived directly from the node's specifications and serve as implementation roadmaps.

---

## Part 1: Conceptual Overview

### 1.1 What is an Implementation Subgraph?

When an agent (internal or external) begins implementing a big-picture node, the orchestrator generates a **subgraph** that breaks down the implementation into concrete tasks:

```
Big Picture Node: "Slack OAuth Handler"
    │
    └─► Implementation Subgraph:
        ├─ [OAuth Token Validation] ──────► [Token Refresh Logic]
        ├─ [Scope Permission Check] ──────► [Error Handler]
        ├─ [Unit Tests] ─────────────────► [Integration Tests]
        └─ [Type Definitions]
```

Each subgraph node represents:
- **Functions/modules** to implement
- **Tests** (unit, integration, eval)
- **Type definitions** and interfaces
- **Error handling** logic
- **Configuration** setup

### 1.2 No Verification Loop for Subgraphs

Unlike the big picture graph, subgraphs do NOT go through the Architect → Compiler → Q&A loop because:
1. The parent node has already been verified with UVDC = 1.0
2. The parent node's `responsibilities`, `assumptions`, and `payload_schema` provide sufficient context
3. Subgraph generation uses the LLM's planning capabilities, not its architectural reasoning

The subgraph is generated once when implementation starts and updated as work progresses.

### 1.3 Live Progress Visualization

As the agent works, subgraph nodes transition through states:

| State | Visual | Description |
|-------|--------|-------------|
| `pending` | Gray fill, dashed border | Not yet started |
| `in_progress` | Yellow fill, solid border, pulse animation | Currently being worked on |
| `completed` | Green fill, solid border | Successfully implemented |
| `failed` | Red fill, solid border | Implementation failed |

The agent reports progress via the existing status API, which broadcasts updates via WebSocket.

---

## Part 2: Backend — Schemas and Models

### 2.1 Add to `app/schemas.py`

```python
# ---------------------------------------------------------------------------
# M6: Implementation Subgraph Models
# ---------------------------------------------------------------------------

class SubgraphNodeKind(str, Enum):
    """Types of nodes in an implementation subgraph."""
    FUNCTION = "function"       # A function or method to implement
    MODULE = "module"           # A module/file to create
    TEST_UNIT = "test_unit"     # Unit test
    TEST_INTEGRATION = "test_integration"  # Integration test
    TEST_EVAL = "test_eval"     # Evaluation/acceptance test
    TYPE_DEF = "type_def"       # Type definitions, interfaces
    CONFIG = "config"           # Configuration setup
    ERROR_HANDLER = "error_handler"  # Error handling logic
    UTIL = "util"               # Utility/helper code


class SubgraphNodeStatus(str, Enum):
    """Status of a subgraph node during implementation."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class SubgraphNode(BaseModel):
    """A node in an implementation subgraph."""
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    kind: SubgraphNodeKind
    description: str  # Brief explanation of what this implements
    status: SubgraphNodeStatus = SubgraphNodeStatus.PENDING
    
    # Implementation details (no assumptions — derived from parent node)
    signature: Optional[str] = None  # Function signature if applicable
    dependencies: list[str] = Field(default_factory=list)  # IDs of nodes this depends on
    estimated_lines: Optional[int] = None  # Rough estimate
    
    # Progress tracking
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class SubgraphEdge(BaseModel):
    """An edge in an implementation subgraph (dependency relationship)."""
    model_config = ConfigDict(extra="allow")

    id: str
    source: str  # SubgraphNode.id
    target: str  # SubgraphNode.id
    kind: str = "dependency"  # Always dependency for subgraphs
    label: Optional[str] = None


class ImplementationSubgraph(BaseModel):
    """A subgraph showing implementation breakdown for a big-picture node."""
    model_config = ConfigDict(extra="allow")

    id: str
    parent_node_id: str  # The big-picture node this implements
    parent_node_name: str
    session_id: str
    created_at: datetime
    
    nodes: list[SubgraphNode]
    edges: list[SubgraphEdge]
    
    # Aggregate status
    status: SubgraphNodeStatus = SubgraphNodeStatus.PENDING
    progress: float = 0.0  # 0.0 to 1.0
    
    # Metadata (NO assumptions — this is implementation-focused)
    total_estimated_lines: Optional[int] = None


# ---------------------------------------------------------------------------
# M6: Subgraph API Request/Response Models
# ---------------------------------------------------------------------------

class GenerateSubgraphRequest(BaseModel):
    """Request to generate a subgraph for a node."""
    model_config = ConfigDict(extra="forbid")
    node_id: str


class GenerateSubgraphResponse(BaseModel):
    subgraph: ImplementationSubgraph


class GetSubgraphResponse(BaseModel):
    subgraph: Optional[ImplementationSubgraph] = None


class UpdateSubgraphNodeRequest(BaseModel):
    """Update a subgraph node's status."""
    model_config = ConfigDict(extra="forbid")
    subgraph_node_id: str
    status: SubgraphNodeStatus
    error_message: Optional[str] = None


class UpdateSubgraphNodeResponse(BaseModel):
    success: bool
    subgraph: Optional[ImplementationSubgraph] = None


# ---------------------------------------------------------------------------
# M6: WebSocket Message Models for Subgraph Updates
# ---------------------------------------------------------------------------

class WSSubgraphCreated(WSMessage):
    """Broadcast when a subgraph is generated."""
    type: WSMessageType = WSMessageType.SUBGRAPH_CREATED
    parent_node_id: str
    subgraph: ImplementationSubgraph


class WSSubgraphNodeStatusChanged(WSMessage):
    """Broadcast when a subgraph node status changes."""
    type: WSMessageType = WSMessageType.SUBGRAPH_NODE_STATUS_CHANGED
    parent_node_id: str
    subgraph_node_id: str
    status: SubgraphNodeStatus
    progress: float  # Updated aggregate progress


# Add to WSMessageType enum:
# SUBGRAPH_CREATED = "subgraph_created"
# SUBGRAPH_NODE_STATUS_CHANGED = "subgraph_node_status_changed"
```

---

## Part 3: Backend — Subgraph Generator

### 3.1 Create `app/subgraph.py`

```python
"""Implementation subgraph generator.

Generates a breakdown of implementation tasks for a big-picture node.
Does NOT use the verification loop — assumes parent node is fully specified.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
import uuid

from .llm import call_structured
from .logger import get_logger
from .schemas import (
    Node, Contract, ImplementationSubgraph, SubgraphNode, SubgraphEdge,
    SubgraphNodeKind, SubgraphNodeStatus,
)

log = get_logger(__name__)


def generate_subgraph(
    node: Node,
    contract: Contract,
    neighbor_interfaces: dict,
) -> ImplementationSubgraph:
    """Generate an implementation subgraph for a big-picture node.
    
    The subgraph breaks down the node into concrete implementation tasks:
    - Functions/methods to implement
    - Tests (unit, integration, eval)
    - Type definitions
    - Error handling
    - Configuration
    
    No verification loop is used because:
    1. Parent node has UVDC = 1.0 (fully specified)
    2. Subgraph is derived from concrete specifications
    3. Acts as a planner/roadmap, not an architecture document
    """
    log.info("subgraph.generating", extra={
        "node_id": node.id,
        "node_name": node.name,
        "responsibilities_count": len(node.responsibilities),
    })
    
    # Build context from the verified parent node
    context = _build_generation_context(node, contract, neighbor_interfaces)
    
    # Call LLM to generate implementation breakdown
    try:
        subgraph_data = _call_planner_llm(context)
    except Exception as e:
        log.warning("subgraph.llm_failed", extra={
            "node_id": node.id,
            "error": str(e),
        })
        # Fallback: generate minimal subgraph from responsibilities
        subgraph_data = _generate_fallback_subgraph(node)
    
    # Build the subgraph model
    subgraph = ImplementationSubgraph(
        id=str(uuid.uuid4()),
        parent_node_id=node.id,
        parent_node_name=node.name,
        session_id=contract.meta.id,
        created_at=datetime.utcnow(),
        nodes=subgraph_data["nodes"],
        edges=subgraph_data["edges"],
        total_estimated_lines=subgraph_data.get("total_lines"),
    )
    
    log.info("subgraph.generated", extra={
        "subgraph_id": subgraph.id,
        "parent_node_id": node.id,
        "subgraph_node_count": len(subgraph.nodes),
        "subgraph_edge_count": len(subgraph.edges),
    })
    
    return subgraph


def _build_generation_context(
    node: Node,
    contract: Contract,
    neighbor_interfaces: dict,
) -> dict:
    """Build context for the planner LLM."""
    return {
        "node": {
            "id": node.id,
            "name": node.name,
            "kind": node.kind.value,
            "description": node.description,
            "responsibilities": node.responsibilities,
            # Note: NO assumptions included — they're for architecture, not implementation
        },
        "incoming_interfaces": [
            {
                "from_node": ni.node_name,
                "payload_schema": ni.payload_schema,
            }
            for ni in neighbor_interfaces.get("incoming", [])
        ],
        "outgoing_interfaces": [
            {
                "to_node": ni.node_name,
                "payload_schema": ni.payload_schema,
            }
            for ni in neighbor_interfaces.get("outgoing", [])
        ],
        "system_intent": contract.meta.stated_intent,
    }


def _call_planner_llm(context: dict) -> dict:
    """Call LLM to generate implementation breakdown."""
    from pydantic import BaseModel, Field
    
    class PlannerOutput(BaseModel):
        """LLM output for implementation planning."""
        nodes: list[dict] = Field(description="Implementation task nodes")
        edges: list[dict] = Field(description="Dependency edges between nodes")
        total_lines: Optional[int] = Field(description="Estimated total lines of code")
    
    system_prompt = """You are an implementation planner. Given a verified architecture node,
break it down into concrete implementation tasks.

Generate a subgraph with these node types:
- function: Individual functions/methods to implement
- module: Files/modules to create
- test_unit: Unit tests for specific functions
- test_integration: Integration tests for the node
- test_eval: Evaluation/acceptance tests
- type_def: Type definitions, interfaces, schemas
- config: Configuration setup
- error_handler: Error handling logic
- util: Utility/helper code

For each node, provide:
- id: Unique identifier (use format: sg-{short_name})
- name: Human-readable name
- kind: One of the types above
- description: Brief explanation (1-2 sentences)
- signature: Function signature if applicable (e.g., "def fetch_dms(token: str) -> list[DM]")
- dependencies: List of node IDs this depends on
- estimated_lines: Rough line count estimate

Create edges showing dependencies (source depends on target being complete first).

IMPORTANT: Focus on IMPLEMENTATION details, not architectural assumptions.
The architecture is already verified — your job is to plan HOW to build it."""

    user_prompt = f"""Break down this verified architecture node into implementation tasks:

Node: {context['node']['name']}
Kind: {context['node']['kind']}
Description: {context['node']['description']}

Responsibilities:
{chr(10).join(f"- {r}" for r in context['node']['responsibilities'])}

Incoming data (what this node receives):
{context['incoming_interfaces']}

Outgoing data (what this node produces):
{context['outgoing_interfaces']}

System intent: {context['system_intent']}

Generate a practical implementation subgraph with functions, tests, types, and error handling."""

    result = call_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=PlannerOutput,
        temperature=0.2,  # Slight creativity for planning
    )
    
    # Convert to SubgraphNode/SubgraphEdge models
    nodes = []
    for n in result.nodes:
        nodes.append(SubgraphNode(
            id=n.get("id", str(uuid.uuid4())),
            name=n.get("name", "Unnamed"),
            kind=SubgraphNodeKind(n.get("kind", "function")),
            description=n.get("description", ""),
            signature=n.get("signature"),
            dependencies=n.get("dependencies", []),
            estimated_lines=n.get("estimated_lines"),
        ))
    
    edges = []
    for e in result.edges:
        edges.append(SubgraphEdge(
            id=str(uuid.uuid4()),
            source=e.get("source"),
            target=e.get("target"),
            kind="dependency",
            label=e.get("label"),
        ))
    
    return {
        "nodes": nodes,
        "edges": edges,
        "total_lines": result.total_lines,
    }


def _generate_fallback_subgraph(node: Node) -> dict:
    """Generate a minimal subgraph from node responsibilities."""
    nodes = []
    edges = []
    
    # Create a node for each responsibility
    for i, responsibility in enumerate(node.responsibilities):
        func_id = f"sg-func-{i}"
        nodes.append(SubgraphNode(
            id=func_id,
            name=f"Implement: {responsibility[:50]}...",
            kind=SubgraphNodeKind.FUNCTION,
            description=responsibility,
        ))
    
    # Add a test node
    test_id = "sg-test-unit"
    nodes.append(SubgraphNode(
        id=test_id,
        name="Unit Tests",
        kind=SubgraphNodeKind.TEST_UNIT,
        description=f"Unit tests for {node.name}",
        dependencies=[n.id for n in nodes if n.kind == SubgraphNodeKind.FUNCTION],
    ))
    
    # Create edges from test to functions
    for n in nodes:
        if n.kind == SubgraphNodeKind.FUNCTION:
            edges.append(SubgraphEdge(
                id=str(uuid.uuid4()),
                source=test_id,
                target=n.id,
            ))
    
    return {"nodes": nodes, "edges": edges, "total_lines": None}


def update_subgraph_node_status(
    subgraph: ImplementationSubgraph,
    subgraph_node_id: str,
    status: SubgraphNodeStatus,
    error_message: Optional[str] = None,
) -> ImplementationSubgraph:
    """Update a subgraph node's status and recalculate aggregate progress."""
    now = datetime.utcnow()
    
    for node in subgraph.nodes:
        if node.id == subgraph_node_id:
            old_status = node.status
            node.status = status
            
            if status == SubgraphNodeStatus.IN_PROGRESS and not node.started_at:
                node.started_at = now
            elif status in (SubgraphNodeStatus.COMPLETED, SubgraphNodeStatus.FAILED):
                node.completed_at = now
            
            if error_message:
                node.error_message = error_message
            
            log.info("subgraph.node_status_changed", extra={
                "subgraph_id": subgraph.id,
                "node_id": subgraph_node_id,
                "old_status": old_status.value,
                "new_status": status.value,
            })
            break
    
    # Recalculate aggregate progress
    completed = sum(1 for n in subgraph.nodes if n.status == SubgraphNodeStatus.COMPLETED)
    total = len(subgraph.nodes)
    subgraph.progress = completed / total if total > 0 else 0.0
    
    # Update aggregate status
    if all(n.status == SubgraphNodeStatus.COMPLETED for n in subgraph.nodes):
        subgraph.status = SubgraphNodeStatus.COMPLETED
    elif any(n.status == SubgraphNodeStatus.FAILED for n in subgraph.nodes):
        subgraph.status = SubgraphNodeStatus.FAILED
    elif any(n.status == SubgraphNodeStatus.IN_PROGRESS for n in subgraph.nodes):
        subgraph.status = SubgraphNodeStatus.IN_PROGRESS
    
    return subgraph
```

### 3.2 Create `app/prompts/planner.md`

```markdown
# Implementation Planner System Prompt

You are an implementation planner for verified architecture nodes. Your job is to break down a fully-specified architecture node into concrete implementation tasks.

## Context

The architecture node you receive has already been verified through a rigorous process:
- User-Visible Decision Coverage (UVDC) = 1.0
- All load-bearing fields have been decided by the user or derived from the prompt
- All ambiguities have been resolved through Q&A

Your task is NOT to question the architecture. Your task is to plan HOW to implement it.

## Output Structure

Generate a subgraph with these node types:

| Kind | Purpose | Example |
|------|---------|---------|
| `function` | A function/method to implement | `def authenticate_user(token: str) -> User` |
| `module` | A file/module to create | `auth_handler.py` |
| `test_unit` | Unit test for specific functions | `test_authenticate_user()` |
| `test_integration` | Integration test for the node | `test_oauth_flow_e2e()` |
| `test_eval` | Acceptance/evaluation test | `test_meets_latency_requirements()` |
| `type_def` | Type definitions, interfaces | `class OAuthToken(BaseModel)` |
| `config` | Configuration setup | `OAuth config loader` |
| `error_handler` | Error handling logic | `handle_token_expired()` |
| `util` | Utility/helper code | `token_validator.py` |

## Rules

1. **No assumptions**: Don't include architectural assumptions. Those belong in the parent node.
2. **Concrete tasks**: Each node should be a specific, actionable implementation task.
3. **Include tests**: Always include test nodes (unit at minimum, integration if the node has external interfaces).
4. **Show dependencies**: Use edges to show what must be built first.
5. **Estimate effort**: Provide rough line count estimates where possible.

## Example

For a "Slack OAuth Handler" node with responsibilities:
- Validate OAuth tokens
- Refresh expired tokens
- Check scope permissions

Generate:

```json
{
  "nodes": [
    {"id": "sg-types", "name": "OAuth Types", "kind": "type_def", "description": "OAuthToken, TokenScope dataclasses"},
    {"id": "sg-validate", "name": "validate_token()", "kind": "function", "signature": "def validate_token(token: str) -> OAuthToken", "dependencies": ["sg-types"]},
    {"id": "sg-refresh", "name": "refresh_token()", "kind": "function", "signature": "def refresh_token(token: OAuthToken) -> OAuthToken", "dependencies": ["sg-types"]},
    {"id": "sg-scope", "name": "check_scope()", "kind": "function", "signature": "def check_scope(token: OAuthToken, required: list[str]) -> bool", "dependencies": ["sg-types"]},
    {"id": "sg-error", "name": "OAuth Error Handler", "kind": "error_handler", "description": "Handle token expired, invalid scope, network errors"},
    {"id": "sg-test-unit", "name": "Unit Tests", "kind": "test_unit", "dependencies": ["sg-validate", "sg-refresh", "sg-scope"]}
  ],
  "edges": [
    {"source": "sg-validate", "target": "sg-types"},
    {"source": "sg-refresh", "target": "sg-types"},
    {"source": "sg-scope", "target": "sg-types"},
    {"source": "sg-test-unit", "target": "sg-validate"},
    {"source": "sg-test-unit", "target": "sg-refresh"},
    {"source": "sg-test-unit", "target": "sg-scope"}
  ]
}
```
```

---

## Part 4: Backend — Subgraph Storage and API

### 4.1 Create `app/subgraphs.py` (Storage)

```python
"""In-memory storage for implementation subgraphs."""

from typing import Optional
from .schemas import ImplementationSubgraph

# session_id -> parent_node_id -> ImplementationSubgraph
_subgraphs: dict[str, dict[str, ImplementationSubgraph]] = {}


def store_subgraph(subgraph: ImplementationSubgraph) -> None:
    """Store a subgraph."""
    session_id = subgraph.session_id
    if session_id not in _subgraphs:
        _subgraphs[session_id] = {}
    _subgraphs[session_id][subgraph.parent_node_id] = subgraph


def get_subgraph(session_id: str, parent_node_id: str) -> Optional[ImplementationSubgraph]:
    """Get a subgraph for a specific big-picture node."""
    return _subgraphs.get(session_id, {}).get(parent_node_id)


def get_all_subgraphs(session_id: str) -> list[ImplementationSubgraph]:
    """Get all subgraphs for a session."""
    return list(_subgraphs.get(session_id, {}).values())


def update_subgraph(subgraph: ImplementationSubgraph) -> None:
    """Update a stored subgraph."""
    store_subgraph(subgraph)  # Same operation for in-memory store
```

### 4.2 Add API Routes to `app/api.py`

```python
# ---------------------------------------------------------------------------
# M6: Implementation Subgraph Routes
# ---------------------------------------------------------------------------

from . import subgraph as subgraph_svc
from . import subgraphs as subgraphs_store
from .schemas import (
    GenerateSubgraphRequest, GenerateSubgraphResponse,
    GetSubgraphResponse, UpdateSubgraphNodeRequest, UpdateSubgraphNodeResponse,
    WSSubgraphCreated, WSSubgraphNodeStatusChanged,
)


@router.post(
    "/sessions/{session_id}/nodes/{node_id}/subgraph",
    response_model=GenerateSubgraphResponse,
)
async def generate_node_subgraph(
    session_id: str,
    node_id: str,
) -> GenerateSubgraphResponse:
    """Generate an implementation subgraph for a big-picture node.
    
    Called automatically when implementation starts, or manually by the user.
    Does NOT use verification loop — assumes parent node is fully specified.
    """
    session = contract_svc.get_session(session_id)
    contract = session.contract
    
    # Find the node
    node = next((n for n in contract.nodes if n.id == node_id), None)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    
    # Get neighbor interfaces
    incoming, outgoing = orchestrator.get_neighbor_interfaces(node, contract)
    neighbor_interfaces = {"incoming": incoming, "outgoing": outgoing}
    
    # Generate subgraph
    subgraph = subgraph_svc.generate_subgraph(node, contract, neighbor_interfaces)
    
    # Store it
    subgraphs_store.store_subgraph(subgraph)
    
    # Broadcast creation
    await ws.broadcast_subgraph_created(session_id, node_id, subgraph)
    
    return GenerateSubgraphResponse(subgraph=subgraph)


@router.get(
    "/sessions/{session_id}/nodes/{node_id}/subgraph",
    response_model=GetSubgraphResponse,
)
def get_node_subgraph(
    session_id: str,
    node_id: str,
) -> GetSubgraphResponse:
    """Get the implementation subgraph for a big-picture node."""
    subgraph = subgraphs_store.get_subgraph(session_id, node_id)
    return GetSubgraphResponse(subgraph=subgraph)


@router.get(
    "/sessions/{session_id}/subgraphs",
)
def get_all_session_subgraphs(session_id: str) -> list[ImplementationSubgraph]:
    """Get all implementation subgraphs for a session."""
    return subgraphs_store.get_all_subgraphs(session_id)


@router.patch(
    "/sessions/{session_id}/nodes/{node_id}/subgraph/nodes/{subgraph_node_id}",
    response_model=UpdateSubgraphNodeResponse,
)
async def update_subgraph_node(
    session_id: str,
    node_id: str,
    subgraph_node_id: str,
    request: UpdateSubgraphNodeRequest,
) -> UpdateSubgraphNodeResponse:
    """Update a subgraph node's status (called by implementing agent)."""
    subgraph = subgraphs_store.get_subgraph(session_id, node_id)
    if not subgraph:
        return UpdateSubgraphNodeResponse(success=False)
    
    # Update the node
    updated = subgraph_svc.update_subgraph_node_status(
        subgraph,
        subgraph_node_id,
        request.status,
        request.error_message,
    )
    
    # Store update
    subgraphs_store.update_subgraph(updated)
    
    # Broadcast change
    await ws.broadcast_subgraph_node_status_changed(
        session_id,
        node_id,
        subgraph_node_id,
        request.status,
        updated.progress,
    )
    
    return UpdateSubgraphNodeResponse(success=True, subgraph=updated)
```

### 4.3 Update `app/ws.py`

Add broadcast functions for subgraph events:

```python
async def broadcast_subgraph_created(
    session_id: str,
    parent_node_id: str,
    subgraph: ImplementationSubgraph,
) -> None:
    """Broadcast that a subgraph was created."""
    msg = WSSubgraphCreated(
        parent_node_id=parent_node_id,
        subgraph=subgraph,
    )
    await manager.broadcast(session_id, msg)


async def broadcast_subgraph_node_status_changed(
    session_id: str,
    parent_node_id: str,
    subgraph_node_id: str,
    status: SubgraphNodeStatus,
    progress: float,
) -> None:
    """Broadcast that a subgraph node status changed."""
    msg = WSSubgraphNodeStatusChanged(
        parent_node_id=parent_node_id,
        subgraph_node_id=subgraph_node_id,
        status=status,
        progress=progress,
    )
    await manager.broadcast(session_id, msg)
```

### 4.4 Update `app/orchestrator.py`

Integrate subgraph generation into the implementation flow:

```python
from . import subgraph as subgraph_svc
from . import subgraphs as subgraphs_store

async def run_implementation_internal(session_id: str) -> None:
    """Run implementation using internal LLM subagents."""
    # ... existing code ...
    
    for assignment in assignments:
        node = assignment.payload.node
        
        # Generate implementation subgraph BEFORE starting work
        incoming, outgoing = get_neighbor_interfaces(node, contract)
        neighbor_interfaces = {"incoming": incoming, "outgoing": outgoing}
        
        subgraph = subgraph_svc.generate_subgraph(node, contract, neighbor_interfaces)
        subgraphs_store.store_subgraph(subgraph)
        
        # Broadcast subgraph creation
        await ws.broadcast_subgraph_created(session_id, node.id, subgraph)
        
        # ... rest of implementation, updating subgraph nodes as work progresses ...
```

---

## Part 5: Frontend — Subgraph Visualization

### 5.1 Create `src/state/subgraph.ts`

```typescript
import { create } from 'zustand';
import { ImplementationSubgraph, SubgraphNode, SubgraphNodeStatus } from '../types/subgraph';

interface SubgraphStore {
  // Map of parent_node_id -> ImplementationSubgraph
  subgraphs: Map<string, ImplementationSubgraph>;
  
  // Currently viewed subgraph (null = showing big picture graph)
  activeSubgraphNodeId: string | null;
  
  // Actions
  setSubgraph: (parentNodeId: string, subgraph: ImplementationSubgraph) => void;
  updateSubgraphNodeStatus: (
    parentNodeId: string,
    subgraphNodeId: string,
    status: SubgraphNodeStatus,
    progress: number
  ) => void;
  setActiveSubgraph: (parentNodeId: string | null) => void;
  getSubgraph: (parentNodeId: string) => ImplementationSubgraph | undefined;
}

export const useSubgraphStore = create<SubgraphStore>((set, get) => ({
  subgraphs: new Map(),
  activeSubgraphNodeId: null,

  setSubgraph: (parentNodeId, subgraph) => {
    set((state) => {
      const newMap = new Map(state.subgraphs);
      newMap.set(parentNodeId, subgraph);
      return { subgraphs: newMap };
    });
  },

  updateSubgraphNodeStatus: (parentNodeId, subgraphNodeId, status, progress) => {
    set((state) => {
      const subgraph = state.subgraphs.get(parentNodeId);
      if (!subgraph) return state;

      const updatedNodes = subgraph.nodes.map((node) =>
        node.id === subgraphNodeId ? { ...node, status } : node
      );

      const newMap = new Map(state.subgraphs);
      newMap.set(parentNodeId, {
        ...subgraph,
        nodes: updatedNodes,
        progress,
      });
      return { subgraphs: newMap };
    });
  },

  setActiveSubgraph: (parentNodeId) => {
    set({ activeSubgraphNodeId: parentNodeId });
  },

  getSubgraph: (parentNodeId) => {
    return get().subgraphs.get(parentNodeId);
  },
}));
```

### 5.2 Create `src/components/SubgraphView.tsx`

```typescript
import React, { useMemo, useCallback } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
} from 'reactflow';
import dagre from 'dagre';
import { useSubgraphStore } from '../state/subgraph';
import { SubgraphNodeCard } from './SubgraphNodeCard';
import { SubgraphNodeStatus } from '../types/subgraph';

interface SubgraphViewProps {
  parentNodeId: string;
  parentNodeName: string;
  onBack: () => void;
  onNodeClick: (nodeId: string) => void;
}

const nodeTypes = {
  subgraphNode: SubgraphNodeCard,
};

export const SubgraphView: React.FC<SubgraphViewProps> = ({
  parentNodeId,
  parentNodeName,
  onBack,
  onNodeClick,
}) => {
  const subgraph = useSubgraphStore((s) => s.getSubgraph(parentNodeId));

  // Convert subgraph to React Flow format with dagre layout
  const { nodes, edges } = useMemo(() => {
    if (!subgraph) return { nodes: [], edges: [] };

    const dagreGraph = new dagre.graphlib.Graph();
    dagreGraph.setDefaultEdgeLabel(() => ({}));
    dagreGraph.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 80 });

    // Add nodes
    subgraph.nodes.forEach((node) => {
      dagreGraph.setNode(node.id, { width: 200, height: 100 });
    });

    // Add edges
    subgraph.edges.forEach((edge) => {
      dagreGraph.setEdge(edge.source, edge.target);
    });

    dagre.layout(dagreGraph);

    const flowNodes: Node[] = subgraph.nodes.map((node) => {
      const position = dagreGraph.node(node.id);
      return {
        id: node.id,
        type: 'subgraphNode',
        position: { x: position.x - 100, y: position.y - 50 },
        data: { node, onClick: () => onNodeClick(node.id) },
      };
    });

    const flowEdges: Edge[] = subgraph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'smoothstep',
      animated: subgraph.nodes.find((n) => n.id === edge.source)?.status === 'in_progress',
    }));

    return { nodes: flowNodes, edges: flowEdges };
  }, [subgraph, onNodeClick]);

  const [flowNodes, setNodes, onNodesChange] = useNodesState(nodes);
  const [flowEdges, setEdges, onEdgesChange] = useEdgesState(edges);

  // Update nodes when subgraph changes
  React.useEffect(() => {
    setNodes(nodes);
    setEdges(edges);
  }, [nodes, edges, setNodes, setEdges]);

  if (!subgraph) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        No implementation subgraph available
      </div>
    );
  }

  return (
    <div className="h-full relative">
      {/* Back button and header */}
      <div className="absolute top-4 left-4 z-10 flex items-center gap-4">
        <button
          onClick={onBack}
          className="flex items-center gap-2 px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-white"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Back to Graph
        </button>
        <div className="text-white">
          <span className="text-gray-400">Implementing:</span>{' '}
          <span className="font-semibold">{parentNodeName}</span>
        </div>
      </div>

      {/* Progress indicator */}
      <div className="absolute top-4 right-4 z-10 bg-gray-800 px-4 py-2 rounded-lg">
        <div className="text-sm text-gray-400">Progress</div>
        <div className="flex items-center gap-2">
          <div className="w-32 h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-green-500 transition-all duration-300"
              style={{ width: `${subgraph.progress * 100}%` }}
            />
          </div>
          <span className="text-white font-mono">{Math.round(subgraph.progress * 100)}%</span>
        </div>
      </div>

      {/* React Flow canvas */}
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        className="bg-gray-900"
      >
        <Background color="#374151" gap={20} />
        <Controls />
      </ReactFlow>
    </div>
  );
};
```

### 5.3 Create `src/components/SubgraphNodeCard.tsx`

```typescript
import React from 'react';
import { Handle, Position } from 'reactflow';
import { SubgraphNode, SubgraphNodeStatus, SubgraphNodeKind } from '../types/subgraph';

interface SubgraphNodeCardProps {
  data: {
    node: SubgraphNode;
    onClick: () => void;
  };
}

const statusStyles: Record<SubgraphNodeStatus, string> = {
  pending: 'bg-gray-600 border-dashed border-gray-500',
  in_progress: 'bg-yellow-600 border-solid border-yellow-400 animate-pulse',
  completed: 'bg-green-600 border-solid border-green-400',
  failed: 'bg-red-600 border-solid border-red-400',
};

const kindIcons: Record<SubgraphNodeKind, string> = {
  function: '𝑓',
  module: '📦',
  test_unit: '🧪',
  test_integration: '🔗',
  test_eval: '✅',
  type_def: '📐',
  config: '⚙️',
  error_handler: '⚠️',
  util: '🔧',
};

export const SubgraphNodeCard: React.FC<SubgraphNodeCardProps> = ({ data }) => {
  const { node, onClick } = data;

  return (
    <div
      onClick={onClick}
      className={`
        px-4 py-3 rounded-lg border-2 cursor-pointer
        min-w-[180px] max-w-[220px]
        transition-all duration-200 hover:scale-105
        ${statusStyles[node.status]}
      `}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      
      {/* Kind badge */}
      <div className="flex items-center gap-2 mb-1">
        <span className="text-lg">{kindIcons[node.kind]}</span>
        <span className="text-xs text-gray-300 uppercase">{node.kind.replace('_', ' ')}</span>
      </div>

      {/* Name */}
      <div className="text-white font-medium text-sm truncate" title={node.name}>
        {node.name}
      </div>

      {/* Signature (if function) */}
      {node.signature && (
        <div className="text-xs text-gray-300 font-mono mt-1 truncate" title={node.signature}>
          {node.signature}
        </div>
      )}

      {/* Status indicator */}
      <div className="flex items-center gap-2 mt-2">
        <div
          className={`w-2 h-2 rounded-full ${
            node.status === 'completed' ? 'bg-green-400' :
            node.status === 'in_progress' ? 'bg-yellow-400 animate-ping' :
            node.status === 'failed' ? 'bg-red-400' :
            'bg-gray-400'
          }`}
        />
        <span className="text-xs text-gray-300 capitalize">
          {node.status.replace('_', ' ')}
        </span>
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-gray-400" />
    </div>
  );
};
```

### 5.4 Create `src/components/DraggablePopup.tsx`

```typescript
import React, { useState, useRef, useCallback } from 'react';

interface DraggablePopupProps {
  id: string;
  title: string;
  children: React.ReactNode;
  initialPosition?: { x: number; y: number };
  onClose: () => void;
  zIndex?: number;
}

export const DraggablePopup: React.FC<DraggablePopupProps> = ({
  id,
  title,
  children,
  initialPosition = { x: 100, y: 100 },
  onClose,
  zIndex = 50,
}) => {
  const [position, setPosition] = useState(initialPosition);
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<{ startX: number; startY: number } | null>(null);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    setIsDragging(true);
    dragRef.current = {
      startX: e.clientX - position.x,
      startY: e.clientY - position.y,
    };
  }, [position]);

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging || !dragRef.current) return;
    setPosition({
      x: e.clientX - dragRef.current.startX,
      y: e.clientY - dragRef.current.startY,
    });
  }, [isDragging]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
    dragRef.current = null;
  }, []);

  React.useEffect(() => {
    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
    }
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  return (
    <div
      className="fixed bg-gray-800 rounded-lg shadow-2xl border border-gray-700 min-w-[300px] max-w-[400px]"
      style={{
        left: position.x,
        top: position.y,
        zIndex,
      }}
    >
      {/* Draggable header */}
      <div
        className="flex items-center justify-between px-4 py-3 bg-gray-700 rounded-t-lg cursor-move"
        onMouseDown={handleMouseDown}
      >
        <h3 className="text-white font-semibold truncate">{title}</h3>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white transition-colors"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="p-4 text-gray-300 max-h-[400px] overflow-y-auto">
        {children}
      </div>
    </div>
  );
};
```

### 5.5 Create `src/components/NodePopupManager.tsx`

```typescript
import React, { useCallback } from 'react';
import { DraggablePopup } from './DraggablePopup';
import { Node } from '../types/contract';
import { SubgraphNode } from '../types/subgraph';

interface PopupState {
  bigPictureNode: Node | null;
  subgraphNode: SubgraphNode | null;
  parentNodeId: string | null;  // For subgraph nodes
}

interface NodePopupManagerProps {
  openPopups: PopupState;
  onCloseBigPicturePopup: () => void;
  onCloseSubgraphPopup: () => void;
}

export const NodePopupManager: React.FC<NodePopupManagerProps> = ({
  openPopups,
  onCloseBigPicturePopup,
  onCloseSubgraphPopup,
}) => {
  return (
    <>
      {/* Big picture node popup */}
      {openPopups.bigPictureNode && (
        <DraggablePopup
          id={`bp-${openPopups.bigPictureNode.id}`}
          title={openPopups.bigPictureNode.name}
          onClose={onCloseBigPicturePopup}
          initialPosition={{ x: 50, y: 100 }}
          zIndex={51}
        >
          <BigPictureNodeContent node={openPopups.bigPictureNode} />
        </DraggablePopup>
      )}

      {/* Subgraph node popup */}
      {openPopups.subgraphNode && (
        <DraggablePopup
          id={`sg-${openPopups.subgraphNode.id}`}
          title={openPopups.subgraphNode.name}
          onClose={onCloseSubgraphPopup}
          initialPosition={{ x: 400, y: 100 }}
          zIndex={52}
        >
          <SubgraphNodeContent node={openPopups.subgraphNode} />
        </DraggablePopup>
      )}
    </>
  );
};

// Big picture node content - shows description WITHOUT assumptions (for subgraph context)
const BigPictureNodeContent: React.FC<{ node: Node }> = ({ node }) => (
  <div className="space-y-3">
    <div>
      <span className="text-gray-400 text-sm">Kind:</span>
      <span className="ml-2 text-white">{node.kind}</span>
    </div>
    <div>
      <span className="text-gray-400 text-sm">Description:</span>
      <p className="mt-1 text-white">{node.description}</p>
    </div>
    <div>
      <span className="text-gray-400 text-sm">Responsibilities:</span>
      <ul className="mt-1 list-disc list-inside text-white">
        {node.responsibilities.map((r, i) => (
          <li key={i} className="text-sm">{r}</li>
        ))}
      </ul>
    </div>
    {/* NOTE: No assumptions shown here - this is for implementation context */}
  </div>
);

// Subgraph node content - shows function explanation only
const SubgraphNodeContent: React.FC<{ node: SubgraphNode }> = ({ node }) => (
  <div className="space-y-3">
    <div>
      <span className="text-gray-400 text-sm">Type:</span>
      <span className="ml-2 text-white capitalize">{node.kind.replace('_', ' ')}</span>
    </div>
    <div>
      <span className="text-gray-400 text-sm">Description:</span>
      <p className="mt-1 text-white">{node.description}</p>
    </div>
    {node.signature && (
      <div>
        <span className="text-gray-400 text-sm">Signature:</span>
        <pre className="mt-1 text-green-400 font-mono text-sm bg-gray-900 p-2 rounded">
          {node.signature}
        </pre>
      </div>
    )}
    {node.dependencies.length > 0 && (
      <div>
        <span className="text-gray-400 text-sm">Depends on:</span>
        <ul className="mt-1 list-disc list-inside text-white">
          {node.dependencies.map((dep, i) => (
            <li key={i} className="text-sm font-mono">{dep}</li>
          ))}
        </ul>
      </div>
    )}
    <div>
      <span className="text-gray-400 text-sm">Status:</span>
      <span className={`ml-2 capitalize ${
        node.status === 'completed' ? 'text-green-400' :
        node.status === 'in_progress' ? 'text-yellow-400' :
        node.status === 'failed' ? 'text-red-400' :
        'text-gray-400'
      }`}>
        {node.status.replace('_', ' ')}
      </span>
    </div>
    {node.estimated_lines && (
      <div>
        <span className="text-gray-400 text-sm">Estimated:</span>
        <span className="ml-2 text-white">~{node.estimated_lines} lines</span>
      </div>
    )}
    {/* NOTE: No assumptions - subgraph nodes are concrete implementation tasks */}
  </div>
);
```

### 5.6 Update `src/components/NodeCard.tsx`

Add click handler to enter subgraph:

```typescript
// Add to NodeCard component props
interface NodeCardProps {
  // ... existing props
  onLeftClick?: () => void;  // Enter subgraph
  onInfoClick?: () => void;  // Show popup with description (no assumptions)
  hasSubgraph?: boolean;
}

// In the render:
<div
  onClick={onLeftClick}  // Left click enters subgraph
  className={`... ${hasSubgraph ? 'cursor-pointer' : ''}`}
>
  {/* ... existing content ... */}

  {/* Info button (top right) - shows popup WITHOUT assumptions */}
  {hasSubgraph && (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onInfoClick?.();
      }}
      className="absolute top-2 right-8 w-6 h-6 rounded-full bg-gray-600 hover:bg-gray-500 flex items-center justify-center"
      title="View node details"
    >
      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    </button>
  )}
</div>
```

### 5.7 Update `src/components/Graph.tsx`

Integrate subgraph navigation:

```typescript
// Add to Graph.tsx

import { useSubgraphStore } from '../state/subgraph';
import { SubgraphView } from './SubgraphView';
import { NodePopupManager } from './NodePopupManager';

export const Graph: React.FC = () => {
  const { activeSubgraphNodeId, setActiveSubgraph, getSubgraph } = useSubgraphStore();
  const [openPopups, setOpenPopups] = useState<PopupState>({
    bigPictureNode: null,
    subgraphNode: null,
    parentNodeId: null,
  });

  // Handle node left click - enter subgraph if available
  const handleNodeLeftClick = useCallback((nodeId: string) => {
    const subgraph = getSubgraph(nodeId);
    if (subgraph) {
      setActiveSubgraph(nodeId);
    }
  }, [getSubgraph, setActiveSubgraph]);

  // Handle node info click - show popup WITHOUT assumptions
  const handleNodeInfoClick = useCallback((node: Node) => {
    // Close any existing big picture popup from same graph
    setOpenPopups((prev) => ({
      ...prev,
      bigPictureNode: node,
    }));
  }, []);

  // Handle subgraph node click - show popup
  const handleSubgraphNodeClick = useCallback((subgraphNode: SubgraphNode, parentNodeId: string) => {
    // Close any existing subgraph popup from same graph
    setOpenPopups((prev) => ({
      ...prev,
      subgraphNode: subgraphNode,
      parentNodeId: parentNodeId,
    }));
  }, []);

  // Back to big picture
  const handleBackToGraph = useCallback(() => {
    setActiveSubgraph(null);
    // Optionally close subgraph popup
    setOpenPopups((prev) => ({ ...prev, subgraphNode: null, parentNodeId: null }));
  }, [setActiveSubgraph]);

  // If viewing a subgraph, show SubgraphView
  if (activeSubgraphNodeId) {
    const parentNode = contract?.nodes.find((n) => n.id === activeSubgraphNodeId);
    return (
      <>
        <SubgraphView
          parentNodeId={activeSubgraphNodeId}
          parentNodeName={parentNode?.name || 'Unknown'}
          onBack={handleBackToGraph}
          onNodeClick={(subgraphNodeId) => {
            const subgraph = getSubgraph(activeSubgraphNodeId);
            const node = subgraph?.nodes.find((n) => n.id === subgraphNodeId);
            if (node) {
              handleSubgraphNodeClick(node, activeSubgraphNodeId);
            }
          }}
        />
        <NodePopupManager
          openPopups={openPopups}
          onCloseBigPicturePopup={() => setOpenPopups((p) => ({ ...p, bigPictureNode: null }))}
          onCloseSubgraphPopup={() => setOpenPopups((p) => ({ ...p, subgraphNode: null }))}
        />
      </>
    );
  }

  // Otherwise show big picture graph
  return (
    <>
      {/* ... existing big picture graph rendering ... */}
      <NodePopupManager
        openPopups={openPopups}
        onCloseBigPicturePopup={() => setOpenPopups((p) => ({ ...p, bigPictureNode: null }))}
        onCloseSubgraphPopup={() => setOpenPopups((p) => ({ ...p, subgraphNode: null }))}
      />
    </>
  );
};
```

### 5.8 Update `src/state/websocket.ts`

Handle subgraph WebSocket messages:

```typescript
// Add to handleMessage function:

case 'subgraph_created': {
  const { setSubgraph } = useSubgraphStore.getState();
  setSubgraph(message.parent_node_id, message.subgraph);
  break;
}

case 'subgraph_node_status_changed': {
  const { updateSubgraphNodeStatus } = useSubgraphStore.getState();
  updateSubgraphNodeStatus(
    message.parent_node_id,
    message.subgraph_node_id,
    message.status,
    message.progress
  );
  break;
}
```

### 5.9 Create `src/types/subgraph.ts`

```typescript
export type SubgraphNodeKind =
  | 'function'
  | 'module'
  | 'test_unit'
  | 'test_integration'
  | 'test_eval'
  | 'type_def'
  | 'config'
  | 'error_handler'
  | 'util';

export type SubgraphNodeStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

export interface SubgraphNode {
  id: string;
  name: string;
  kind: SubgraphNodeKind;
  description: string;
  status: SubgraphNodeStatus;
  signature?: string;
  dependencies: string[];
  estimated_lines?: number;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
}

export interface SubgraphEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  label?: string;
}

export interface ImplementationSubgraph {
  id: string;
  parent_node_id: string;
  parent_node_name: string;
  session_id: string;
  created_at: string;
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
  status: SubgraphNodeStatus;
  progress: number;
  total_estimated_lines?: number;
}
```

### 5.10 Update `src/api/client.ts`

Add subgraph API calls:

```typescript
export async function generateSubgraph(
  sessionId: string,
  nodeId: string
): Promise<{ subgraph: ImplementationSubgraph }> {
  const res = await fetch(
    `${API_BASE}/sessions/${sessionId}/nodes/${nodeId}/subgraph`,
    { method: 'POST' }
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getSubgraph(
  sessionId: string,
  nodeId: string
): Promise<{ subgraph: ImplementationSubgraph | null }> {
  const res = await fetch(
    `${API_BASE}/sessions/${sessionId}/nodes/${nodeId}/subgraph`
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAllSubgraphs(
  sessionId: string
): Promise<ImplementationSubgraph[]> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/subgraphs`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateSubgraphNodeStatus(
  sessionId: string,
  nodeId: string,
  subgraphNodeId: string,
  status: SubgraphNodeStatus,
  errorMessage?: string
): Promise<{ success: boolean; subgraph?: ImplementationSubgraph }> {
  const res = await fetch(
    `${API_BASE}/sessions/${sessionId}/nodes/${nodeId}/subgraph/nodes/${subgraphNodeId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subgraph_node_id: subgraphNodeId,
        status,
        error_message: errorMessage,
      }),
    }
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

---

## Part 6: Tests

### 6.1 Create `tests/test_subgraph.py`

```python
import pytest
from app.subgraph import generate_subgraph, update_subgraph_node_status
from app.schemas import (
    SubgraphNodeKind, SubgraphNodeStatus, Node, NodeKind,
)


def test_generate_subgraph_creates_nodes():
    """Test that subgraph generation creates implementation nodes."""
    node = Node(
        id="test-node",
        name="Test Handler",
        kind=NodeKind.SERVICE,
        description="Handles test requests",
        responsibilities=["Validate input", "Process request", "Return response"],
    )
    # ... setup contract and neighbor interfaces ...
    
    subgraph = generate_subgraph(node, contract, neighbor_interfaces)
    
    assert len(subgraph.nodes) >= 3  # At least one per responsibility
    assert any(n.kind == SubgraphNodeKind.TEST_UNIT for n in subgraph.nodes)


def test_generate_subgraph_includes_tests():
    """Test that subgraph includes test nodes."""
    # ...


def test_generate_subgraph_creates_edges():
    """Test that subgraph has proper dependency edges."""
    # ...


def test_update_subgraph_node_status_changes_status():
    """Test updating a subgraph node status."""
    # ...


def test_update_subgraph_node_status_calculates_progress():
    """Test that progress is calculated correctly."""
    # Create subgraph with 4 nodes
    # Complete 2 nodes
    # Assert progress == 0.5


def test_subgraph_aggregate_status_completed():
    """Test aggregate status when all nodes complete."""
    # ...


def test_subgraph_aggregate_status_failed():
    """Test aggregate status when any node fails."""
    # ...


def test_fallback_subgraph_generation():
    """Test fallback subgraph when LLM fails."""
    # ...
```

### 6.2 Create `tests/test_subgraph_api.py`

```python
import pytest
from fastapi.testclient import TestClient


def test_generate_subgraph_endpoint(client, frozen_session):
    """Test POST /sessions/{id}/nodes/{node_id}/subgraph."""
    response = client.post(
        f"/api/v1/sessions/{frozen_session}/nodes/{node_id}/subgraph"
    )
    assert response.status_code == 200
    data = response.json()
    assert "subgraph" in data
    assert data["subgraph"]["parent_node_id"] == node_id


def test_get_subgraph_endpoint(client, session_with_subgraph):
    """Test GET /sessions/{id}/nodes/{node_id}/subgraph."""
    # ...


def test_update_subgraph_node_status_endpoint(client, session_with_subgraph):
    """Test PATCH /sessions/{id}/nodes/{node_id}/subgraph/nodes/{sg_node_id}."""
    # ...


def test_get_all_subgraphs_endpoint(client, session_with_multiple_subgraphs):
    """Test GET /sessions/{id}/subgraphs."""
    # ...
```

---

## Part 7: Integration with Orchestrator

### 7.1 Update `app/orchestrator.py`

Ensure subgraphs are generated when implementation starts:

```python
async def run_implementation_internal(session_id: str) -> None:
    """Run implementation with subgraph tracking."""
    # ... existing setup ...
    
    for assignment in assignments:
        node = assignment.payload.node
        
        # 1. Generate subgraph for this node
        incoming, outgoing = get_neighbor_interfaces(node, contract)
        neighbor_interfaces = {"incoming": incoming, "outgoing": outgoing}
        
        subgraph = subgraph_svc.generate_subgraph(node, contract, neighbor_interfaces)
        subgraphs_store.store_subgraph(subgraph)
        await ws.broadcast_subgraph_created(session_id, node.id, subgraph)
        
        # 2. Update big picture node status
        await ws.broadcast_node_status_changed(
            session_id, node.id, NodeStatus.IN_PROGRESS
        )
        
        # 3. Implement each subgraph node in dependency order
        ordered_nodes = _topological_sort(subgraph)
        
        for sg_node in ordered_nodes:
            # Mark subgraph node as in_progress
            subgraph = subgraph_svc.update_subgraph_node_status(
                subgraph, sg_node.id, SubgraphNodeStatus.IN_PROGRESS
            )
            subgraphs_store.update_subgraph(subgraph)
            await ws.broadcast_subgraph_node_status_changed(
                session_id, node.id, sg_node.id,
                SubgraphNodeStatus.IN_PROGRESS, subgraph.progress
            )
            
            try:
                # Implement this subgraph node
                await _implement_subgraph_node(sg_node, assignment)
                
                # Mark as completed
                subgraph = subgraph_svc.update_subgraph_node_status(
                    subgraph, sg_node.id, SubgraphNodeStatus.COMPLETED
                )
            except Exception as e:
                # Mark as failed
                subgraph = subgraph_svc.update_subgraph_node_status(
                    subgraph, sg_node.id, SubgraphNodeStatus.FAILED, str(e)
                )
            
            subgraphs_store.update_subgraph(subgraph)
            await ws.broadcast_subgraph_node_status_changed(
                session_id, node.id, sg_node.id,
                subgraph.nodes[next(i for i, n in enumerate(subgraph.nodes) if n.id == sg_node.id)].status,
                subgraph.progress
            )
        
        # 4. Mark big picture node as complete/failed based on subgraph
        final_status = NodeStatus.IMPLEMENTED if subgraph.status == SubgraphNodeStatus.COMPLETED else NodeStatus.FAILED
        # ... update node and broadcast ...
```

---

## Acceptance Criteria

1. `pytest tests/ -v` — all tests pass
2. When Phase 2 implementation starts, subgraphs are generated for each node
3. Subgraph nodes show progress: gray → yellow → green (or red for failed)
4. Left-clicking a big picture node enters its subgraph view
5. Back arrow returns to the big picture graph
6. Info button (top right of big picture node) shows popup WITHOUT assumptions
7. Clicking subgraph nodes shows popup with function explanation (no assumptions)
8. Multiple popups can be open simultaneously (one from big picture, one from subgraph)
9. Popups are draggable/movable
10. Node spacing in subgraphs matches big picture graph style (dagre with nodesep: 60, ranksep: 80)
11. WebSocket broadcasts subgraph creation and status updates
12. No verification loop for subgraphs — generated directly from verified parent node

---

## Deliverables Checklist

**Backend:**
- [ ] `backend/app/subgraph.py` — Subgraph generation logic
- [ ] `backend/app/subgraphs.py` — Subgraph storage
- [ ] `backend/app/prompts/planner.md` — Planner LLM prompt
- [ ] Updated `backend/app/schemas.py` — Subgraph models
- [ ] Updated `backend/app/api.py` — Subgraph endpoints
- [ ] Updated `backend/app/ws.py` — Subgraph broadcast functions
- [ ] Updated `backend/app/orchestrator.py` — Integration with implementation flow
- [ ] `backend/tests/test_subgraph.py`
- [ ] `backend/tests/test_subgraph_api.py`

**Frontend:**
- [ ] `frontend/src/types/subgraph.ts` — TypeScript types
- [ ] `frontend/src/state/subgraph.ts` — Zustand store
- [ ] `frontend/src/components/SubgraphView.tsx` — Subgraph visualization
- [ ] `frontend/src/components/SubgraphNodeCard.tsx` — Subgraph node renderer
- [ ] `frontend/src/components/DraggablePopup.tsx` — Draggable popup component
- [ ] `frontend/src/components/NodePopupManager.tsx` — Popup state management
- [ ] Updated `frontend/src/components/Graph.tsx` — Subgraph navigation
- [ ] Updated `frontend/src/components/NodeCard.tsx` — Left click + info button
- [ ] Updated `frontend/src/state/websocket.ts` — Handle subgraph messages
- [ ] Updated `frontend/src/api/client.ts` — Subgraph API calls

---

## Commit Strategy

1. `feat(m6): add subgraph schemas and models`
2. `feat(m6): add subgraph generation module`
3. `feat(m6): add subgraph storage and API routes`
4. `feat(m6): add WebSocket broadcasts for subgraphs`
5. `feat(m6): add frontend subgraph state and types`
6. `feat(m6): add SubgraphView and SubgraphNodeCard components`
7. `feat(m6): add DraggablePopup and NodePopupManager`
8. `feat(m6): integrate subgraphs into Graph navigation`
9. `feat(m6): integrate subgraphs into orchestrator implementation flow`
10. `test(m6): add subgraph generation and API tests`
11. `feat(m6): complete implementation subgraphs end-to-end`
