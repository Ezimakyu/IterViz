"""Architect agent.

The Architect is the only agent that sees the user's natural-language
prompt. It translates that prompt (plus any captured user decisions)
into a full ``Contract`` instance.

Both ``generate_contract`` and ``refine_contract`` go through
:func:`app.llm.call_structured`, which uses ``instructor`` to enforce
the ``Contract`` Pydantic schema on the LLM output.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Iterable

from .llm import call_structured, load_prompt
from .logger import get_logger
from .schemas import Contract, Decision, PromptHistoryEntry

log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def _system_prompt() -> str:
    return load_prompt("architect")


def generate_contract(prompt: str) -> Contract:
    """Convert a free-text prompt into a fresh ``Contract``."""
    if not prompt or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")

    log.info("architect.generate.start", extra={"prompt_len": len(prompt)})

    user_message = (
        "User prompt:\n"
        f"\"\"\"\n{prompt}\n\"\"\"\n\n"
        "Produce the full Contract JSON now. Required minimums: "
        "at least 3 nodes and at least 2 edges."
    )

    contract = call_structured(
        response_model=Contract,
        system=_system_prompt(),
        user=user_message,
    )

    # Always reflect the original prompt in meta.prompt_history so the
    # downstream pipeline can audit what the user actually said.
    if not contract.meta.id:
        contract.meta.id = _new_id()
    contract.meta.prompt_history = [
        PromptHistoryEntry(role="user", content=prompt, timestamp=_now())
    ] + [e for e in contract.meta.prompt_history if e.content != prompt]
    contract.meta.created_at = contract.meta.created_at or _now()
    contract.meta.updated_at = _now()
    contract.meta.version = 1

    log.info(
        "architect.generate.complete",
        extra={
            "contract_id": contract.meta.id,
            "n_nodes": len(contract.nodes),
            "n_edges": len(contract.edges),
        },
    )
    return contract


def refine_contract(
    contract: Contract, answers: Iterable[Decision]
) -> Contract:
    """Apply user answers to an existing contract.

    The LLM is responsible for editing affected nodes/edges in place
    (preserving ids) and for marking resolved fields ``decided_by:
    "user"``. We additionally guarantee that:

    * every supplied answer is appended to ``decisions[]``,
    * ``meta.version`` is bumped,
    * ``meta.updated_at`` is refreshed.
    """
    answers_list = list(answers)
    log.info(
        "architect.refine.start",
        extra={
            "contract_id": contract.meta.id,
            "n_answers": len(answers_list),
            "prev_version": contract.meta.version,
        },
    )

    contract_json = contract.model_dump(mode="json")
    answers_json = [a.model_dump(mode="json") for a in answers_list]

    user_message = (
        "Refine the previous contract using the supplied user answers.\n"
        "Preserve every node and edge id; update fields in place; mark\n"
        "resolved fields decided_by=\"user\" and bump their confidence.\n\n"
        f"Previous contract JSON:\n{json.dumps(contract_json)}\n\n"
        f"User answers JSON:\n{json.dumps(answers_json)}\n\n"
        "Return the full updated Contract JSON."
    )

    updated = call_structured(
        response_model=Contract,
        system=_system_prompt(),
        user=user_message,
    )

    # Make absolutely sure the answers we were given end up in
    # decisions[] even if the LLM forgets to copy them.
    existing_ids = {d.id for d in updated.decisions}
    for answer in answers_list:
        if answer.id not in existing_ids:
            updated.decisions.append(answer)

    updated.meta.id = contract.meta.id
    updated.meta.version = contract.meta.version + 1
    updated.meta.created_at = contract.meta.created_at
    updated.meta.updated_at = _now()

    log.info(
        "architect.refine.complete",
        extra={
            "contract_id": updated.meta.id,
            "version": updated.meta.version,
            "n_decisions": len(updated.decisions),
        },
    )
    return updated
