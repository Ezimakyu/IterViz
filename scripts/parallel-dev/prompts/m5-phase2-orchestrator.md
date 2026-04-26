# M5: Phase 2 Orchestrator (Slim Demo Path)

You are implementing Milestone M5 for the Glasshouse project. Read these files first:
- ARCHITECTURE.md (sections 1-6 for system overview, API surface, contract schema, Phase 2 concurrency)
- TODO.md (M5 section for detailed tasks and acceptance criteria)
- SPEC.md (sections 2.1, 5, 7 for external agent coordination, Phase 2 live graph, demo script)

## Prerequisites

M0, M1, M2, and M3 are complete. You have:
- **Frontend** (`frontend/`): React Flow visualization with `Graph.tsx`, `NodeCard.tsx`, `EdgeLabel.tsx`, `QuestionPanel.tsx`, `ControlBar.tsx`, `PromptInput.tsx`
- **Backend** (`backend/`):
  - `app/schemas.py` — Pydantic models for Contract, Node, Edge, Violation, CompilerOutput, etc.
  - `app/llm.py` — LLM wrapper with `call_structured()` using instructor
  - `app/architect.py` — `generate_contract()`, `refine_contract()`
  - `app/compiler.py` — `verify_contract()` with invariant checks and LLM passes
  - `app/contract.py` — SQLite persistence with session CRUD
  - `app/api.py` — REST endpoints for Phase 1 loop
  - `app/logger.py` — structured logging with DEBUG mode
  - `app/prompts/architect.md`, `app/prompts/compiler.md`
  - `tests/` — existing unit and integration tests

**Note**: M4 (Editable Graph + Decision Provenance) is being developed in parallel. M5 does not depend on M4's features — both build on M3's foundation independently.

## Environment

- Backend: conda environment `glasshouse` (Python 3.10), `cd backend && conda activate glasshouse`
- Frontend: Node.js 18+, `cd frontend && npm install`
- Run both: backend on port 8000, frontend on port 5173

## Goal

Implement the freeze → implement → live-update flow for Phase 2. Support both internal subagents (LLM calls managed by orchestrator) and external agent coordination (Devin, Cursor, Claude Code, etc. claiming nodes via API). The UI shows live node status transitions as agents work via WebSocket.

**Core principle**: The frozen contract's declared `payload_schema` is the source of truth. All subagents code against declared interfaces, not each other's outputs. Mismatches are surfaced to the user via the Integrator pass, not auto-fixed.

---

## Part 1: Backend — New Pydantic Models

### 1.1 Add to `app/schemas.py`

```python
# ---------------------------------------------------------------------------
# M5: Agent & Assignment models (for Phase 2 orchestration)
# ---------------------------------------------------------------------------

class AgentType(str, Enum):
    DEVIN = "devin"
    CURSOR = "cursor"
    CLAUDE = "claude"
    CUSTOM = "custom"
    INTERNAL = "internal"  # for orchestrator-managed subagents


class AgentStatus(str, Enum):
    ACTIVE = "active"      # currently working on a node
    IDLE = "idle"          # registered but not working
    DISCONNECTED = "disconnected"  # no API calls for > 60s


class AssignmentStatus(str, Enum):
    PENDING = "pending"        # created, not yet claimed
    IN_PROGRESS = "in_progress"  # claimed by an agent
    COMPLETED = "completed"
    FAILED = "failed"


class Agent(BaseModel):
    """External agent that can claim and work on nodes."""
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    type: AgentType = AgentType.CUSTOM
    registered_at: datetime
    last_seen_at: datetime
    status: AgentStatus = AgentStatus.IDLE
    current_assignment: Optional[str] = None  # assignment_id


class NeighborInterface(BaseModel):
    """Interface info for an adjacent node."""
    model_config = ConfigDict(extra="allow")

    edge_id: str
    node_id: str  # source or target depending on direction
    node_name: str
    payload_schema: Optional[dict[str, Any]] = None


class AssignmentPayload(BaseModel):
    """What an agent receives when assigned a node."""
    model_config = ConfigDict(extra="allow")

    contract_snapshot: Contract  # frozen contract at assignment time
    node: Node  # the specific node to implement
    neighbor_interfaces: dict[str, list[NeighborInterface]] = Field(
        default_factory=lambda: {"incoming": [], "outgoing": []}
    )


class AssignmentResult(BaseModel):
    """What an agent submits when completing a node."""
    model_config = ConfigDict(extra="allow")

    implementation: Implementation
    completed_at: datetime
    duration_ms: int


class Assignment(BaseModel):
    """Work assignment for Phase 2 implementation."""
    model_config = ConfigDict(extra="allow")

    id: str
    session_id: str
    node_id: str
    created_at: datetime
    assigned_to: Optional[str] = None  # agent_id, null = available
    assigned_at: Optional[datetime] = None
    status: AssignmentStatus = AssignmentStatus.PENDING
    payload: AssignmentPayload
    result: Optional[AssignmentResult] = None


class IntegrationMismatch(BaseModel):
    """Detected mismatch between declared and actual interfaces."""
    model_config = ConfigDict(extra="allow")

    id: str
    edge_id: str
    source_node_id: str
    target_node_id: str
    declared_schema: Optional[dict[str, Any]] = None
    actual_source_interface: Optional[ActualInterface] = None
    actual_target_interface: Optional[ActualInterface] = None
    mismatch_description: str
    severity: Severity = Severity.WARNING


# ---------------------------------------------------------------------------
# M5: API Request/Response models
# ---------------------------------------------------------------------------

class RegisterAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    type: AgentType = AgentType.CUSTOM


class RegisterAgentResponse(BaseModel):
    agent_id: str
    agent: Agent


class ListAgentsResponse(BaseModel):
    agents: list[Agent]


class GetAssignmentResponse(BaseModel):
    assignment: Optional[Assignment] = None


class ClaimNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str


class ClaimNodeResponse(BaseModel):
    success: bool
    node: Optional[Node] = None
    assignment: Optional[Assignment] = None
    error: Optional[str] = None


class NodeStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    progress: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    message: Optional[str] = None


class NodeStatusResponse(BaseModel):
    success: bool


class SubmitImplementationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    file_paths: list[str]
    actual_interface: ActualInterface
    notes: Optional[str] = None


class SubmitImplementationResponse(BaseModel):
    success: bool
    node: Optional[Node] = None


class ReleaseNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str


class ReleaseNodeResponse(BaseModel):
    success: bool


class FreezeResponse(BaseModel):
    contract: Contract
    frozen_hash: str


class ImplementMode(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"


class ImplementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: ImplementMode = ImplementMode.INTERNAL


class ImplementResponse(BaseModel):
    job_id: str
    mode: ImplementMode
    assignments_created: int


class GeneratedFilesResponse(BaseModel):
    """Metadata about generated files (actual zip sent as file response)."""
    session_id: str
    node_count: int
    file_count: int


# ---------------------------------------------------------------------------
# M5: WebSocket message models
# ---------------------------------------------------------------------------

class WSMessageType(str, Enum):
    CONTRACT_UPDATED = "contract_updated"
    NODE_STATUS_CHANGED = "node_status_changed"
    NODE_PROGRESS = "node_progress"
    NODE_CLAIMED = "node_claimed"
    AGENT_CONNECTED = "agent_connected"
    IMPLEMENTATION_COMPLETE = "implementation_complete"
    INTEGRATION_RESULT = "integration_result"
    ERROR = "error"


class WSMessage(BaseModel):
    """Base WebSocket message."""
    model_config = ConfigDict(extra="allow")
    type: WSMessageType
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class WSNodeStatusChanged(WSMessage):
    type: WSMessageType = WSMessageType.NODE_STATUS_CHANGED
    node_id: str
    status: NodeStatus
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None


class WSNodeProgress(WSMessage):
    type: WSMessageType = WSMessageType.NODE_PROGRESS
    node_id: str
    agent_id: str
    progress: float
    message: Optional[str] = None


class WSNodeClaimed(WSMessage):
    type: WSMessageType = WSMessageType.NODE_CLAIMED
    node_id: str
    agent_id: str
    agent_name: str


class WSAgentConnected(WSMessage):
    type: WSMessageType = WSMessageType.AGENT_CONNECTED
    agent_id: str
    agent_name: str
    agent_type: Optional[AgentType] = None


class WSImplementationComplete(WSMessage):
    type: WSMessageType = WSMessageType.IMPLEMENTATION_COMPLETE
    success: bool
    nodes_implemented: int
    nodes_failed: int


class WSIntegrationResult(WSMessage):
    type: WSMessageType = WSMessageType.INTEGRATION_RESULT
    mismatches: list[IntegrationMismatch]


class WSError(WSMessage):
    type: WSMessageType = WSMessageType.ERROR
    message: str
    recoverable: bool = True
```

