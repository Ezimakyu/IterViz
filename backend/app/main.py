"""FastAPI app factory + middleware for Glasshouse backend."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import contract as contract_svc
from . import llm as llm_svc
from . import ws as ws_svc
from .api import router as api_router
from .logger import get_logger

log = get_logger(__name__)


DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    contract_svc.init_db()
    log.info("app.startup", extra={"db_path": str(contract_svc.get_db_path())})

    # M3: prompt for the Anthropic key if running in an interactive TTY,
    # otherwise just log a warning so deployment / test harnesses keep
    # working even when no key is configured.
    try:
        llm_svc.ensure_api_key(llm_svc.DEFAULT_PROVIDER)
    except RuntimeError as exc:
        log.warning("app.startup.no_llm_key", extra={"reason": str(exc)})

    try:
        yield
    finally:
        log.info("app.shutdown")


def create_app() -> FastAPI:
    """Build the FastAPI app. Always use this — never instantiate ``FastAPI``
    directly — so middleware + lifespan stay consistent across processes
    and tests.
    """
    app = FastAPI(
        title="Glasshouse Backend",
        version="0.1.0",
        description="Epistemic Architecture Verification — backend services.",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEFAULT_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _request_logger(request: Request, call_next):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)
        log.info(
            "http.request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    @app.get("/health", tags=["meta"])
    def _health() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/api/v1/sessions/{session_id}/stream")
    async def _ws_stream(websocket: WebSocket, session_id: str) -> None:
        """WebSocket endpoint for live Phase 2 updates."""
        await ws_svc.manager.connect(session_id, websocket)
        try:
            while True:
                # We currently don't act on client -> server messages,
                # but receive_text keeps the connection alive and lets
                # us drain any pings the client sends.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            # Always release the connection so an abnormal close
            # (RuntimeError, network error) doesn't leave a stale
            # reference in ConnectionManager._connections.
            await ws_svc.manager.disconnect(session_id, websocket)

    app.include_router(api_router)
    return app


app = create_app()
