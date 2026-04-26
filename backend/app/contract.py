"""Contract persistence: SQLite-backed CRUD plus schema validation.

A "session" wraps one Architect → Compiler → Implementer run. The
contract evolves inside the session and is written back to SQLite on
every update.

Schema:

    CREATE TABLE sessions (
        id           TEXT PRIMARY KEY,    -- session uuid (= contract.meta.id)
        created_at   TEXT NOT NULL,       -- ISO-8601
        updated_at   TEXT NOT NULL,
        status       TEXT NOT NULL,       -- contract status
        contract_json TEXT NOT NULL       -- full contract JSON
    );

Every write goes through :func:`validate_contract_payload` which both
parses the payload through Pydantic *and* enforces the JSON schema
generated from the Pydantic model. This catches malformed contracts
even when the caller hands us a raw dict.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Union

import jsonschema
from pydantic import ValidationError

from .logger import get_logger
from .schemas import (
    CompilerOutput,
    Contract,
    DecidedBy,
    Decision,
    Node,
    NodeUpdateRequest,
    Verdict,
    VerificationLogEntry,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ContractValidationError(ValueError):
    """Raised when a contract fails schema validation on write."""


class SessionNotFoundError(LookupError):
    """Raised when the requested session id does not exist."""


# ---------------------------------------------------------------------------
# Database lifecycle
# ---------------------------------------------------------------------------


_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "glasshouse.db"
_db_path_override: Optional[Path] = None
_lock = threading.Lock()


def get_db_path() -> Path:
    """Resolve the active sqlite db path.

    Resolution order:
    1. ``set_db_path()`` override (used by tests).
    2. ``GLASSHOUSE_DB`` environment variable.
    3. ``backend/glasshouse.db`` (default).
    """
    if _db_path_override is not None:
        return _db_path_override
    env = os.environ.get("GLASSHOUSE_DB")
    if env:
        return Path(env)
    return _DEFAULT_DB_PATH


def set_db_path(path: Optional[Union[str, Path]]) -> None:
    """Override the active db path (mostly for tests)."""
    global _db_path_override
    _db_path_override = Path(path) if path is not None else None


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create the ``sessions`` table if it does not already exist."""
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id            TEXT PRIMARY KEY,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL,
                status        TEXT NOT NULL,
                contract_json TEXT NOT NULL
            )
            """
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


_CONTRACT_JSON_SCHEMA: Optional[dict[str, Any]] = None


def _contract_json_schema() -> dict[str, Any]:
    global _CONTRACT_JSON_SCHEMA
    if _CONTRACT_JSON_SCHEMA is None:
        _CONTRACT_JSON_SCHEMA = Contract.model_json_schema()
    return _CONTRACT_JSON_SCHEMA


def validate_contract_payload(
    payload: Union[Contract, dict[str, Any], str]
) -> Contract:
    """Validate *anything* contract-shaped and return a ``Contract``.

    Accepts a Pydantic ``Contract``, a dict, or a JSON string. Runs both
    Pydantic validation and JSON-Schema validation so writes never end
    up with a structurally-broken contract on disk.
    """
    if isinstance(payload, Contract):
        contract = payload
        as_dict = contract.model_dump(mode="json")
    else:
        if isinstance(payload, str):
            try:
                as_dict = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ContractValidationError(
                    f"contract is not valid JSON: {exc}"
                ) from exc
        else:
            as_dict = payload

        try:
            contract = Contract.model_validate(as_dict)
        except ValidationError as exc:
            raise ContractValidationError(
                f"contract failed pydantic validation: {exc}"
            ) from exc

    try:
        jsonschema.validate(as_dict, _contract_json_schema())
    except jsonschema.ValidationError as exc:
        raise ContractValidationError(
            f"contract failed JSON-Schema validation: {exc.message}"
        ) from exc

    return contract


# ---------------------------------------------------------------------------
# Session record + CRUD
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Session:
    """In-memory session record returned by CRUD helpers."""

    __slots__ = ("id", "created_at", "updated_at", "status", "contract")

    def __init__(
        self,
        id: str,
        created_at: str,
        updated_at: str,
        status: str,
        contract: Contract,
    ) -> None:
        self.id = id
        self.created_at = created_at
        self.updated_at = updated_at
        self.status = status
        self.contract = contract

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "contract": self.contract.model_dump(mode="json"),
        }


def _row_to_session(row: sqlite3.Row) -> Session:
    contract = validate_contract_payload(row["contract_json"])
    return Session(
        id=row["id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        status=row["status"],
        contract=contract,
    )


def create_session(contract: Contract) -> Session:
    """Persist a new session for the given contract.

    The session id is the contract's ``meta.id`` so the two stay in sync.
    """
    init_db()
    contract = validate_contract_payload(contract)

    now = _now_iso()
    session_id = contract.meta.id
    contract_json = json.dumps(contract.model_dump(mode="json"))

    with _lock, _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if existing:
            raise ContractValidationError(
                f"session {session_id} already exists"
            )
        conn.execute(
            """
            INSERT INTO sessions (id, created_at, updated_at, status,
                                  contract_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, now, now, contract.meta.status, contract_json),
        )

    log.info(
        "contract.create_session",
        extra={"session_id": session_id, "status": contract.meta.status},
    )
    return Session(
        id=session_id,
        created_at=now,
        updated_at=now,
        status=contract.meta.status,
        contract=contract,
    )