---

## Part 2: Backend — Core Modules

### 2.1 Create `app/agents.py`

```python
"""External agent registry for Phase 2 coordination.

Agents (Devin, Cursor, Claude Code, etc.) register via API and can claim
nodes to implement. The registry tracks agent status and heartbeats.
"""

from datetime import datetime, timedelta
from typing import Optional
import uuid

from .logger import get_logger
from .schemas import Agent, AgentStatus, AgentType

log = get_logger(__name__)

# In-memory store (for hackathon; production would use SQLite)
_agents: dict[str, Agent] = {}

DISCONNECT_THRESHOLD = timedelta(seconds=60)


def register_agent(name: str, agent_type: AgentType = AgentType.CUSTOM) -> Agent:
    """Register a new external agent."""
    agent_id = str(uuid.uuid4())
    now = datetime.utcnow()
    agent = Agent(
        id=agent_id,
        name=name,
        type=agent_type,
        registered_at=now,
        last_seen_at=now,
        status=AgentStatus.IDLE,
    )
    _agents[agent_id] = agent
    log.info("agents.registered", extra={
        "agent_id": agent_id,
        "name": name,
        "type": agent_type.value,
    })
    return agent


def get_agent(agent_id: str) -> Optional[Agent]:
    """Get an agent by ID, updating last_seen_at (heartbeat)."""
    agent = _agents.get(agent_id)
    if agent:
        agent.last_seen_at = datetime.utcnow()
        _check_status(agent)
    return agent


def list_agents() -> list[Agent]:
    """List all registered agents, updating disconnected status."""
    for agent in _agents.values():
        _check_status(agent)
    return list(_agents.values())


def heartbeat(agent_id: str) -> Optional[Agent]:
    """Update agent's last_seen_at timestamp."""
    return get_agent(agent_id)


def set_agent_status(agent_id: str, status: AgentStatus) -> Optional[Agent]:
    """Update agent status (active/idle)."""
    agent = _agents.get(agent_id)
    if agent:
        agent.status = status
        agent.last_seen_at = datetime.utcnow()
        log.info("agents.status_changed", extra={
            "agent_id": agent_id,
            "status": status.value,
        })
    return agent


def set_agent_assignment(agent_id: str, assignment_id: Optional[str]) -> Optional[Agent]:
    """Update agent's current assignment."""
    agent = _agents.get(agent_id)
    if agent:
        agent.current_assignment = assignment_id
        agent.status = AgentStatus.ACTIVE if assignment_id else AgentStatus.IDLE
        agent.last_seen_at = datetime.utcnow()
    return agent


def _check_status(agent: Agent) -> None:
    """Check if agent should be marked disconnected."""
    if datetime.utcnow() - agent.last_seen_at > DISCONNECT_THRESHOLD:
        if agent.status != AgentStatus.DISCONNECTED:
            agent.status = AgentStatus.DISCONNECTED
            log.warning("agents.disconnected", extra={
                "agent_id": agent.id,
                "name": agent.name,
                "last_seen": agent.last_seen_at.isoformat(),
            })
```

### 2.2 Create `app/assignments.py`

```python
"""Work assignments for Phase 2 implementation.

Assignments are created by the orchestrator when implementation starts.
Agents claim assignments to work on nodes.
"""

from datetime import datetime
from typing import Optional
import uuid

from .logger import get_logger
from .schemas import (
    Assignment, AssignmentPayload, AssignmentResult, AssignmentStatus,
    Contract, Node, NeighborInterface, Implementation, ActualInterface,
)

log = get_logger(__name__)

# In-memory store keyed by session_id -> assignment_id -> Assignment
_assignments: dict[str, dict[str, Assignment]] = {}


def create_assignment(
    session_id: str,
    node: Node,
    contract_snapshot: Contract,
    incoming_interfaces: list[NeighborInterface],
    outgoing_interfaces: list[NeighborInterface],
) -> Assignment:
    """Create a new assignment for a node."""
    assignment_id = str(uuid.uuid4())
    assignment = Assignment(
        id=assignment_id,
        session_id=session_id,
        node_id=node.id,
        created_at=datetime.utcnow(),
        status=AssignmentStatus.PENDING,
        payload=AssignmentPayload(
            contract_snapshot=contract_snapshot,
            node=node,
            neighbor_interfaces={
                "incoming": incoming_interfaces,
                "outgoing": outgoing_interfaces,
            },
        ),
    )
    
    if session_id not in _assignments:
        _assignments[session_id] = {}
    _assignments[session_id][assignment_id] = assignment
    
    log.info("assignments.created", extra={
        "assignment_id": assignment_id,
        "session_id": session_id,
        "node_id": node.id,
        "node_name": node.name,
    })
    return assignment


def get_assignment(session_id: str, assignment_id: str) -> Optional[Assignment]:
    """Get a specific assignment."""
    return _assignments.get(session_id, {}).get(assignment_id)


def get_assignments_for_session(session_id: str) -> list[Assignment]:
    """Get all assignments for a session."""
    return list(_assignments.get(session_id, {}).values())


def get_available_assignments(session_id: str) -> list[Assignment]:
    """Get unclaimed assignments for a session."""
    return [
        a for a in _assignments.get(session_id, {}).values()
        if a.status == AssignmentStatus.PENDING
    ]


def get_assignment_for_node(session_id: str, node_id: str) -> Optional[Assignment]:
    """Get the assignment for a specific node."""
    for assignment in _assignments.get(session_id, {}).values():
        if assignment.node_id == node_id:
            return assignment
    return None


def claim_assignment(
    session_id: str,
    node_id: str,
    agent_id: str,
) -> Optional[Assignment]:
    """Claim an assignment for a node. Returns None if already claimed."""
    assignment = get_assignment_for_node(session_id, node_id)
    if not assignment:
        log.warning("assignments.claim_failed_not_found", extra={
            "session_id": session_id,
            "node_id": node_id,
        })
        return None
    
    if assignment.status != AssignmentStatus.PENDING:
        log.warning("assignments.claim_failed_not_available", extra={
            "assignment_id": assignment.id,
            "current_status": assignment.status.value,
            "current_agent": assignment.assigned_to,
        })
        return None
    
    assignment.assigned_to = agent_id
    assignment.assigned_at = datetime.utcnow()
    assignment.status = AssignmentStatus.IN_PROGRESS
    
    log.info("assignments.claimed", extra={
        "assignment_id": assignment.id,
        "node_id": node_id,
        "agent_id": agent_id,
    })
    return assignment


def complete_assignment(
    session_id: str,
    node_id: str,
    agent_id: str,
    file_paths: list[str],
    actual_interface: ActualInterface,
    notes: Optional[str] = None,
    duration_ms: int = 0,
) -> Optional[Assignment]:
    """Mark an assignment as completed with implementation details."""
    assignment = get_assignment_for_node(session_id, node_id)
    if not assignment:
        return None
    
    if assignment.assigned_to != agent_id:
        log.warning("assignments.complete_wrong_agent", extra={
            "assignment_id": assignment.id,
            "expected_agent": assignment.assigned_to,
            "actual_agent": agent_id,
        })
        return None
    
    assignment.status = AssignmentStatus.COMPLETED
    assignment.result = AssignmentResult(
        implementation=Implementation(
            file_paths=file_paths,
            notes=notes,
            actual_interface=actual_interface,
            completed_at=datetime.utcnow(),
        ),
        completed_at=datetime.utcnow(),
        duration_ms=duration_ms,
    )
    
    log.info("assignments.completed", extra={
        "assignment_id": assignment.id,
        "node_id": node_id,
        "file_count": len(file_paths),
        "duration_ms": duration_ms,
    })
    return assignment


def release_assignment(
    session_id: str,
    node_id: str,
    agent_id: str,
) -> Optional[Assignment]:
    """Release a claimed assignment (on failure/abort)."""
    assignment = get_assignment_for_node(session_id, node_id)
    if not assignment or assignment.assigned_to != agent_id:
        return None
    
    assignment.assigned_to = None
    assignment.assigned_at = None
    assignment.status = AssignmentStatus.PENDING
    
    log.info("assignments.released", extra={
        "assignment_id": assignment.id,
        "node_id": node_id,
        "agent_id": agent_id,
    })
    return assignment


def fail_assignment(session_id: str, node_id: str) -> Optional[Assignment]:
    """Mark an assignment as failed."""
    assignment = get_assignment_for_node(session_id, node_id)
    if assignment:
        assignment.status = AssignmentStatus.FAILED
        log.warning("assignments.failed", extra={
            "assignment_id": assignment.id,
            "node_id": node_id,
        })
    return assignment
```

