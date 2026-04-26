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
    update_node,
    validate_contract_payload,
)
from app.schemas import (
    Assumption,
    DecidedBy,
    NodeUpdateRequest,
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


# ---------------------------------------------------------------------------
# M4: update_node — direct user edits with provenance tracking
# ---------------------------------------------------------------------------


class TestUpdateNode:
    """``update_node`` flips ``decided_by`` to ``user`` for any changed
    field and persists the new contract. Unchanged fields keep their
    original provenance.
    """

    def test_description_edit_sets_user_provenance(
        self, temp_db, sample_contract
    ):
        create_session(sample_contract)
        sid = sample_contract.meta.id
        target_node = sample_contract.nodes[0]

        updates = NodeUpdateRequest(description="User-supplied description")
        node, fields_updated, provenance = update_node(
            sid, target_node.id, updates
        )

        assert node.description == "User-supplied description"
        assert fields_updated == ["description"]
        assert provenance == {"description": "user"}
        # The node-level decided_by must flip to ``user`` after an edit.
        assert (
            node.decided_by == DecidedBy.USER
            or node.decided_by == DecidedBy.USER.value
        )

        # Persisted to the DB.
        fetched = get_session(sid)
        persisted_node = next(
            n for n in fetched.contract.nodes if n.id == target_node.id
        )
        assert persisted_node.description == "User-supplied description"
        assert (
            persisted_node.decided_by == DecidedBy.USER.value
            or persisted_node.decided_by == DecidedBy.USER
        )

    def test_unchanged_fields_keep_their_values(
        self, temp_db, sample_contract
    ):
        create_session(sample_contract)
        sid = sample_contract.meta.id
        target_node = sample_contract.nodes[0]
        original_responsibilities = list(target_node.responsibilities)

        updates = NodeUpdateRequest(description="Another description")
        _, fields_updated, provenance = update_node(
            sid, target_node.id, updates
        )

        assert "responsibilities" not in fields_updated
        assert "responsibilities" not in provenance

        fetched = get_session(sid)
        persisted_node = next(
            n for n in fetched.contract.nodes if n.id == target_node.id
        )
        assert persisted_node.responsibilities == original_responsibilities

    def test_assumption_replacement_marks_each_user_decided(
        self, temp_db, sample_contract
    ):
        create_session(sample_contract)
        sid = sample_contract.meta.id
        target_node = sample_contract.nodes[0]

        new_assumptions = [
            Assumption(
                text="User assumption A",
                confidence=0.9,
                decided_by=DecidedBy.AGENT,  # will be flipped to user
                load_bearing=True,
            ),
            Assumption(
                text="User assumption B",
                confidence=0.7,
                decided_by=DecidedBy.AGENT,  # will be flipped to user
                load_bearing=False,
            ),
        ]
        updates = NodeUpdateRequest(assumptions=new_assumptions)
        node, fields_updated, provenance = update_node(
            sid, target_node.id, updates
        )

        assert "assumptions" in fields_updated
        assert provenance["assumptions"] == "user"
        assert all(
            (a.decided_by == DecidedBy.USER or a.decided_by == "user")
            for a in node.assumptions
        )

    def test_invalid_node_id_raises_value_error(
        self, temp_db, sample_contract
    ):
        create_session(sample_contract)
        sid = sample_contract.meta.id

        with pytest.raises(ValueError, match="not found"):
            update_node(
                sid,
                "this-node-does-not-exist",
                NodeUpdateRequest(description="x"),
            )

    def test_invalid_session_id_raises_session_not_found(
        self, temp_db, sample_contract
    ):
        with pytest.raises(SessionNotFoundError):
            update_node(
                "missing-session",
                "any-node",
                NodeUpdateRequest(description="x"),
            )

    def test_no_op_update_does_not_flip_provenance(
        self, temp_db, sample_contract
    ):
        # Force the target node to a known non-user provenance so we can
        # detect any spurious flip.
        sample_contract.nodes[0].decided_by = DecidedBy.PROMPT
        create_session(sample_contract)
        sid = sample_contract.meta.id
        target_node = sample_contract.nodes[0]

        # Update the description with the *same* value it already has —
        # this should not be reported as a change.
        updates = NodeUpdateRequest(description=target_node.description)
        node, fields_updated, provenance = update_node(
            sid, target_node.id, updates
        )

        assert fields_updated == []
        assert provenance == {}
        # decided_by must NOT be flipped to user when there were no
        # actual changes.
        assert (
            node.decided_by == DecidedBy.PROMPT
            or node.decided_by == DecidedBy.PROMPT.value
        )

    def test_multi_field_update_reports_all_changed(
        self, temp_db, sample_contract
    ):
        create_session(sample_contract)
        sid = sample_contract.meta.id
        target_node = sample_contract.nodes[0]

        updates = NodeUpdateRequest(
            description="New description",
            responsibilities=["new resp 1", "new resp 2"],
        )
        node, fields_updated, provenance = update_node(
            sid, target_node.id, updates
        )

        assert set(fields_updated) == {"description", "responsibilities"}
        assert provenance == {
            "description": "user",
            "responsibilities": "user",
        }
        assert node.responsibilities == ["new resp 1", "new resp 2"]
