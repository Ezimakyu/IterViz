"""FastAPI app factory + middleware for Glasshouse backend."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import contract as contract_svc
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

    app.include_router(api_router)
    return app


app = create_app()