### 2.3 Create `app/ws.py`

```python
"""WebSocket endpoint for live Phase 2 updates.

The connection manager tracks active connections per session and broadcasts
status changes as agents work on nodes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
import json

from fastapi import WebSocket, WebSocketDisconnect

from .logger import get_logger
from .schemas import (
    WSMessage, WSMessageType, WSNodeStatusChanged, WSNodeClaimed,
    WSNodeProgress, WSAgentConnected, WSImplementationComplete,
    WSIntegrationResult, WSError, NodeStatus, AgentType,
    IntegrationMismatch,
)

log = get_logger(__name__)


class ConnectionManager:
    """Manages WebSocket connections per session."""
    
    def __init__(self):
        # session_id -> list of active connections
        self._connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()
    
    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection for a session."""
        await websocket.accept()
        async with self._lock:
            if session_id not in self._connections:
                self._connections[session_id] = []
            self._connections[session_id].append(websocket)
        log.debug("ws.connected", extra={
            "session_id": session_id,
            "total_connections": len(self._connections.get(session_id, [])),
        })
    
    async def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            if session_id in self._connections:
                try:
                    self._connections[session_id].remove(websocket)
                except ValueError:
                    pass
                if not self._connections[session_id]:
                    del self._connections[session_id]
        log.debug("ws.disconnected", extra={"session_id": session_id})
    
    async def broadcast(self, session_id: str, message: WSMessage) -> None:
        """Send a message to all connections for a session."""
        connections = self._connections.get(session_id, [])
        if not connections:
            return
        
        # Serialize message to JSON
        data = message.model_dump(mode="json")
        data_str = json.dumps(data)
        
        log.debug("ws.broadcast", extra={
            "session_id": session_id,
            "type": message.type.value,
            "recipients": len(connections),
        })
        
        # Send to all connections, removing dead ones
        dead_connections = []
        for connection in connections:
            try:
                await connection.send_text(data_str)
            except Exception:
                dead_connections.append(connection)
        
        # Clean up dead connections
        for conn in dead_connections:
            await self.disconnect(session_id, conn)
    
    def get_connection_count(self, session_id: str) -> int:
        """Get the number of active connections for a session."""
        return len(self._connections.get(session_id, []))


# Global connection manager instance
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Broadcast helper functions
# ---------------------------------------------------------------------------

async def broadcast_node_status_changed(
    session_id: str,
    node_id: str,
    status: NodeStatus,
    agent_id: str | None = None,
    agent_name: str | None = None,
) -> None:
    """Broadcast a node status change."""
    msg = WSNodeStatusChanged(
        node_id=node_id,
        status=status,
        agent_id=agent_id,
        agent_name=agent_name,
    )
    await manager.broadcast(session_id, msg)


async def broadcast_node_claimed(
    session_id: str,
    node_id: str,
    agent_id: str,
    agent_name: str,
) -> None:
    """Broadcast that a node was claimed by an agent."""
    msg = WSNodeClaimed(
        node_id=node_id,
        agent_id=agent_id,
        agent_name=agent_name,
    )
    await manager.broadcast(session_id, msg)


async def broadcast_node_progress(
    session_id: str,
    node_id: str,
    agent_id: str,
    progress: float,
    message: str | None = None,
) -> None:
    """Broadcast progress update for a node."""
    msg = WSNodeProgress(
        node_id=node_id,
        agent_id=agent_id,
        progress=progress,
        message=message,
    )
    await manager.broadcast(session_id, msg)


async def broadcast_agent_connected(
    session_id: str,
    agent_id: str,
    agent_name: str,
    agent_type: AgentType | None = None,
) -> None:
    """Broadcast that an agent connected."""
    msg = WSAgentConnected(
        agent_id=agent_id,
        agent_name=agent_name,
        agent_type=agent_type,
    )
    await manager.broadcast(session_id, msg)


async def broadcast_implementation_complete(
    session_id: str,
    success: bool,
    nodes_implemented: int,
    nodes_failed: int,
) -> None:
    """Broadcast that implementation phase completed."""
    msg = WSImplementationComplete(
        success=success,
        nodes_implemented=nodes_implemented,
        nodes_failed=nodes_failed,
    )
    await manager.broadcast(session_id, msg)


async def broadcast_integration_result(
    session_id: str,
    mismatches: list[IntegrationMismatch],
) -> None:
    """Broadcast integration pass results."""
    msg = WSIntegrationResult(mismatches=mismatches)
    await manager.broadcast(session_id, msg)


async def broadcast_error(
    session_id: str,
    message: str,
    recoverable: bool = True,
) -> None:
    """Broadcast an error message."""
    msg = WSError(message=message, recoverable=recoverable)
    await manager.broadcast(session_id, msg)
```

### 2.4 Create `app/orchestrator.py`

