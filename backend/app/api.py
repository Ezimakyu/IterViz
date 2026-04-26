"""FastAPI route handlers for Glasshouse v1.

Routes are intentionally thin: validate, delegate to the service layer
(``architect`` / ``contract``), serialize the response.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from . import architect as architect_svc
from . import contract as contract_svc
from .logger import get_logger
from .schemas import (
    Contract,
    CreateSessionRequest,
    CreateSessionResponse,
    GetSessionResponse,
    RefineRequest,
    RefineResponse,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["sessions"])


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


@router.post(
    "/sessions/{session_id}/architect/refine",
    response_model=RefineResponse,
)
def refine_session(
    session_id: str, request: RefineRequest
) -> RefineResponse:
    """Apply user answers to an existing contract via the Architect."""
    try:
        session = contract_svc.get_session(session_id)
    except contract_svc.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    updated: Contract = architect_svc.refine_contract(
        session.contract, request.answers
    )
    persisted = contract_svc.update_contract(session_id, updated)
    diff = {
        "previous_version": session.contract.meta.version,
        "new_version": persisted.contract.meta.version,
        "n_decisions": len(persisted.contract.decisions),
    }
    return RefineResponse(contract=persisted.contract, diff=diff)
