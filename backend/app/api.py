"""FastAPI route handlers for Glasshouse v1.

Routes are intentionally thin: validate, delegate to the service layer
(``architect`` / ``compiler`` / ``contract`` / ``orchestrator``),
serialize the response.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from . import agents as agents_svc
from . import architect as architect_svc
from . import assignments as assignments_svc
from . import compiler as compiler_svc
from . import contract as contract_svc
from . import orchestrator as orchestrator_svc
from . import subgraph as subgraph_svc
from . import subgraphs as subgraphs_store
from . import ws as ws_svc
from .logger import get_logger
from .schemas import (
    AnswersRequest,
    ClaimNodeRequest,
    ClaimNodeResponse,
    CompilerResponse,
    Contract,
    ContractResponse,
    ContractStatus,
    CreateSessionRequest,
    CreateSessionResponse,
    FreezeResponse,
    GenerateSubgraphResponse,
    GetAssignmentResponse,
    GetSessionResponse,
    GetSubgraphResponse,
    Implementation,
    ImplementMode,
    ImplementRequest,
    ImplementResponse,
    ImplementationSubgraph,
    ListAgentsResponse,
    NodeStatus,
    NodeStatusRequest,
    NodeStatusResponse,
    NodeUpdateRequest,
    NodeUpdateResponse,
    RefineRequest,
    RefineResponse,
    RegisterAgentRequest,
    RegisterAgentResponse,
    ReleaseNodeRequest,
    ReleaseNodeResponse,
    SubmitImplementationRequest,
    SubmitImplementationResponse,
    UpdateSubgraphNodeRequest,
    UpdateSubgraphNodeResponse,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["sessions"])


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@router.post(
    "/sessions",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session(request: CreateSessionRequest) -> CreateSessionResponse:
    """Create a session, run the Architect, persist the contract."""
    log.info("api.create_session", extra={"prompt_len": len(request.prompt)})
    try:
        contract = architect_svc.generate_contract(request.prompt)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    session = contract_svc.create_session(contract)
    return CreateSessionResponse(
        session_id=session.id, contract=session.contract
    )


@router.get("/sessions/{session_id}", response_model=GetSessionResponse)
def get_session(session_id: str) -> GetSessionResponse:
    """Return the current contract for a session."""
    try:
        session = contract_svc.get_session(session_id)
    except contract_svc.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return GetSessionResponse(contract=session.contract)


# ---------------------------------------------------------------------------
# M3: Compiler / Answers / Refine
# ---------------------------------------------------------------------------

@router.post(
    "/sessions/{session_id}/compiler/verify",
    response_model=CompilerResponse,
)
def verify_session(session_id: str) -> CompilerResponse:
    """Run the Blind Compiler on the current contract and persist the run."""
    log.info("api.verify_called", extra={"session_id": session_id})
    try:
        session = contract_svc.get_session(session_id)
    except contract_svc.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    try:
        output = compiler_svc.verify_contract(session.contract)
    except RuntimeError as exc:
        # Eg. no LLM key configured AND use_llm=True; surface as 503 so
        # the frontend can fall back to a no-LLM mode if needed.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Compiler unavailable: {exc}",
        ) from exc

    contract_svc.add_verification_run(session_id, output)
    return CompilerResponse(
        verdict=output.verdict,
        violations=output.violations,
        questions=output.questions,
        intent_guess=output.intent_guess,
        uvdc_score=output.uvdc_score,
        confidence_updates=output.confidence_updates,
    )


@router.post(
    "/sessions/{session_id}/answers",
    response_model=ContractResponse,
)
def submit_answers(
    session_id: str, request: AnswersRequest
) -> ContractResponse:
    """Append user answers to ``contract.decisions[]``."""
    log.info(
        "api.answers_submitted",
        extra={"session_id": session_id, "count": len(request.decisions)},
    )
    try:
        contract_svc.get_session(session_id)
    except contract_svc.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    last_session = None
    for decision in request.decisions:
        last_session = contract_svc.add_decision(session_id, decision)
    if last_session is None:
        last_session = contract_svc.get_session(session_id)
    return ContractResponse(contract=last_session.contract)


# ---------------------------------------------------------------------------
# M4: Node update — direct user edits to graph fields
# ---------------------------------------------------------------------------

@router.patch(
    "/sessions/{session_id}/nodes/{node_id}",
    response_model=NodeUpdateResponse,
)
def update_node_endpoint(
    session_id: str, node_id: str, body: NodeUpdateRequest
) -> NodeUpdateResponse:
    """Update node fields and set their provenance to ``user``.

    Editable fields: ``description``, ``responsibilities``, ``assumptions``.
    Structural fields (``id``, ``name``, ``kind``) are intentionally not
    accepted — the Pydantic ``extra="forbid"`` config rejects them with a
    422.
    """
    log.info(
        "api.update_node_called",
        extra={"session_id": session_id, "node_id": node_id},
    )
    try:
        node, fields_updated, provenance_changes = contract_svc.update_node(
            session_id, node_id, body
        )
    except contract_svc.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    log.info(
        "api.node_updated",
        extra={
            "session_id": session_id,
            "node_id": node_id,
            "fields_updated": fields_updated,
            "provenance_changes": provenance_changes,
        },
    )
    return NodeUpdateResponse(
        node=node,
        fields_updated=fields_updated,
        provenance_set=provenance_changes,
    )


@router.post(
    "/sessions/{session_id}/architect/refine",
    response_model=RefineResponse,
)
def refine_session(
    session_id: str, request: RefineRequest
) -> RefineResponse:
    """Apply user answers to an existing contract via the Architect.

    If the request body is empty, fall back to *unanswered-but-recorded*
    decisions on the contract. This lets the frontend run the canonical
    M3 loop ``answers -> refine`` cleanly.
    """
    log.info(
        "api.refine_called",
        extra={"session_id": session_id, "n_answers": len(request.answers)},
    )
    try:
        session = contract_svc.get_session(session_id)
    except contract_svc.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    answers = list(request.answers) if request.answers else list(
        session.contract.decisions
    )

    updated: Contract = architect_svc.refine_contract(session.contract, answers)
    persisted = contract_svc.update_contract(session_id, updated)
    diff = {
        "previous_version": session.contract.meta.version,
        "new_version": persisted.contract.meta.version,
        "n_decisions": len(persisted.contract.decisions),
        "n_nodes_before": len(session.contract.nodes),
        "n_nodes_after": len(persisted.contract.nodes),
        "n_edges_before": len(session.contract.edges),
        "n_edges_after": len(persisted.contract.edges),
    }
    return RefineResponse(contract=persisted.contract, diff=diff)


# ---------------------------------------------------------------------------
# M6: Implementation subgraphs
# ---------------------------------------------------------------------------


def _find_node_or_404(
    session: contract_svc.Session, node_id: str
):
    node = next((n for n in session.contract.nodes if n.id == node_id), None)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"node {node_id} not found in session {session.id}",
        )
    return node


@router.post(
    "/sessions/{session_id}/nodes/{node_id}/subgraph",
    response_model=GenerateSubgraphResponse,
)
async def generate_node_subgraph(
    session_id: str, node_id: str
) -> GenerateSubgraphResponse:
    """Generate (or regenerate) the implementation subgraph for a node.

    M6: bypasses the verification loop -- the parent node is assumed to
    already have UVDC = 1.0. The generated subgraph is stored in memory
    and broadcast to all session subscribers.
    """

    log.info(
        "api.subgraph_generate",
        extra={"session_id": session_id, "node_id": node_id},
    )
    try:
        session = contract_svc.get_session(session_id)
    except contract_svc.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    node = _find_node_or_404(session, node_id)
    neighbor_interfaces = subgraph_svc.get_neighbor_interfaces(
        node, session.contract
    )

    # ``generate_subgraph`` may issue a blocking LLM HTTP request that
    # takes several seconds; running it in a worker thread keeps the
    # FastAPI event loop free for other requests / WebSocket frames.
    try:
        subgraph = await asyncio.to_thread(
            subgraph_svc.generate_subgraph,
            node,
            session.contract,
            neighbor_interfaces,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Subgraph generator unavailable: {exc}",
        ) from exc

    subgraphs_store.store_subgraph(subgraph)
    await ws_svc.broadcast_subgraph_created(session_id, node_id, subgraph)

    return GenerateSubgraphResponse(subgraph=subgraph)


@router.get(
    "/sessions/{session_id}/nodes/{node_id}/subgraph",
    response_model=GetSubgraphResponse,
)
def get_node_subgraph(session_id: str, node_id: str) -> GetSubgraphResponse:
    """Return the cached subgraph for a node, or ``null`` if none."""

    return GetSubgraphResponse(
        subgraph=subgraphs_store.get_subgraph(session_id, node_id)
    )


@router.get(
    "/sessions/{session_id}/subgraphs",
    response_model=list[ImplementationSubgraph],
)
def get_all_session_subgraphs(
    session_id: str,
) -> list[ImplementationSubgraph]:
    """Return every cached subgraph for a session."""

    return subgraphs_store.get_all_subgraphs(session_id)


@router.patch(
    "/sessions/{session_id}/nodes/{node_id}/subgraph/nodes/{subgraph_node_id}",
    response_model=UpdateSubgraphNodeResponse,
)
async def update_subgraph_node(
    session_id: str,
    node_id: str,
    subgraph_node_id: str,
    body: UpdateSubgraphNodeRequest,
) -> UpdateSubgraphNodeResponse:
    """Update a subgraph node's status and broadcast the change.

    Returns ``success=False`` (200) when the subgraph itself does not
    exist yet -- callers should call POST /subgraph first.
    Returns 404 when the parent node id is unknown to the subgraph.
    """

    subgraph = subgraphs_store.get_subgraph(session_id, node_id)
    if subgraph is None:
        return UpdateSubgraphNodeResponse(success=False, subgraph=None)

    try:
        updated = subgraph_svc.update_subgraph_node_status(
            subgraph,
            subgraph_node_id,
            body.status,
            body.error_message,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    subgraphs_store.update_subgraph(updated)
    await ws_svc.broadcast_subgraph_node_status_changed(
        session_id,
        node_id,
        subgraph_node_id,
        body.status,
        updated.progress,
    )

    return UpdateSubgraphNodeResponse(success=True, subgraph=updated)


# ---------------------------------------------------------------------------
# M6: Session WebSocket stream
# ---------------------------------------------------------------------------


@router.websocket("/sessions/{session_id}/stream")
async def session_stream(websocket: WebSocket, session_id: str) -> None:
    """Bidirectional stream for live session events.

    The server only broadcasts; client-sent frames are read and
    discarded so the connection lifecycle stays under the client's
    control. M5 will extend the broadcast set with node-status events.
    """

    await ws_svc.manager.connect(session_id, websocket)
    try:
        while True:
            # We don't expect commands today, but receiving keeps the
            # connection alive and lets us notice client disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_svc.manager.disconnect(session_id, websocket)


# ---------------------------------------------------------------------------
# M5: Phase 2 orchestration routes
# ---------------------------------------------------------------------------


@router.post(
    "/agents",
    response_model=RegisterAgentResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_agent(request: RegisterAgentRequest) -> RegisterAgentResponse:
    """Register an external agent (Devin, Cursor, Claude Code, etc.)."""
    agent = agents_svc.register_agent(request.name, request.type)
    return RegisterAgentResponse(agent_id=agent.id, agent=agent)


@router.get("/agents", response_model=ListAgentsResponse)
def list_agents() -> ListAgentsResponse:
    """List every registered agent (status auto-updates if stale)."""
    return ListAgentsResponse(agents=agents_svc.list_agents())


@router.get(
    "/sessions/{session_id}/assignments",
    response_model=GetAssignmentResponse,
)
def get_assignment(
    session_id: str, agent_id: str
) -> GetAssignmentResponse:
    """Poll for an available (pending) assignment for the given agent."""
    agents_svc.heartbeat(agent_id)

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
    try:
        session = contract_svc.get_session(session_id)
    except contract_svc.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    # Verify the node exists in the contract BEFORE mutating any
    # assignment/agent state, so an unknown node id can't leave an
    # assignment stuck IN_PROGRESS or an agent marked as busy.
    contract = session.contract
    target_node = next((n for n in contract.nodes if n.id == node_id), None)
    if target_node is None:
        return ClaimNodeResponse(success=False, error="Node not found")

    assignment = assignments_svc.claim_assignment(
        session_id, node_id, request.agent_id
    )
    if assignment is None:
        return ClaimNodeResponse(
            success=False,
            error="Node not available or already claimed",
        )

    agent = agents_svc.set_agent_assignment(request.agent_id, assignment.id)
    agent_name = agent.name if agent is not None else "Unknown"

    target_node.status = NodeStatus.IN_PROGRESS
    persisted = contract_svc.update_contract(session_id, contract)

    await ws_svc.broadcast_node_claimed(
        session_id, node_id, request.agent_id, agent_name
    )
    await ws_svc.broadcast_node_status_changed(
        session_id,
        node_id,
        NodeStatus.IN_PROGRESS,
        agent_id=request.agent_id,
        agent_name=agent_name,
    )

    updated_node = next(
        (n for n in persisted.contract.nodes if n.id == node_id),
        target_node,
    )
    return ClaimNodeResponse(
        success=True,
        node=updated_node,
        assignment=assignment,
    )


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
        await ws_svc.broadcast_node_progress(
            session_id,
            node_id,
            request.agent_id,
            request.progress,
            request.message,
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
    """Submit an implementation for a claimed node."""
    try:
        session = contract_svc.get_session(session_id)
    except contract_svc.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    # Verify the node exists BEFORE completing the assignment, so an
    # unknown node id can't silently mark the assignment COMPLETED
    # without ever updating the contract.
    contract = session.contract
    target_node = next((n for n in contract.nodes if n.id == node_id), None)
    if target_node is None:
        return SubmitImplementationResponse(success=False, node=None)

    assignment = assignments_svc.complete_assignment(
        session_id=session_id,
        node_id=node_id,
        agent_id=request.agent_id,
        file_paths=request.file_paths,
        actual_interface=request.actual_interface,
        notes=request.notes,
    )
    if assignment is None:
        return SubmitImplementationResponse(success=False, node=None)

    agents_svc.set_agent_assignment(request.agent_id, None)

    target_node.status = NodeStatus.IMPLEMENTED
    target_node.implementation = Implementation(
        file_paths=request.file_paths,
        notes=request.notes,
        actual_interface=request.actual_interface,
        completed_at=datetime.utcnow(),
    )
    persisted = contract_svc.update_contract(session_id, contract)

    await ws_svc.broadcast_node_status_changed(
        session_id,
        node_id,
        NodeStatus.IMPLEMENTED,
    )

    updated_node = next(
        (n for n in persisted.contract.nodes if n.id == node_id),
        target_node,
    )
    return SubmitImplementationResponse(success=True, node=updated_node)


@router.post(
    "/sessions/{session_id}/nodes/{node_id}/release",
    response_model=ReleaseNodeResponse,
)
async def release_node(
    session_id: str,
    node_id: str,
    request: ReleaseNodeRequest,
) -> ReleaseNodeResponse:
    """Release a claimed node so it can be picked up by another agent."""
    try:
        session = contract_svc.get_session(session_id)
    except contract_svc.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    assignment = assignments_svc.release_assignment(
        session_id, node_id, request.agent_id
    )
    if assignment is None:
        return ReleaseNodeResponse(success=False)

    agents_svc.set_agent_assignment(request.agent_id, None)

    target_node = next(
        (n for n in session.contract.nodes if n.id == node_id), None
    )
    if target_node is not None:
        target_node.status = NodeStatus.DRAFTED
        contract_svc.update_contract(session_id, session.contract)
        await ws_svc.broadcast_node_status_changed(
            session_id, node_id, NodeStatus.DRAFTED
        )

    return ReleaseNodeResponse(success=True)


@router.post(
    "/sessions/{session_id}/freeze",
    response_model=FreezeResponse,
)
def freeze_session(session_id: str) -> FreezeResponse:
    """Freeze the contract so the implementation phase can begin."""
    try:
        contract = orchestrator_svc.freeze_contract(session_id)
    except contract_svc.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return FreezeResponse(
        contract=contract,
        frozen_hash=contract.meta.frozen_hash or "",
    )


@router.post(
    "/sessions/{session_id}/implement",
    response_model=ImplementResponse,
)
async def implement_session(
    session_id: str,
    request: ImplementRequest,
    background_tasks: BackgroundTasks,
) -> ImplementResponse:
    """Start Phase 2 implementation in either internal or external mode."""
    try:
        session = contract_svc.get_session(session_id)
    except contract_svc.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    current_status = (
        session.contract.meta.status
        if isinstance(session.contract.meta.status, str)
        else session.contract.meta.status.value
    )
    if current_status != ContractStatus.VERIFIED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contract must be frozen before implementation",
        )

    assignments = orchestrator_svc.create_assignments(session_id)
    job_id = str(uuid.uuid4())

    mode = request.mode
    if isinstance(mode, ImplementMode):
        mode_value = mode
    else:
        mode_value = ImplementMode(mode)

    if mode_value == ImplementMode.INTERNAL:
        background_tasks.add_task(
            orchestrator_svc.run_implementation_internal, session_id
        )

    return ImplementResponse(
        job_id=job_id,
        mode=mode_value,
        assignments_created=len(assignments),
    )


@router.get("/sessions/{session_id}/generated")
def download_generated(session_id: str) -> FileResponse:
    """Download generated files (and final contract) as a zip archive."""
    try:
        output_dir = orchestrator_svc.get_generated_files_dir(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = Path(tmp.name)
    tmp.close()
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in output_dir.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(output_dir))

    # Schedule the temp zip for deletion AFTER the response is sent so
    # we don't leak files in the OS temp directory on every download.
    return FileResponse(
        str(tmp_path),
        media_type="application/zip",
        filename=f"generated_{session_id}.zip",
        background=BackgroundTask(tmp_path.unlink, missing_ok=True),
    )
