"""FastAPI route handlers for Glasshouse v1.

Routes are intentionally thin: validate, delegate to the service layer
(``architect`` / ``compiler`` / ``contract``), serialize the response.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from . import architect as architect_svc
from . import compiler as compiler_svc
from . import contract as contract_svc
from .logger import get_logger
from .schemas import (
    AnswersRequest,
    CompilerResponse,
    Contract,
    ContractResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    GetSessionResponse,
    RefineRequest,
    RefineResponse,
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