```python
"""Phase 2 Orchestrator: freeze, dispatch subagents, integration pass.

The orchestrator manages the transition from a verified contract to
generated code. It supports both internal subagents (LLM calls) and
external agent coordination.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

from . import agents as agents_svc
from . import assignments as assignments_svc
from . import contract as contract_svc
from . import ws
from .llm import call_structured
from .logger import get_logger
from .schemas import (
    Contract, ContractStatus, Node, NodeStatus, Edge, EdgeKind,
    Assignment, AssignmentStatus, NeighborInterface,
    Implementation, ActualInterface, IntegrationMismatch,
    AgentStatus, AgentType, Severity,
)

log = get_logger(__name__)

# Output directory for generated files
GENERATED_DIR = Path("generated")


def freeze_contract(session_id: str) -> Contract:
    """Lock a contract for implementation.
    
    - Sets status to 'verified'
    - Computes SHA-256 hash of contract JSON
    - Sets frozen_at timestamp
    - Prevents further structural changes
    """
    session = contract_svc.get_session(session_id)
    contract = session.contract
    
    if contract.meta.status == ContractStatus.VERIFIED:
        log.warning("orchestrator.already_frozen", extra={"session_id": session_id})
        return contract
    
    if contract.meta.status != ContractStatus.DRAFTING:
        raise ValueError(f"Cannot freeze contract in status: {contract.meta.status}")
    
    # Compute hash of contract
    contract_json = contract.model_dump_json(exclude_none=True)
    frozen_hash = hashlib.sha256(contract_json.encode()).hexdigest()
    
    # Update contract meta
    contract.meta.status = ContractStatus.VERIFIED
    contract.meta.frozen_at = datetime.utcnow()
    contract.meta.frozen_hash = frozen_hash
    contract.meta.version += 1
    
    # Persist
    contract_svc.update_contract(session_id, contract)
    
    log.info("orchestrator.frozen", extra={
        "session_id": session_id,
        "hash": frozen_hash[:16] + "...",
        "node_count": len(contract.nodes),
        "edge_count": len(contract.edges),
    })
    
    return contract


def identify_leaf_nodes(contract: Contract) -> list[Node]:
    """Identify leaf nodes for implementation.
    
    Leaf nodes are those with no outgoing data or control edges
    (they don't depend on other nodes' implementation outputs).
    """
    # Build set of nodes that ARE dependencies (have outgoing data/control)
    non_leaf_ids = set()
    for edge in contract.edges:
        if edge.kind in (EdgeKind.DATA, EdgeKind.CONTROL):
            non_leaf_ids.add(edge.source)
    
    leaf_nodes = [n for n in contract.nodes if n.id not in non_leaf_ids]
    
    log.debug("orchestrator.leaf_nodes_identified", extra={
        "total_nodes": len(contract.nodes),
        "leaf_nodes": len(leaf_nodes),
        "leaf_ids": [n.id for n in leaf_nodes],
    })
    
    return leaf_nodes


def get_neighbor_interfaces(
    node: Node,
    contract: Contract,
) -> tuple[list[NeighborInterface], list[NeighborInterface]]:
    """Get incoming and outgoing interfaces for a node."""
    incoming = []
    outgoing = []
    
    node_map = {n.id: n for n in contract.nodes}
    
    for edge in contract.edges:
        if edge.target == node.id:
            source_node = node_map.get(edge.source)
            if source_node:
                incoming.append(NeighborInterface(
                    edge_id=edge.id,
                    node_id=edge.source,
                    node_name=source_node.name,
                    payload_schema=edge.payload_schema,
                ))
        elif edge.source == node.id:
            target_node = node_map.get(edge.target)
            if target_node:
                outgoing.append(NeighborInterface(
                    edge_id=edge.id,
                    node_id=edge.target,
                    node_name=target_node.name,
                    payload_schema=edge.payload_schema,
                ))
    
    return incoming, outgoing


def create_assignments(session_id: str) -> list[Assignment]:
    """Create assignments for all leaf nodes."""
    session = contract_svc.get_session(session_id)
    contract = session.contract
    
    if contract.meta.status != ContractStatus.VERIFIED:
        raise ValueError("Contract must be frozen (verified) before creating assignments")
    
    leaf_nodes = identify_leaf_nodes(contract)
    assignments = []
    
    for node in leaf_nodes:
        incoming, outgoing = get_neighbor_interfaces(node, contract)
        assignment = assignments_svc.create_assignment(
            session_id=session_id,
            node=node,
            contract_snapshot=contract,
            incoming_interfaces=incoming,
            outgoing_interfaces=outgoing,
        )
        assignments.append(assignment)
    
    log.info("orchestrator.assignments_created", extra={
        "session_id": session_id,
        "count": len(assignments),
    })
    
    return assignments


async def run_implementation_internal(session_id: str) -> None:
    """Run implementation using internal LLM subagents.
    
    Processes leaf nodes sequentially (for demo simplicity).
    Production would use asyncio.gather for parallelism.
    """
    session = contract_svc.get_session(session_id)
    contract = session.contract
    
    # Update contract status
    contract.meta.status = ContractStatus.IMPLEMENTING
    contract_svc.update_contract(session_id, contract)
    
    assignments = assignments_svc.get_assignments_for_session(session_id)
    
    nodes_implemented = 0
    nodes_failed = 0
    
    for assignment in assignments:
        node = assignment.payload.node
        
        # Broadcast status change
        await ws.broadcast_node_status_changed(
            session_id, node.id, NodeStatus.IN_PROGRESS
        )
        
        # Update node status in contract
        for n in contract.nodes:
            if n.id == node.id:
                n.status = NodeStatus.IN_PROGRESS
                break
        contract_svc.update_contract(session_id, contract)
        
        try:
            # Call LLM subagent
            start_time = datetime.utcnow()
            implementation = await _run_subagent(assignment)
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # Write generated files
            output_dir = GENERATED_DIR / session_id / node.id
            output_dir.mkdir(parents=True, exist_ok=True)
            
            file_paths = []
            for i, content in enumerate(implementation.get("files", [])):
                filename = content.get("filename", f"file_{i}.py")
                file_path = output_dir / filename
                file_path.write_text(content.get("content", ""))
                file_paths.append(str(file_path))
            
            # Update assignment
            actual_interface = ActualInterface(
                exports=implementation.get("exports", []),
                imports=implementation.get("imports", []),
                public_functions=implementation.get("public_functions", []),
            )
            
            assignments_svc.complete_assignment(
                session_id=session_id,
                node_id=node.id,
                agent_id="internal",
                file_paths=file_paths,
                actual_interface=actual_interface,
                notes=implementation.get("notes"),
                duration_ms=duration_ms,
            )
            
            # Update node in contract
            for n in contract.nodes:
                if n.id == node.id:
                    n.status = NodeStatus.IMPLEMENTED
                    n.implementation = Implementation(
                        file_paths=file_paths,
                        notes=implementation.get("notes"),
                        actual_interface=actual_interface,
                        completed_at=datetime.utcnow(),
                    )
                    break
            contract_svc.update_contract(session_id, contract)
            
            # Broadcast completion
            await ws.broadcast_node_status_changed(
                session_id, node.id, NodeStatus.IMPLEMENTED
            )
            
            nodes_implemented += 1
            
            log.info("orchestrator.node_implemented", extra={
                "session_id": session_id,
                "node_id": node.id,
                "node_name": node.name,
                "duration_ms": duration_ms,
                "file_count": len(file_paths),
            })
            
        except Exception as e:
            log.error("orchestrator.node_failed", extra={
                "session_id": session_id,
                "node_id": node.id,
                "error": str(e),
            })
            
            assignments_svc.fail_assignment(session_id, node.id)
            
            for n in contract.nodes:
                if n.id == node.id:
                    n.status = NodeStatus.FAILED
                    break
            contract_svc.update_contract(session_id, contract)
            
            await ws.broadcast_node_status_changed(
                session_id, node.id, NodeStatus.FAILED
            )
            
            nodes_failed += 1
    
    # Run integration pass
    mismatches = await run_integration_pass(session_id)
    
    # Update final status
    contract.meta.status = ContractStatus.COMPLETE
    contract_svc.update_contract(session_id, contract)
    
    # Write final contract
    contract_path = GENERATED_DIR / session_id / "contract.json"
    contract_path.write_text(contract.model_dump_json(indent=2))
    
    # Broadcast completion
    await ws.broadcast_implementation_complete(
        session_id,
        success=(nodes_failed == 0),
        nodes_implemented=nodes_implemented,
        nodes_failed=nodes_failed,
    )
    
    log.info("orchestrator.implementation_complete", extra={
        "session_id": session_id,
        "nodes_implemented": nodes_implemented,
        "nodes_failed": nodes_failed,
        "mismatches": len(mismatches),
    })


async def _run_subagent(assignment: Assignment) -> dict:
    """Call LLM to implement a single node.
    
    Uses the subagent prompt with the node's context and neighbor interfaces.
    """
    from .prompts import load_prompt
    
    node = assignment.payload.node
    contract = assignment.payload.contract_snapshot
    neighbors = assignment.payload.neighbor_interfaces
    
    # Build context for the subagent
    context = {
        "node": node.model_dump(),
        "incoming_interfaces": [n.model_dump() for n in neighbors.get("incoming", [])],
        "outgoing_interfaces": [n.model_dump() for n in neighbors.get("outgoing", [])],
        "contract_intent": contract.meta.stated_intent,
    }
    
    system_prompt = load_prompt("subagent")
    user_prompt = f"""Implement the following node:

Node: {node.name}
Kind: {node.kind}
Description: {node.description}

Responsibilities:
{chr(10).join(f"- {r}" for r in node.responsibilities)}

Incoming interfaces (data you receive):
{json.dumps(context["incoming_interfaces"], indent=2)}

Outgoing interfaces (data you produce):
{json.dumps(context["outgoing_interfaces"], indent=2)}

System intent: {contract.meta.stated_intent}

Generate Python code that implements this node's responsibilities.
Code against the declared interfaces, not your assumptions.
"""
    
    # For the demo, return a mock implementation
    # In production, this would call the LLM
    try:
        # Try to call LLM if available
        from pydantic import BaseModel
        
        class SubagentOutput(BaseModel):
            files: list[dict]  # [{filename, content}]
            exports: list[str]
            imports: list[str]
            public_functions: list[dict]
            notes: Optional[str] = None
        
        result = call_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=SubagentOutput,
        )
        return result.model_dump()
    except Exception as e:
        log.warning("orchestrator.subagent_llm_failed", extra={
            "node_id": node.id,
            "error": str(e),
        })
        # Return mock implementation for demo
        return {
            "files": [{
                "filename": f"{node.id.replace('-', '_')}.py",
                "content": f'''"""Implementation for {node.name}."""

# Auto-generated implementation
# Node: {node.name}
# Kind: {node.kind}

def main():
    """Entry point for {node.name}."""
    pass

if __name__ == "__main__":
    main()
''',
            }],
            "exports": ["main"],
            "imports": [],
            "public_functions": [{"name": "main", "signature": "def main() -> None"}],
            "notes": "Mock implementation for demo",
        }


async def run_integration_pass(session_id: str) -> list[IntegrationMismatch]:
    """Compare actual interfaces against declared payload schemas.
    
    Returns mismatches that will be surfaced as violations to the user.
    """
    session = contract_svc.get_session(session_id)
    contract = session.contract
    
    mismatches = []
    node_map = {n.id: n for n in contract.nodes}
    
    for edge in contract.edges:
        if edge.kind not in (EdgeKind.DATA, EdgeKind.EVENT):
            continue
        
        source_node = node_map.get(edge.source)
        target_node = node_map.get(edge.target)
        
        if not source_node or not target_node:
            continue
        
        # Check if implementations exist
        source_impl = source_node.implementation
        target_impl = target_node.implementation
        
        if not source_impl or not target_impl:
            continue
        
        # Compare declared vs actual (simplified check for demo)
        # A real implementation would do semantic comparison
        declared = edge.payload_schema or {}
        source_actual = source_impl.actual_interface
        target_actual = target_impl.actual_interface
        
        # Check if source exports what the edge declares
        # and target imports what it expects
        # (This is a simplified heuristic)
        if declared and source_actual:
            # Check if source has exports that match declared schema
            # For demo, just check if any exports exist
            pass
        
    log.info("orchestrator.integration_pass_complete", extra={
        "session_id": session_id,
        "edges_checked": len([e for e in contract.edges if e.kind in (EdgeKind.DATA, EdgeKind.EVENT)]),
        "mismatches_found": len(mismatches),
    })
    
    # Broadcast results
    await ws.broadcast_integration_result(session_id, mismatches)
    
    return mismatches


def get_generated_files(session_id: str) -> Path:
    """Get the path to generated files for a session."""
    output_dir = GENERATED_DIR / session_id
    if not output_dir.exists():
        raise ValueError(f"No generated files for session {session_id}")
    return output_dir
```

