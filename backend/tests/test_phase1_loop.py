"""Integration tests for the M3 Phase 1 loop.

Runs exactly 3 fixed iterations of (verify -> answer -> refine) with the
LLM mocked, and produces a structured ConfidenceReport that mirrors the
shape called out in the M3 task description.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Iterable

import pytest

from app import architect as architect_svc
from app import compiler as compiler_svc
from app import contract as contract_svc
from app.compiler import verify_contract
from app.schemas import (
    Assumption,
    ConfidenceReport,
    ConfidenceSnapshot,
    ConfidenceSummary,
    Contract,
    DecidedBy,
    Decision,
    Edge,
    EdgeKind,
    Meta,
    Node,
    NodeConfidenceUpdate,
    NodeKind,
    Verdict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _id() -> str:
    return str(uuid.uuid4())


def _build_seed_contract(prompt: str) -> Contract:
    """A seed contract with several agent-decided nodes/edges so the
    Compiler has work to do across multiple iterations."""
    ui = Node(
        id=_id(),
        name="Slack OAuth UI",
        kind=NodeKind.UI,
        responsibilities=["Sign in to Slack"],
        confidence=0.55,
        decided_by=DecidedBy.AGENT,
        open_questions=[],
        assumptions=[
            Assumption(
                text="OAuth scopes will include channels:history",
                confidence=0.5,
                decided_by=DecidedBy.AGENT,
                load_bearing=True,
            )
        ],
    )
    summarizer = Node(
        id=_id(),
        name="Summarizer",
        kind=NodeKind.SERVICE,
        responsibilities=["Summarize unread DMs"],
        confidence=0.65,
        decided_by=DecidedBy.AGENT,
    )
    store = Node(
        id=_id(),
        name="Digest Store",
        kind=NodeKind.STORE,
        responsibilities=["Persist daily digests"],
        confidence=0.7,
        decided_by=DecidedBy.AGENT,
    )
    slack_ext = Node(
        id=_id(),
        name="Slack API",
        kind=NodeKind.EXTERNAL,
        responsibilities=["Provide messages"],
        confidence=0.9,
        decided_by=DecidedBy.PROMPT,
    )

    edges = [
        Edge(
            id=_id(),
            source=ui.id,
            target=summarizer.id,
            kind=EdgeKind.DATA,
            payload_schema={"type": "object"},
            confidence=0.7,
            decided_by=DecidedBy.AGENT,
        ),
        Edge(
            id=_id(),
            source=summarizer.id,
            target=store.id,
            kind=EdgeKind.DATA,
            payload_schema={"type": "object"},
            confidence=0.7,
            decided_by=DecidedBy.AGENT,
        ),
        Edge(
            id=_id(),
            source=summarizer.id,
            target=slack_ext.id,
            kind=EdgeKind.DATA,
            payload_schema={"type": "object"},
            confidence=0.6,
            decided_by=DecidedBy.AGENT,
        ),
    ]
    return Contract(
        meta=Meta(id=_id(), stated_intent=prompt),
        nodes=[ui, summarizer, store, slack_ext],
        edges=edges,
    )


def _stub_architect_generate(prompt: str) -> Contract:
    return _build_seed_contract(prompt)


def _stub_architect_refine(contract: Contract, answers: Iterable[Decision]) -> Contract:
    """Mimic refinement: bump confidence + flip provenance to ``user`` for
    every node/edge mentioned in an answer's ``affects`` list, then
    increment the contract version."""
    affected: set[str] = set()
    for answer in answers:
        affected.update(answer.affects or [])

    new_contract = contract.model_copy(deep=True)
    for node in new_contract.nodes:
        if node.id in affected:
            node.decided_by = DecidedBy.USER
            node.confidence = min(1.0, node.confidence + 0.1)
            for assumption in node.assumptions:
                if assumption.load_bearing:
                    assumption.decided_by = DecidedBy.USER
                    assumption.confidence = min(1.0, assumption.confidence + 0.1)
    for edge in new_contract.edges:
        if edge.id in affected:
            edge.decided_by = DecidedBy.USER
            edge.confidence = min(1.0, edge.confidence + 0.1)

    # Make sure user answers always end up in decisions[]
    existing_ids = {d.id for d in new_contract.decisions}
    for answer in answers:
        if answer.id not in existing_ids:
            new_contract.decisions.append(answer)

    new_contract.meta.version = contract.meta.version + 1
    new_contract.meta.updated_at = datetime.now(timezone.utc)
    return new_contract


def _confidence_snapshot(
    contract: Contract,
    pass_number: int,
    reasoning: dict[str, str] | None = None,
) -> ConfidenceSnapshot:
    reasoning = reasoning or {}
    return ConfidenceSnapshot(
        pass_number=pass_number,
        timestamp=datetime.now(timezone.utc).isoformat(),
        nodes=[
            NodeConfidenceUpdate(
                node_id=n.id,
                new_confidence=n.confidence,
                reasoning=reasoning.get(n.id, ""),
            )
            for n in contract.nodes
        ],
    )


def generate_confidence_report(
    *,
    session_id: str,
    initial: ConfidenceSnapshot,
    final: ConfidenceSnapshot,
    per_pass: list[ConfidenceSnapshot],
) -> ConfidenceReport:
    """Build the structured confidence report used by the integration test."""
    by_init = {n.node_id: n.new_confidence for n in initial.nodes}
    nodes_improved = nodes_unchanged = nodes_degraded = 0
    deltas: list[float] = []
    degraded_ids: list[str] = []
    for node in final.nodes:
        init_conf = by_init.get(node.node_id, node.new_confidence)
        delta = node.new_confidence - init_conf
        deltas.append(delta)
        if init_conf >= 1.0:
            nodes_unchanged += 1
        elif delta > 1e-9:
            nodes_improved += 1
        elif delta < -1e-9:
            nodes_degraded += 1
            degraded_ids.append(node.node_id)
        else:
            nodes_unchanged += 1
    summary = ConfidenceSummary(
        nodes_improved=nodes_improved,
        nodes_unchanged=nodes_unchanged,
        nodes_degraded=nodes_degraded,
        average_delta=round(sum(deltas) / len(deltas), 4) if deltas else 0.0,
        degraded_node_ids=degraded_ids,
    )
    return ConfidenceReport(
        session_id=session_id,
        total_passes=len(per_pass),
        initial_snapshot=initial,
        final_snapshot=final,
        per_pass_snapshots=per_pass,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def looped_session(temp_db, monkeypatch):
    """Create a session, then return helpers to run the loop."""
    monkeypatch.setattr(
        architect_svc, "generate_contract", _stub_architect_generate
    )
    monkeypatch.setattr(architect_svc, "refine_contract", _stub_architect_refine)
    # Stub the LLM call so verify_contract is fully deterministic.
    monkeypatch.setattr(
        compiler_svc,
        "_call_llm_passes",
        lambda contract: ([], contract.meta.stated_intent or "", []),
    )

    contract = architect_svc.generate_contract(
        "Build a Slack bot that summarizes unread DMs daily."
    )
    session = contract_svc.create_session(contract)
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_three_pass_confidence_improvement(looped_session, caplog):
    """Run exactly 3 fixed iterations and check confidence improves overall."""
    session = looped_session
    sid = session.id
    caplog.set_level(logging.INFO)

    initial_snapshot = _confidence_snapshot(session.contract, pass_number=0)
    per_pass: list[ConfidenceSnapshot] = []

    for i in range(3):
        # 1. Verify
        contract = contract_svc.get_session(sid).contract
        output = verify_contract(contract, use_llm=False, pass_number=i + 1)
        contract_svc.add_verification_run(sid, output)

        # 2. Answer every emitted question, attaching every (now-low) node.
        all_node_ids = [n.id for n in contract.nodes]
        all_edge_ids = [e.id for e in contract.edges]
        decisions = [
            Decision(
                id=_id(),
                question=q,
                answer=f"User answer to: {q}",
                answered_at=datetime.now(timezone.utc),
                affects=all_node_ids + all_edge_ids,
            )
            for q in output.questions
        ]
        for d in decisions:
            contract_svc.add_decision(sid, d)

        # 3. Refine
        contract = contract_svc.get_session(sid).contract
        refined = architect_svc.refine_contract(contract, decisions)
        contract_svc.update_contract(sid, refined)

        # Snapshot confidence after this pass.
        per_pass.append(
            _confidence_snapshot(
                refined,
                pass_number=i + 1,
                reasoning={n.id: f"pass {i + 1}: user clarified" for n in refined.nodes},
            )
        )

    final_contract = contract_svc.get_session(sid).contract
    final_snapshot = _confidence_snapshot(final_contract, pass_number=3)

    report = generate_confidence_report(
        session_id=sid,
        initial=initial_snapshot,
        final=final_snapshot,
        per_pass=per_pass,
    )

    # Log the structured report; it would also be a fine artifact to drop on
    # disk for human inspection during demos.
    print(json.dumps(report.model_dump(mode="json"), default=str, indent=2))

    # Acceptance criteria: most nodes should improve, and none should
    # silently degrade.
    assert report.total_passes == 3
    assert report.summary.nodes_degraded == 0, (
        f"Degraded nodes detected: {report.summary.degraded_node_ids}"
    )
    assert report.summary.nodes_improved >= 1
    assert report.summary.average_delta > 0

    # The verification log must contain three entries (one per pass).
    final = contract_svc.get_session(sid).contract
    assert len(final.verification_log) == 3


def test_answered_questions_dont_reappear(looped_session, monkeypatch):
    """After answering every question, a re-verify should not reproduce them."""
    session = looped_session
    sid = session.id

    contract = contract_svc.get_session(sid).contract
    first = verify_contract(contract, use_llm=False, pass_number=1)
    assert first.questions, "expected questions on first verify"

    # Answer everything, attaching all nodes/edges so refinement clears
    # provenance flags + bumps confidence.
    all_ids = [n.id for n in contract.nodes] + [e.id for e in contract.edges]
    decisions = [
        Decision(
            id=_id(),
            question=q,
            answer="ack",
            answered_at=datetime.now(timezone.utc),
            affects=all_ids,
        )
        for q in first.questions
    ]
    for d in decisions:
        contract_svc.add_decision(sid, d)
    refined = architect_svc.refine_contract(
        contract_svc.get_session(sid).contract, decisions
    )
    contract_svc.update_contract(sid, refined)

    second = verify_contract(refined, use_llm=False, pass_number=2)
    # The exact same question text should not reappear.
    assert not (set(first.questions) & set(second.questions))


def test_verification_log_grows_per_verify(looped_session):
    sid = looped_session.id
    for i in range(3):
        out = verify_contract(
            contract_svc.get_session(sid).contract,
            use_llm=False,
            pass_number=i + 1,
        )
        contract_svc.add_verification_run(sid, out)
    final = contract_svc.get_session(sid).contract
    assert len(final.verification_log) == 3


def test_confidence_report_flags_degraded_nodes():
    """generate_confidence_report should surface degraded nodes."""
    initial = ConfidenceSnapshot(
        pass_number=0,
        timestamp=datetime.now(timezone.utc).isoformat(),
        nodes=[
            NodeConfidenceUpdate(node_id="n1", new_confidence=0.7),
            NodeConfidenceUpdate(node_id="n2", new_confidence=0.8),
            NodeConfidenceUpdate(node_id="n3", new_confidence=1.0),
        ],
    )
    final = ConfidenceSnapshot(
        pass_number=3,
        timestamp=datetime.now(timezone.utc).isoformat(),
        nodes=[
            NodeConfidenceUpdate(node_id="n1", new_confidence=0.95),
            NodeConfidenceUpdate(node_id="n2", new_confidence=0.6),  # degraded
            NodeConfidenceUpdate(node_id="n3", new_confidence=1.0),  # unchanged
        ],
    )
    report = generate_confidence_report(
        session_id="sess-1",
        initial=initial,
        final=final,
        per_pass=[final],
    )
    assert report.summary.nodes_improved == 1
    assert report.summary.nodes_degraded == 1
    assert report.summary.nodes_unchanged == 1
    assert "n2" in report.summary.degraded_node_ids
