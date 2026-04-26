"""FastAPI route handlers for Glasshouse v1.

Routes are intentionally thin: validate, delegate to the service layer
(``architect`` / ``compiler`` / ``contract`` / ``orchestrator``),
serialize the response.
"""

from __future__ import annotations

import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import FileResponse

from . import agents as agents_svc
from . import architect as architect_svc
from . import assignments as assignments_svc
from . import compiler as compiler_svc
from . import contract as contract_svc
from . import orchestrator as orchestrator_svc
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
    GetAssignmentResponse,
    GetSessionResponse,
    Implementation,
    ImplementMode,
    ImplementRequest,
    ImplementResponse,
    ListAgentsResponse,
    NodeStatus,
    NodeStatusRequest,
    NodeStatusResponse,
    RefineRequest,
    RefineResponse,
    RegisterAgentRequest,
    RegisterAgentResponse,
    ReleaseNodeRequest,
    ReleaseNodeResponse,
    SubmitImplementationRequest,
    SubmitImplementationResponse,
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

    contract = session.contract
    target_node = next((n for n in contract.nodes if n.id == node_id), None)
    if target_node is None:
        return ClaimNodeResponse(success=False, error="Node not found")

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

    contract = session.contract
    target_node = next((n for n in contract.nodes if n.id == node_id), None)
    if target_node is None:
        return SubmitImplementationResponse(success=False, node=None)

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

    return FileResponse(
        str(tmp_path),
        media_type="application/zip",
        filename=f"generated_{session_id}.zip",
    )