### 2.5 Create `app/prompts/subagent.md`

```markdown
# Subagent System Prompt

You are a code implementation agent. You receive a specific node from an architecture contract and generate Python code that implements that node's responsibilities.

## Critical Rules

1. **Code against declared interfaces, not assumptions.** The `incoming_interfaces` and `outgoing_interfaces` define exactly what data you receive and produce. Do not invent additional data or modify schemas.

2. **Single responsibility.** Implement ONLY the node you are assigned. Do not implement other nodes or shared utilities unless they are internal to your node.

3. **Append-only output.** You write files only to your node's directory. You cannot modify other nodes' code.

4. **Match the contract.** Your `actual_interface` (exports, imports, public functions) must match or be compatible with the declared `payload_schema` on your edges.

## Output Format

Respond with valid JSON containing:
- `files`: Array of `{filename, content}` objects
- `exports`: List of symbols your code exports
- `imports`: List of external modules you import
- `public_functions`: List of `{name, signature}` for public functions
- `notes`: Optional implementation notes

## Example

Given a node "DM Reader" that receives OAuth tokens and outputs DM summaries:

```json
{
  "files": [
    {
      "filename": "dm_reader.py",
      "content": "\"\"\"Read Slack DMs.\"\"\"\\n\\nfrom slack_sdk import WebClient\\n\\ndef read_dms(oauth_token: str) -> list[dict]:\\n    client = WebClient(token=oauth_token)\\n    return client.conversations_list(types='im')['channels']"
    }
  ],
  "exports": ["read_dms"],
  "imports": ["slack_sdk"],
  "public_functions": [
    {"name": "read_dms", "signature": "def read_dms(oauth_token: str) -> list[dict]"}
  ],
  "notes": "Uses official Slack SDK for reliability"
}
```
```

### 2.6 Create `app/prompts/integrator.md`

```markdown
# Integrator System Prompt

You are an integration verification agent. You compare the **actual interfaces** that implementation subagents produced against the **declared interfaces** in the architecture contract.

## Your Task

For each edge of kind `data` or `event`:
1. Look at `edge.payload_schema` — this is what was declared
2. Look at `source.implementation.actual_interface` — this is what the source node actually exports
3. Look at `target.implementation.actual_interface` — this is what the target node actually imports/expects

## Mismatch Types

Report a mismatch when:
- **Missing export**: Source doesn't export what the edge declares
- **Missing import**: Target doesn't import/handle what the edge declares
- **Type mismatch**: Exported type doesn't match declared schema
- **Extra fields**: Actual interface has fields not in declared schema (may be intentional, report as warning)

## Output Format

Respond with a list of mismatches:

```json
{
  "mismatches": [
    {
      "edge_id": "e-123",
      "source_node_id": "n-1",
      "target_node_id": "n-2",
      "mismatch_description": "Source exports `get_dms()` returning `list[str]` but edge declares `list[DMMessage]`",
      "severity": "error"
    }
  ]
}
```

If all interfaces match, return an empty list.
```

---

## Part 3: Backend — API Routes

### 3.1 Update `app/api.py`

Add these routes to the existing router:

