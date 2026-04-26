"""FastAPI route handlers for Glasshouse v1.

Routes are intentionally thin: validate, delegate to the service layer
(``architect`` / ``compiler`` / ``contract``), serialize the response.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from . import architect as architect_svc
from . import compiler as compiler_svc
from . import contract as contract_svc
from . import subgraph as subgraph_svc
from . import subgraphs as subgraphs_store
from . import ws as ws_svc
from .logger import get_logger
from .schemas import (
    AnswersRequest,
    CompilerResponse,
    Contract,
    ContractResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    GenerateSubgraphResponse,
    GetSessionResponse,
    GetSubgraphResponse,
    ImplementationSubgraph,
    NodeUpdateRequest,
    NodeUpdateResponse,
    RefineRequest,
    RefineResponse,
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

    try:
        subgraph = subgraph_svc.generate_subgraph(
            node, session.contract, neighbor_interfaces
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
