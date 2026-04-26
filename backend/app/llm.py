"""Thin LLM wrapper for the Blind Compiler.

The wrapper uses `instructor` to enforce that the LLM response conforms to
`CompilerOutput`. Temperature is pinned to 0 (see SPEC.md §3 — Compiler
must be deterministic).

Provider selection (in priority order):
1. Explicit `provider=` argument.
2. `GLASSHOUSE_LLM_PROVIDER` env var (`openai` or `anthropic`).
3. `ANTHROPIC_API_KEY` present -> anthropic (M3 demo target).
4. `OPENAI_API_KEY` present    -> openai.

Models:
- anthropic default: `claude-opus-4-5` (M3 demo target).
- openai default: `gpt-4o`.
- Override via `GLASSHOUSE_COMPILER_MODEL`.
"""

from __future__ import annotations

import json
import os
import time
from getpass import getpass
from pathlib import Path
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from .logger import get_logger
from .schemas import CompilerOutput, Contract

T = TypeVar("T", bound=BaseModel)

log = get_logger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "compiler.md"

# M3 demo target: Anthropic Claude Opus 4.5 is the headline model.
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-opus-4-5"

DEFAULT_MODELS = {
    # M1 eval results on the 8-contract seed set:
    #   gpt-4o-mini           recall 72.73% / precision 61.54%  (FAILS targets)
    #   gpt-4o                recall 100%   / precision 91.67%  (meets targets)
    #   claude-opus-4-5       recall 100%   / precision 100%    (demo model)
    # Override via GLASSHOUSE_COMPILER_MODEL when tuning.
    "openai": "gpt-4o",
    "anthropic": DEFAULT_MODEL,
}


def ensure_api_key(provider: Optional[str] = None) -> str:
    """Ensure the chosen provider's API key is set, prompting the user if not.

    M3 ships with Anthropic / Claude Opus 4.5 as the default. If the
    relevant env var is missing AND we have an interactive TTY, prompt the
    user. Otherwise, raise so server-side callers fail fast.

    Returns the API key string. Side-effect: sets ``os.environ`` so
    subsequent SDK calls pick it up.
    """
    provider = (provider or DEFAULT_PROVIDER).lower()
    var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    url = (
        "https://console.anthropic.com/settings/keys"
        if provider == "anthropic"
        else "https://platform.openai.com/api-keys"
    )

    key = os.getenv(var)
    if key:
        return key

    # Non-interactive contexts (CI, FastAPI workers): fail loudly instead of
    # blocking on input(). Callers should catch and surface to the user.
    if not _is_interactive():
        raise RuntimeError(
            f"{var} not set and no interactive TTY available to prompt."
        )

    print("\n" + "=" * 60)
    print(f"{var} not found in environment.")
    print(f"Get your API key from: {url}")
    print("=" * 60 + "\n")

    key = getpass(f"Enter your {provider.title()} API key: ").strip()
    if not key:
        raise RuntimeError(f"No {var} provided.")

    save = input("Save to backend/.env file? (y/n): ").strip().lower()
    if save == "y":
        env_path = Path(__file__).resolve().parent.parent / ".env"
        with env_path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n{var}={key}\n")
        print(f"Saved to {env_path}")

    os.environ[var] = key
    return key


def _is_interactive() -> bool:
    """True iff stdin is attached to a TTY."""
    try:
        import sys

        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:  # pragma: no cover - defensive
        return False


def _load_compiler_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _resolve_provider(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    env_provider = os.getenv("GLASSHOUSE_LLM_PROVIDER")
    if env_provider:
        return env_provider.lower()
    # M3 default: prefer Anthropic / Claude Opus 4.5 if its key is present.
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    raise RuntimeError(
        "No LLM provider configured. Set GLASSHOUSE_LLM_PROVIDER and the "
        "matching API key (ANTHROPIC_API_KEY or OPENAI_API_KEY)."
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
        # Anthropic SDK requires max_tokens. Architect/Compiler payloads
        # routinely exceed 16k tokens once the contract has been refined
        # three times (decisions list, expanded assumptions, payload
        # schemas), so we set a generous ceiling and rely on instructor's
        # retry to recover any partial output.
        common_kwargs["max_tokens"] = 32768

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


def load_prompt(name: str) -> str:
    """Load a system prompt by name from ``app/prompts/<name>.md``."""
    path = Path(__file__).parent / "prompts" / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def call_structured(
    *,
    response_model: Type[T],
    system: str,
    user: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 32768,
    max_retries: int = 2,
) -> T:
    """Generic structured-output call.

    Used by agents (Architect, Subagents, Integrator) that need a
    Pydantic-validated response but don't share the Compiler's specific
    contract-in / output-out signature.
    """
    provider = _resolve_provider(provider)
    model = _resolve_model(provider, model)
    client = _build_client(provider)

    log.debug(
        "llm call started",
        extra={
            "provider": provider,
            "model": model,
            "response_model": response_model.__name__,
            "system_preview": system[:240],
            "user_preview": user[:240],
        },
    )
    start = time.perf_counter()

    common_kwargs: dict[str, Any] = {
        "model": model,
        "response_model": response_model,
        "temperature": temperature,
        "max_retries": max_retries,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if provider == "anthropic":
        common_kwargs["max_tokens"] = max_tokens

    result: T = client.chat.completions.create(**common_kwargs)
    duration_ms = int((time.perf_counter() - start) * 1000)

    log.info(
        "llm call completed",
        extra={
            "provider": provider,
            "model": model,
            "response_model": response_model.__name__,
            "duration_ms": duration_ms,
        },
    )
    return result


__all__ = [
    "call_compiler",
    "call_structured",
    "load_prompt",
    "ensure_api_key",
    "DEFAULT_PROVIDER",
    "DEFAULT_MODEL",
]