```python
# ---------------------------------------------------------------------------
# M5: Phase 2 Orchestration Routes
# ---------------------------------------------------------------------------

from fastapi import BackgroundTasks
from fastapi.responses import FileResponse
import zipfile
import tempfile

from . import agents as agents_svc
from . import assignments as assignments_svc
from . import orchestrator
from .schemas import (
    RegisterAgentRequest, RegisterAgentResponse, ListAgentsResponse,
    GetAssignmentResponse, ClaimNodeRequest, ClaimNodeResponse,
    NodeStatusRequest, NodeStatusResponse,
    SubmitImplementationRequest, SubmitImplementationResponse,
    ReleaseNodeRequest, ReleaseNodeResponse,
    FreezeResponse, ImplementRequest, ImplementResponse,
    ImplementMode, NodeStatus,
)


@router.post("/agents", response_model=RegisterAgentResponse, status_code=201)
def register_agent(request: RegisterAgentRequest) -> RegisterAgentResponse:
    """Register an external agent."""
    agent = agents_svc.register_agent(request.name, request.type)
    return RegisterAgentResponse(agent_id=agent.id, agent=agent)


@router.get("/agents", response_model=ListAgentsResponse)
def list_agents() -> ListAgentsResponse:
    """List all registered agents."""
    agents = agents_svc.list_agents()
    return ListAgentsResponse(agents=agents)


@router.get("/sessions/{session_id}/assignments", response_model=GetAssignmentResponse)
def get_assignment(session_id: str, agent_id: str) -> GetAssignmentResponse:
    """Poll for an available assignment."""
    # Heartbeat the agent
    agents_svc.heartbeat(agent_id)
    
    # Find an available assignment
    available = assignments_svc.get_available_assignments(session_id)
    if not available:
        return GetAssignmentResponse(assignment=None)
    
    return GetAssignmentResponse(assignment=available[0])


@router.post(
    "/sessions/{session_id}/nodes/{node_id}/claim",
    response_model=ClaimNodeResponse,
)
async def claim_node(
    session_id: str,
    node_id: str,
    request: ClaimNodeRequest,
) -> ClaimNodeResponse:
    """Claim a node for implementation."""
    assignment = assignments_svc.claim_assignment(
        session_id, node_id, request.agent_id
    )
    
    if not assignment:
        return ClaimNodeResponse(
            success=False,
            error="Node not available or already claimed",
        )
    
    # Update agent status
    agent = agents_svc.set_agent_assignment(request.agent_id, assignment.id)
    
    # Update node status in contract
    session = contract_svc.get_session(session_id)
    for node in session.contract.nodes:
        if node.id == node_id:
            node.status = NodeStatus.IN_PROGRESS
            contract_svc.update_contract(session_id, session.contract)
            
            # Broadcast
            await ws.broadcast_node_claimed(
                session_id, node_id, request.agent_id, agent.name if agent else "Unknown"
            )
            await ws.broadcast_node_status_changed(
                session_id, node_id, NodeStatus.IN_PROGRESS,
                agent_id=request.agent_id,
                agent_name=agent.name if agent else None,
            )
            
            return ClaimNodeResponse(success=True, node=node, assignment=assignment)
    
    return ClaimNodeResponse(success=False, error="Node not found")


@router.post(
    "/sessions/{session_id}/nodes/{node_id}/status",
    response_model=NodeStatusResponse,
)
async def report_node_status(
    session_id: str,
    node_id: str,
    request: NodeStatusRequest,
) -> NodeStatusResponse:
    """Report progress on a claimed node."""
    agents_svc.heartbeat(request.agent_id)
    
    if request.progress is not None:
        await ws.broadcast_node_progress(
            session_id, node_id, request.agent_id,
            request.progress, request.message,
        )
    
    return NodeStatusResponse(success=True)


@router.post(
    "/sessions/{session_id}/nodes/{node_id}/implementation",
    response_model=SubmitImplementationResponse,
)
async def submit_implementation(
    session_id: str,
    node_id: str,
    request: SubmitImplementationRequest,
) -> SubmitImplementationResponse:
    """Submit implementation for a node."""
    assignment = assignments_svc.complete_assignment(
        session_id=session_id,
        node_id=node_id,
        agent_id=request.agent_id,
        file_paths=request.file_paths,
        actual_interface=request.actual_interface,
        notes=request.notes,
    )
    
    if not assignment:
        return SubmitImplementationResponse(success=False, node=None)
    
    # Update agent status
    agents_svc.set_agent_assignment(request.agent_id, None)
    
    # Update node in contract
    session = contract_svc.get_session(session_id)
    for node in session.contract.nodes:
        if node.id == node_id:
            node.status = NodeStatus.IMPLEMENTED
            node.implementation = Implementation(
                file_paths=request.file_paths,
                notes=request.notes,
                actual_interface=request.actual_interface,
                completed_at=datetime.utcnow(),
            )
            contract_svc.update_contract(session_id, session.contract)
            
            await ws.broadcast_node_status_changed(
                session_id, node_id, NodeStatus.IMPLEMENTED,
            )
            
            return SubmitImplementationResponse(success=True, node=node)
    
    return SubmitImplementationResponse(success=False, node=None)


@router.post(
    "/sessions/{session_id}/nodes/{node_id}/release",
    response_model=ReleaseNodeResponse,
)
async def release_node(
    session_id: str,
    node_id: str,
    request: ReleaseNodeRequest,
) -> ReleaseNodeResponse:
    """Release a claimed node (on failure/abort)."""
    assignment = assignments_svc.release_assignment(
        session_id, node_id, request.agent_id
    )
    
    if assignment:
        agents_svc.set_agent_assignment(request.agent_id, None)
        
        # Reset node status
        session = contract_svc.get_session(session_id)
        for node in session.contract.nodes:
            if node.id == node_id:
                node.status = NodeStatus.DRAFTED
                contract_svc.update_contract(session_id, session.contract)
                break
    
    return ReleaseNodeResponse(success=assignment is not None)


@router.post("/sessions/{session_id}/freeze", response_model=FreezeResponse)
def freeze_session(session_id: str) -> FreezeResponse:
    """Freeze the contract for implementation."""
    try:
        contract = orchestrator.freeze_contract(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return FreezeResponse(
        contract=contract,
        frozen_hash=contract.meta.frozen_hash or "",
    )


@router.post("/sessions/{session_id}/implement", response_model=ImplementResponse)
async def implement_session(
    session_id: str,
    request: ImplementRequest,
    background_tasks: BackgroundTasks,
) -> ImplementResponse:
    """Start Phase 2 implementation."""
    try:
        session = contract_svc.get_session(session_id)
    except contract_svc.SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    if session.contract.meta.status != ContractStatus.VERIFIED:
        raise HTTPException(
            status_code=400,
            detail="Contract must be frozen before implementation",
        )
    
    # Create assignments
    assignments = orchestrator.create_assignments(session_id)
    
    job_id = str(uuid.uuid4())
    
    if request.mode == ImplementMode.INTERNAL:
        # Run internal implementation in background
        background_tasks.add_task(
            orchestrator.run_implementation_internal,
            session_id,
        )
    # External mode: assignments are created, agents will poll for them
    
    return ImplementResponse(
        job_id=job_id,
        mode=request.mode,
        assignments_created=len(assignments),
    )


@router.get("/sessions/{session_id}/generated")
def get_generated_files(session_id: str) -> FileResponse:
    """Download generated files as a zip."""
    try:
        output_dir = orchestrator.get_generated_files(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    # Create zip file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in output_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(output_dir)
                    zf.write(file_path, arcname)
        tmp_path = tmp.name
    
    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=f"generated_{session_id}.zip",
    )
```

### 3.2 Update `app/main.py`

Add WebSocket route:

```python
from fastapi import WebSocket, WebSocketDisconnect
from .ws import manager

# Add after app creation and before including router:

@app.websocket("/api/v1/sessions/{session_id}/stream")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for live Phase 2 updates."""
    await manager.connect(session_id, websocket)
    try:
        while True:
            # Keep connection alive, handle any client messages
            data = await websocket.receive_text()
            # Could handle client-side messages here if needed
    except WebSocketDisconnect:
        await manager.disconnect(session_id, websocket)
```

---

## Part 4: Frontend

### 4.1 Create `src/state/websocket.ts`

```typescript
import { create } from 'zustand';
import { useContractStore } from './contract';

interface WebSocketState {
  socket: WebSocket | null;
  sessionId: string | null;
  isConnected: boolean;
  connect: (sessionId: string) => void;
  disconnect: () => void;
}

export const useWebSocketStore = create<WebSocketState>((set, get) => ({
  socket: null,
  sessionId: null,
  isConnected: false,

  connect: (sessionId: string) => {
    const existing = get().socket;
    if (existing && get().sessionId === sessionId) {
      return; // Already connected to this session
    }

    // Disconnect existing
    if (existing) {
      existing.close();
    }

    const wsUrl = `ws://localhost:8000/api/v1/sessions/${sessionId}/stream`;
    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log('[WS] Connected to session:', sessionId);
      set({ isConnected: true });
    };

    socket.onclose = () => {
      console.log('[WS] Disconnected');
      set({ isConnected: false });
    };

    socket.onerror = (error) => {
      console.error('[WS] Error:', error);
    };

    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        handleMessage(message);
      } catch (e) {
        console.error('[WS] Failed to parse message:', e);
      }
    };

    set({ socket, sessionId });
  },

  disconnect: () => {
    const { socket } = get();
    if (socket) {
      socket.close();
    }
    set({ socket: null, sessionId: null, isConnected: false });
  },
}));