def get_session(session_id: str) -> Session:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, created_at, updated_at, status, contract_json "
            "FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        raise SessionNotFoundError(f"session {session_id} not found")
    return _row_to_session(row)


def update_contract(session_id: str, contract: Contract) -> Session:
    """Replace the contract on an existing session."""
    init_db()
    contract = validate_contract_payload(contract)

    now = _now_iso()
    contract_json = json.dumps(contract.model_dump(mode="json"))

    with _lock, _connect() as conn:
        existing = conn.execute(
            "SELECT id, created_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if existing is None:
            raise SessionNotFoundError(f"session {session_id} not found")
        conn.execute(
            """
            UPDATE sessions
            SET updated_at = ?, status = ?, contract_json = ?
            WHERE id = ?
            """,
            (now, contract.meta.status, contract_json, session_id),
        )
        created_at = existing["created_at"]

    log.info(
        "contract.update_contract",
        extra={
            "session_id": session_id,
            "status": contract.meta.status,
            "version": contract.meta.version,
        },
    )
    return Session(
        id=session_id,
        created_at=created_at,
        updated_at=now,
        status=contract.meta.status,
        contract=contract,
    )


def add_decision(session_id: str, decision: Decision) -> Session:
    """Append a Decision to the session's contract and persist it."""
    session = get_session(session_id)
    contract = session.contract
    if contract.decisions is None:  # defensive; default_factory should populate
        contract.decisions = []
    # Avoid duplicates by id.
    if any(d.id == decision.id for d in contract.decisions):
        log.debug(
            "contract.add_decision.duplicate",
            extra={"session_id": session_id, "decision_id": decision.id},
        )
        return session
    contract.decisions.append(decision)
    log.info(
        "contract.add_decision",
        extra={
            "session_id": session_id,
            "decision_id": decision.id,
            "affects_count": len(decision.affects or []),
        },
    )
    return update_contract(session_id, contract)


def update_node(
    session_id: str,
    node_id: str,
    updates: NodeUpdateRequest,
) -> tuple[Node, list[str], dict[str, str]]:
    """Update a single node and tag changed fields as ``decided_by: user``.

    Only fields explicitly set on ``updates`` (i.e. not ``None``) are
    considered. Setting a field to its current value is a no-op and does
    not flip the node's provenance.

    For ``assumptions``, every assumption in the new list is marked as
    ``decided_by: user`` because the user is replacing the agent's
    assumption set wholesale.

    Returns:
        Tuple of ``(updated_node, fields_updated, provenance_changes)``.

    Raises:
        SessionNotFoundError: if the session does not exist.
        ValueError: if ``node_id`` is not present in the session's
            contract.
    """
    session = get_session(session_id)
    contract = session.contract

    node = next((n for n in contract.nodes if n.id == node_id), None)
    if node is None:
        raise ValueError(f"node {node_id} not found in session {session_id}")

    fields_updated: list[str] = []
    provenance_changes: dict[str, str] = {}

    if updates.description is not None and updates.description != node.description:
        node.description = updates.description
        fields_updated.append("description")
        provenance_changes["description"] = DecidedBy.USER.value

    if (
        updates.responsibilities is not None
        and list(updates.responsibilities) != list(node.responsibilities)
    ):
        node.responsibilities = list(updates.responsibilities)
        fields_updated.append("responsibilities")
        provenance_changes["responsibilities"] = DecidedBy.USER.value

    if updates.assumptions is not None:
        # Replace the assumption set; force every entry to user-decided so
        # the Compiler stops asking about them.
        new_assumptions = []
        for assumption in updates.assumptions:
            assumption_copy = assumption.model_copy(
                update={"decided_by": DecidedBy.USER}
            )
            new_assumptions.append(assumption_copy)
        # Treat any change to the assumptions list as a real update.
        existing = [a.model_dump(mode="json") for a in node.assumptions]
        proposed = [a.model_dump(mode="json") for a in new_assumptions]
        if existing != proposed:
            node.assumptions = new_assumptions
            fields_updated.append("assumptions")
            provenance_changes["assumptions"] = DecidedBy.USER.value

    if fields_updated:
        node.decided_by = DecidedBy.USER
        update_contract(session_id, contract)
        log.info(
            "contract.node_updated",
            extra={
                "session_id": session_id,
                "node_id": node_id,
                "fields_updated": fields_updated,
                "provenance_changes": provenance_changes,
                "new_decided_by": DecidedBy.USER.value,
            },
        )
    else:
        log.debug(
            "contract.node_update_noop",
            extra={"session_id": session_id, "node_id": node_id},
        )

    return node, fields_updated, provenance_changes


def add_verification_run(
    session_id: str, compiler_output: CompilerOutput
) -> Session:
    """Append a VerificationLogEntry derived from a CompilerOutput."""
    session = get_session(session_id)
    contract = session.contract
    entry = VerificationLogEntry(
        id=str(uuid.uuid4()),
        run_at=datetime.now(timezone.utc),
        verdict=(
            Verdict.PASS
            if (compiler_output.verdict == Verdict.PASS.value
                or compiler_output.verdict == Verdict.PASS)
            else Verdict.FAIL
        ),
        violations=list(compiler_output.violations),
        questions=list(compiler_output.questions),
        intent_guess=compiler_output.intent_guess or "",
        uvdc_score=float(compiler_output.uvdc_score or 0.0),
    )
    if contract.verification_log is None:
        contract.verification_log = []
    contract.verification_log.append(entry)
    log.info(
        "contract.add_verification_run",
        extra={
            "session_id": session_id,
            "verdict": (
                entry.verdict.value
                if hasattr(entry.verdict, "value")
                else entry.verdict
            ),
            "violation_count": len(entry.violations),
            "question_count": len(entry.questions),
            "uvdc_score": entry.uvdc_score,
        },
    )
    return update_contract(session_id, contract)


def list_sessions() -> list[Session]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, updated_at, status, contract_json "
            "FROM sessions ORDER BY created_at ASC"
        ).fetchall()
    return [_row_to_session(row) for row in rows]


def delete_session(session_id: str) -> None:
    init_db()
    with _lock, _connect() as conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE id = ?", (session_id,)
        )
        if cur.rowcount == 0:
            raise SessionNotFoundError(f"session {session_id} not found")
