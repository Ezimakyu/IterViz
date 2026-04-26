"""Tests for app.contract — SQLite persistence + JSON schema validation."""

from __future__ import annotations

import pytest

from app import contract as contract_svc
from app.contract import (
    ContractValidationError,
    SessionNotFoundError,
    create_session,
    get_session,
    list_sessions,
    update_contract,
    validate_contract_payload,
)


def test_create_session_persists(temp_db, sample_contract):
    session = create_session(sample_contract)
    assert session.id == sample_contract.meta.id
    assert session.status == "drafting"

    # Round-trip through the DB.
    fetched = get_session(session.id)
    assert fetched.id == session.id
    assert fetched.contract.meta.id == session.contract.meta.id
    assert len(fetched.contract.nodes) == 3
    assert len(fetched.contract.edges) == 2


def test_get_session_missing_raises(temp_db):
    with pytest.raises(SessionNotFoundError):
        get_session("does-not-exist")


def test_update_contract_persists_changes(temp_db, sample_contract):
    create_session(sample_contract)
    updated = sample_contract.model_copy(deep=True)
    updated.meta.version = sample_contract.meta.version + 1
    updated.meta.status = "verified"

    persisted = update_contract(sample_contract.meta.id, updated)
    assert persisted.contract.meta.version == updated.meta.version
    assert persisted.status == "verified"

    fetched = get_session(sample_contract.meta.id)
    assert fetched.contract.meta.version == updated.meta.version
    assert fetched.status == "verified"


def test_update_contract_missing_raises(temp_db, sample_contract):
    with pytest.raises(SessionNotFoundError):
        update_contract("missing-id", sample_contract)


def test_create_session_duplicate_raises(temp_db, sample_contract):
    create_session(sample_contract)
    with pytest.raises(ContractValidationError):
        create_session(sample_contract)


def test_validate_contract_rejects_garbage():
    with pytest.raises(ContractValidationError):
        validate_contract_payload("not-json")
    with pytest.raises(ContractValidationError):
        validate_contract_payload({"meta": {}})


def test_validate_contract_accepts_dict_form(sample_contract):
    as_dict = sample_contract.model_dump(mode="json")
    parsed = validate_contract_payload(as_dict)
    assert parsed.meta.id == sample_contract.meta.id


def test_list_sessions(temp_db, sample_contract):
    create_session(sample_contract)
    other = sample_contract.model_copy(deep=True)
    other.meta.id = "other-session-id"
    create_session(other)

    sessions = list_sessions()
    assert {s.id for s in sessions} == {sample_contract.meta.id, "other-session-id"}


def test_temp_db_isolated(tmp_path, sample_contract):
    """Each test using ``temp_db`` should write to its own file."""
    db = tmp_path / "isolated.db"
    contract_svc.set_db_path(db)
    try:
        contract_svc.init_db()
        create_session(sample_contract)
        assert db.exists()
    finally:
        contract_svc.set_db_path(None)