function handleMessage(message: any) {
  const { updateNodeStatus, setAgentInfo, addMismatch, setImplementationComplete } = 
    useContractStore.getState();

  switch (message.type) {
    case 'node_status_changed':
      updateNodeStatus(message.node_id, message.status, message.agent_id, message.agent_name);
      break;

    case 'node_claimed':
      updateNodeStatus(message.node_id, 'in_progress', message.agent_id, message.agent_name);
      break;

    case 'node_progress':
      // Could add progress tracking to store
      console.log(`[WS] Node ${message.node_id} progress: ${message.progress}`);
      break;

    case 'agent_connected':
      setAgentInfo(message.agent_id, message.agent_name, message.agent_type);
      break;

    case 'implementation_complete':
      setImplementationComplete(message.success, message.nodes_implemented, message.nodes_failed);
      break;

    case 'integration_result':
      for (const mismatch of message.mismatches) {
        addMismatch(mismatch);
      }
      break;

    case 'error':
      console.error('[WS] Server error:', message.message);
      break;

    default:
      console.log('[WS] Unknown message type:', message.type);
  }
}
```

### 4.2 Update `src/state/contract.ts`

Add these fields and actions to the existing store:

```typescript
interface ContractStore {
  // ... existing fields ...
  
  // M5 additions
  isFrozen: boolean;
  isImplementing: boolean;
  implementationMode: 'internal' | 'external' | null;
  connectedAgents: Map<string, { name: string; type?: string }>;
  nodeAgents: Map<string, { agentId: string; agentName: string }>;
  integrationMismatches: any[];
  implementationComplete: boolean;
  implementationSuccess: boolean;
  
  // M5 actions
  setFrozen: (frozen: boolean) => void;
  setImplementing: (implementing: boolean, mode?: 'internal' | 'external') => void;
  updateNodeStatus: (nodeId: string, status: string, agentId?: string, agentName?: string) => void;
  setAgentInfo: (agentId: string, agentName: string, agentType?: string) => void;
  addMismatch: (mismatch: any) => void;
  setImplementationComplete: (success: boolean, implemented: number, failed: number) => void;
}
```

### 4.3 Create `src/components/AgentPanel.tsx`

```typescript
import React from 'react';
import { useContractStore } from '../state/contract';

