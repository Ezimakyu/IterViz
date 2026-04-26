"""LLM provider wrapper using ``instructor`` for structured outputs.

This module is intentionally thin. Architect / Compiler / Subagent code
should call into helpers here rather than instantiating SDK clients
directly so we can switch providers, mock for tests, and centralize
timing + token-count logging.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from .logger import get_logger

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "openai").lower()


def _model_name() -> str:
    if _provider() == "anthropic":
        return os.environ.get("LLM_MODEL", "claude-3-5-sonnet-latest")
    return os.environ.get("LLM_MODEL", "gpt-4o-mini")


def _client() -> Any:
    """Return an ``instructor``-patched chat client for the configured provider.

    The import happens lazily so unit tests that mock ``call_structured``
    never need real provider SDK credentials.
    """
    import instructor

    provider = _provider()
    if provider == "anthropic":
        from anthropic import Anthropic

        return instructor.from_anthropic(Anthropic())
    # default: OpenAI
    from openai import OpenAI

    return instructor.from_openai(OpenAI())


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a system prompt by name from ``app/prompts/<name>.md``."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Structured call entrypoint
# ---------------------------------------------------------------------------


def call_structured(
    *,
    response_model: Type[T],
    system: str,
    user: str,
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> T:
    """Call the configured LLM and parse the response into ``response_model``.

    Logs timing on every call. With ``DEBUG=1``, the system / user previews
    are logged too.
    """
    client = _client()
    model = model or _model_name()
    provider = _provider()

    log.debug(
        "llm.call.start",
        extra={
            "provider": provider,
            "model": model,
            "response_model": response_model.__name__,
            "system_preview": system[:240],
            "user_preview": user[:240],
        },
    )

    start = time.perf_counter()
    if provider == "anthropic":
        result = client.messages.create(
            model=model,
            response_model=response_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=temperature,
        )
    else:
        result = client.chat.completions.create(
            model=model,
            response_model=response_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
    duration_ms = int((time.perf_counter() - start) * 1000)

    log.info(
        "llm.call.complete",
        extra={
            "provider": provider,
            "model": model,
            "response_model": response_model.__name__,
            "duration_ms": duration_ms,
        },
    )
    return result
