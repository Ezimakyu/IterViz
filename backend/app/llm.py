"""Thin LLM wrapper for the Blind Compiler.

The wrapper uses `instructor` to enforce that the LLM response conforms to
`CompilerOutput`. Temperature is pinned to 0 (see SPEC.md §3 — Compiler
must be deterministic).

Provider selection (in priority order):
1. Explicit `provider=` argument.
2. `GLASSHOUSE_LLM_PROVIDER` env var (`openai` or `anthropic`).
3. `OPENAI_API_KEY` present  -> openai.
4. `ANTHROPIC_API_KEY` present -> anthropic.

Models:
- openai default: `gpt-4o-mini` (fast, cheap, good at structured output).
- anthropic default: `claude-3-5-sonnet-latest`.
- Override via `GLASSHOUSE_COMPILER_MODEL`.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from .logger import get_logger
from .schemas import CompilerOutput, Contract

log = get_logger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "compiler.md"

DEFAULT_MODELS = {
    # gpt-4o-mini hallucinates edge connectivity on the M1 seeds (precision
    # ~56-62%); gpt-4o reaches the SPEC targets of recall >= 80% / precision
    # >= 90%. Override via GLASSHOUSE_COMPILER_MODEL when tuning.
    "openai": "gpt-4o",
    "anthropic": "claude-3-5-sonnet-latest",
}


def _load_compiler_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _resolve_provider(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    env_provider = os.getenv("GLASSHOUSE_LLM_PROVIDER")
    if env_provider:
        return env_provider.lower()
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    raise RuntimeError(
        "No LLM provider configured. Set GLASSHOUSE_LLM_PROVIDER and the "
        "matching API key (OPENAI_API_KEY or ANTHROPIC_API_KEY)."
    )


def _resolve_model(provider: str, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    env_model = os.getenv("GLASSHOUSE_COMPILER_MODEL")
    if env_model:
        return env_model
    return DEFAULT_MODELS[provider]


def _build_client(provider: str) -> Any:
    """Return an `instructor`-patched chat client for the chosen provider."""
    import instructor  # local import keeps schemas importable without LLM deps

    if provider == "openai":
        from openai import OpenAI

        return instructor.from_openai(OpenAI())
    if provider == "anthropic":
        from anthropic import Anthropic

        return instructor.from_anthropic(Anthropic())
    raise ValueError(f"Unknown provider: {provider!r}")


def call_compiler(
    contract: Contract,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_retries: int = 2,
) -> CompilerOutput:
    """Run the Blind Compiler over a contract and return its findings.

    Args:
        contract: parsed contract.
        provider: 'openai' or 'anthropic'. Auto-detects when omitted.
        model: model name override.
        max_retries: passed through to instructor's structured-output retry.

    Returns:
        A validated `CompilerOutput`.
    """
    provider = _resolve_provider(provider)
    model = _resolve_model(provider, model)
    client = _build_client(provider)

    system_prompt = _load_compiler_prompt()
    contract_json = contract.model_dump_json(indent=2, exclude_none=True)
    user_msg = (
        "Verify the following architecture_contract. Return a CompilerOutput "
        "object only.\n\n"
        f"```json\n{contract_json}\n```"
    )

    log.debug(
        "compiler call started",
        extra={
            "agent_type": "compiler",
            "provider": provider,
            "model": model,
            "contract_id": contract.meta.id,
            "node_count": len(contract.nodes),
            "edge_count": len(contract.edges),
        },
    )
    start = time.perf_counter()

    common_kwargs: dict[str, Any] = {
        "model": model,
        "response_model": CompilerOutput,
        "temperature": 0,
        "max_retries": max_retries,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
    }
    if provider == "anthropic":
        # Anthropic SDK requires max_tokens.
        common_kwargs["max_tokens"] = 4096

    result: CompilerOutput = client.chat.completions.create(**common_kwargs)
    duration_ms = int((time.perf_counter() - start) * 1000)

    log.info(
        "compiler call completed",
        extra={
            "agent_type": "compiler",
            "provider": provider,
            "model": model,
            "duration_ms": duration_ms,
            "verdict": result.verdict,
            "violation_count": len(result.violations),
            "question_count": len(result.questions),
        },
    )
    return result


__all__ = ["call_compiler"]