export const AgentPanel: React.FC = () => {
  const { connectedAgents, nodeAgents, contract } = useContractStore();
  
  const agentList = Array.from(connectedAgents.entries());
  
  return (
    <div className="bg-gray-800 border-l border-gray-700 p-4 w-64">
      <h3 className="text-lg font-semibold text-white mb-4">Connected Agents</h3>
      
      {agentList.length === 0 ? (
        <p className="text-gray-400 text-sm">No agents connected</p>
      ) : (
        <ul className="space-y-3">
          {agentList.map(([agentId, agent]) => {
            // Find nodes assigned to this agent
            const assignedNodes = Array.from(nodeAgents.entries())
              .filter(([_, a]) => a.agentId === agentId)
              .map(([nodeId]) => contract?.nodes.find(n => n.id === nodeId))
              .filter(Boolean);
            
            return (
              <li key={agentId} className="bg-gray-700 rounded p-3">
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${
                    assignedNodes.length > 0 ? 'bg-green-400' : 'bg-gray-400'
                  }`} />
                  <span className="text-white font-medium">{agent.name}</span>
                </div>
                {agent.type && (
                  <span className="text-xs text-gray-400 ml-4">{agent.type}</span>
                )}
                {assignedNodes.length > 0 && (
                  <div className="mt-2 ml-4">
                    <span className="text-xs text-gray-400">Working on:</span>
                    {assignedNodes.map(node => (
                      <div key={node!.id} className="text-sm text-blue-300">
                        {node!.name}
                      </div>
                    ))}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};
```

### 4.4 Update `src/components/ControlBar.tsx`

Add Freeze and Implement buttons:

```typescript
// Add to existing ControlBar component

const { isFrozen, isImplementing, implementationMode, setFrozen, setImplementing } = useContractStore();
const { connect: connectWs } = useWebSocketStore();

const handleFreeze = async () => {
  if (!sessionId) return;
  setLoading(true);
  try {
    const response = await freezeContract(sessionId);
    setFrozen(true);
    updateContract(response.contract);
  } catch (e) {
    setError('Failed to freeze contract');
  } finally {
    setLoading(false);
  }
};

const handleImplement = async (mode: 'internal' | 'external') => {
  if (!sessionId) return;
  
  // Connect WebSocket for live updates
  connectWs(sessionId);
  
  setLoading(true);
  setImplementing(true, mode);
  try {
    await startImplementation(sessionId, mode);
  } catch (e) {
    setError('Failed to start implementation');
    setImplementing(false);
  } finally {
    setLoading(false);
  }
};

// In render, add buttons:
{isFrozen && !isImplementing && (
  <div className="flex gap-2">
    <button
      onClick={() => handleImplement('internal')}
      className="px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700"
    >
      Implement (Internal)
    </button>
    <button
      onClick={() => handleImplement('external')}
      className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700"
    >
      Implement (External)
    </button>
  </div>
)}

{!isFrozen && uvdcScore >= 1.0 && (
  <button
    onClick={handleFreeze}
    disabled={isLoading}
    className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
  >
    Freeze Contract
  </button>
)}
```

### 4.5 Update `src/components/NodeCard.tsx`

Add status animation and agent display:

```typescript
// Add to NodeCard component

const { nodeAgents } = useContractStore();
const agentInfo = nodeAgents.get(node.id);

// Status badge with animation
const statusColors = {
  drafted: 'bg-gray-500',
  in_progress: 'bg-yellow-500 animate-pulse',
  implemented: 'bg-green-500',
  failed: 'bg-red-500',
};

// In render, add:
<div className={`absolute top-2 right-2 w-3 h-3 rounded-full ${statusColors[node.status] || statusColors.drafted}`} />

{agentInfo && (
  <div className="text-xs text-blue-300 mt-1">
    Agent: {agentInfo.agentName}
  </div>
)}
```

### 4.6 Update `src/api/client.ts`

Add new API calls:

```typescript
export async function freezeContract(sessionId: string): Promise<FreezeResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/freeze`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function startImplementation(
  sessionId: string,
  mode: 'internal' | 'external'
): Promise<ImplementResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/implement`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function downloadGenerated(sessionId: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/generated`);
  if (!res.ok) throw new Error(await res.text());
  return res.blob();
}
```

---

## Part 5: Tests

### 5.1 Create `tests/test_orchestrator.py`

```python
import pytest
from app.orchestrator import (
    freeze_contract, identify_leaf_nodes, create_assignments,
    get_neighbor_interfaces,
)
from app.schemas import Contract, ContractStatus, NodeStatus

def test_freeze_contract_sets_status(sample_valid_contract):
    """Test that freeze sets status to verified and computes hash."""
    # Setup: create session with drafting contract
    # ...
    
def test_freeze_contract_prevents_refreezing(sample_frozen_contract):
    """Test that already frozen contracts can't be re-frozen."""
    # ...

def test_identify_leaf_nodes(sample_valid_contract):
    """Test leaf node identification (no outgoing data/control edges)."""
    # ...

def test_create_assignments_for_leaf_nodes(sample_frozen_contract):
    """Test that assignments are created for all leaf nodes."""
    # ...

def test_frozen_contract_rejects_structural_changes(sample_frozen_contract):
    """Test that frozen contracts reject node/edge modifications."""
    # ...
```

### 5.2 Create `tests/test_agents.py`

```python
import pytest
from app import agents
from app.schemas import AgentType, AgentStatus

def test_register_agent():
    """Test agent registration returns valid agent_id."""
    agent = agents.register_agent("TestAgent", AgentType.CUSTOM)
    assert agent.id
    assert agent.name == "TestAgent"
    assert agent.status == AgentStatus.IDLE

def test_list_agents_shows_all():
    """Test listing shows all registered agents."""
    # ...

def test_heartbeat_updates_last_seen():
    """Test heartbeat updates last_seen_at."""
    # ...

def test_agent_status_transitions():
    """Test agent status changes correctly."""
    # ...
```

### 5.3 Create `tests/test_assignments.py`

```python
import pytest
from app import assignments
from app.schemas import AssignmentStatus

def test_create_assignment():
    """Test assignment creation with correct payload."""
    # ...

def test_claim_assignment_sets_status():
    """Test claiming sets assigned_to and broadcasts."""
    # ...

def test_double_claim_fails():
    """Test that double-claiming returns error."""
    # ...

def test_release_makes_available():
    """Test releasing makes node available again."""
    # ...

def test_get_available_excludes_claimed():
    """Test get_available_assignments excludes claimed nodes."""
    # ...
```

### 5.4 Create `tests/test_ws.py`

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_websocket_connection():
    """Test WebSocket connection lifecycle."""
    # ...

def test_broadcast_sends_to_all():
    """Test broadcast sends to all connected clients."""
    # ...

def test_message_format():
    """Test message format matches schema."""
    # ...
```

### 5.5 Update `tests/test_api.py`

Add tests for new endpoints:

```python
def test_freeze_changes_status(client, session_with_verified_contract):
    """Test POST /freeze changes status and returns hash."""
    # ...

def test_freeze_already_frozen_returns_error(client, frozen_session):
    """Test POST /freeze on frozen contract returns error."""
    # ...

def test_implement_creates_assignments(client, frozen_session):
    """Test POST /implement creates assignments."""
    # ...

def test_implement_external_mode(client, frozen_session):
    """Test POST /implement with mode=external creates assignments."""
    # ...

def test_get_generated_before_implementation(client, frozen_session):
    """Test GET /generated before implementation returns 404."""
    # ...

def test_register_agent(client):
    """Test POST /agents returns agent_id."""
    # ...

def test_claim_node(client, frozen_session_with_assignments):
    """Test POST /nodes/{id}/claim."""
    # ...
```

---

## Part 6: External Agent Example

### 6.1 Create `scripts/external_agent_example.py`

```python
#!/usr/bin/env python3
"""Example external agent that implements nodes via the Glasshouse API.

Usage:
    python scripts/external_agent_example.py --session-id <session_id>

This demonstrates how Devin, Cursor, or other agents can coordinate
with Glasshouse during Phase 2 implementation.
"""

import argparse
import time
import requests
from pathlib import Path

API_BASE = "http://localhost:8000/api/v1"


def main():
    parser = argparse.ArgumentParser(description="External agent example")
    parser.add_argument("--session-id", required=True, help="Session ID to work on")
    parser.add_argument("--name", default="ExampleAgent", help="Agent name")
    args = parser.parse_args()
    
    session_id = args.session_id
    
    # 1. Register agent
    print(f"[Agent] Registering as '{args.name}'...")
    resp = requests.post(f"{API_BASE}/agents", json={
        "name": args.name,
        "type": "custom",
    })
    resp.raise_for_status()
    agent_id = resp.json()["agent_id"]
    print(f"[Agent] Registered with ID: {agent_id}")
    
    # 2. Poll for assignments
    while True:
        print("[Agent] Polling for assignment...")
        resp = requests.get(
            f"{API_BASE}/sessions/{session_id}/assignments",
            params={"agent_id": agent_id},
        )
        resp.raise_for_status()
        
        assignment = resp.json().get("assignment")
        if not assignment:
            print("[Agent] No assignment available, waiting...")
            time.sleep(2)
            continue
        
        node = assignment["payload"]["node"]
        print(f"[Agent] Got assignment for node: {node['name']}")
        
        # 3. Claim the node
        resp = requests.post(
            f"{API_BASE}/sessions/{session_id}/nodes/{node['id']}/claim",
            json={"agent_id": agent_id},
        )
        if not resp.json().get("success"):
            print("[Agent] Failed to claim, retrying...")
            continue
        
        print(f"[Agent] Claimed node: {node['name']}")
        
        # 4. Report progress
        for progress in [0.25, 0.5, 0.75]:
            requests.post(
                f"{API_BASE}/sessions/{session_id}/nodes/{node['id']}/status",
                json={
                    "agent_id": agent_id,
                    "progress": progress,
                    "message": f"Working... {int(progress * 100)}%",
                },
            )
            time.sleep(1)
        
        # 5. Generate implementation (mock)
        output_dir = Path(f"generated/{session_id}/{node['id']}")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        impl_file = output_dir / f"{node['id'].replace('-', '_')}.py"
        impl_file.write_text(f'''"""Implementation for {node['name']}."""

def main():
    """Generated by {args.name}."""
    pass

if __name__ == "__main__":
    main()
''')
        
        # 6. Submit implementation
        resp = requests.post(
            f"{API_BASE}/sessions/{session_id}/nodes/{node['id']}/implementation",
            json={
                "agent_id": agent_id,
                "file_paths": [str(impl_file)],
                "actual_interface": {
                    "exports": ["main"],
                    "imports": [],
                    "public_functions": [{"name": "main", "signature": "def main()"}],
                },
                "notes": f"Implemented by {args.name}",
            },
        )
        
        if resp.json().get("success"):
            print(f"[Agent] Successfully implemented: {node['name']}")
        else:
            print(f"[Agent] Failed to submit implementation")
        
        # Continue polling for more work
        time.sleep(1)


if __name__ == "__main__":
    main()
```

---

## Acceptance Criteria

1. `pytest tests/ -v` — all tests pass
2. Complete Phase 1 loop (contract verified with UVDC = 1.0)
3. Click Freeze → contract status changes to `verified`, Freeze button disables
4. Click Implement (internal mode) → nodes start transitioning via WebSocket
5. Within 60 seconds, all nodes reach `implemented`
6. Logs show subagent dispatch, completion, and integration pass
7. Click Download → zip file downloads
8. Unzip contains:
   - `contract.json` (final, with `implementation` blocks filled)
   - `<node_id>/` directories with `.py` files
9. File interfaces match declared `payload_schema` (manual inspection)

**External mode test:**
1. Click Implement (external mode) → nodes show as "waiting for agent"
2. Run `python scripts/external_agent_example.py --session-id <id>`
3. Watch nodes turn yellow (claimed) then green (implemented) in UI
4. Agent name appears on node cards

---

## Deliverables Checklist

**Backend:**
- [ ] `backend/app/orchestrator.py`
- [ ] `backend/app/agents.py`
- [ ] `backend/app/assignments.py`
- [ ] `backend/app/ws.py`
- [ ] `backend/app/prompts/subagent.md`
- [ ] `backend/app/prompts/integrator.md`
- [ ] Updated `backend/app/api.py` (freeze, implement, generated, agent endpoints)
- [ ] Updated `backend/app/schemas.py` (Agent, Assignment, WS models)
- [ ] Updated `backend/app/main.py` (WebSocket route)
- [ ] `backend/tests/test_orchestrator.py`
- [ ] `backend/tests/test_agents.py`
- [ ] `backend/tests/test_assignments.py`
- [ ] `backend/tests/test_ws.py`
- [ ] Updated `backend/tests/test_api.py`

**Frontend:**
- [ ] `frontend/src/state/websocket.ts`
- [ ] `frontend/src/components/AgentPanel.tsx`
- [ ] Updated `frontend/src/state/contract.ts`
- [ ] Updated `frontend/src/components/ControlBar.tsx`
- [ ] Updated `frontend/src/components/NodeCard.tsx`
- [ ] Updated `frontend/src/api/client.ts`

**Scripts:**
- [ ] `scripts/external_agent_example.py`

---

## Commit Strategy

Create commits as you complete major pieces:
1. `feat(m5): add agent and assignment models to schemas`
2. `feat(m5): add agents module for external agent registry`
3. `feat(m5): add assignments module for work coordination`
4. `feat(m5): add WebSocket module for live updates`
5. `feat(m5): add orchestrator with freeze and implementation logic`
6. `feat(m5): add Phase 2 API routes`
7. `feat(m5): add frontend WebSocket state and handlers`
8. `feat(m5): add AgentPanel component`
9. `feat(m5): update ControlBar with Freeze/Implement buttons`
10. `feat(m5): update NodeCard with status animation and agent display`
11. `test(m5): add orchestrator, agents, assignments, and ws tests`
12. `feat(m5): add external agent example script`
13. `feat(m5): complete Phase 2 orchestrator end-to-end`
