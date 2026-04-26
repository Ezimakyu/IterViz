"""In-memory storage for implementation subgraphs.

M6 keeps subgraphs purely in process memory: they are derived artifacts
and do not need durable persistence for the demo. Storage is keyed by
``(session_id, parent_node_id)``.

A future milestone may persist subgraphs alongside contracts in
SQLite; the API is intentionally narrow so that swap is straightforward.
"""

from __future__ import annotations

import threading
from typing import Optional

from .schemas import ImplementationSubgraph

# session_id -> parent_node_id -> ImplementationSubgraph
_subgraphs: dict[str, dict[str, ImplementationSubgraph]] = {}
_lock = threading.RLock()


def store_subgraph(subgraph: ImplementationSubgraph) -> ImplementationSubgraph:
    """Insert or overwrite the subgraph for ``parent_node_id`` in its session."""

    with _lock:
        bucket = _subgraphs.setdefault(subgraph.session_id, {})
        bucket[subgraph.parent_node_id] = subgraph
    return subgraph


def get_subgraph(
    session_id: str, parent_node_id: str
) -> Optional[ImplementationSubgraph]:
    """Return the subgraph for a node, or ``None`` if none has been generated."""

    with _lock:
        return _subgraphs.get(session_id, {}).get(parent_node_id)


def get_all_subgraphs(session_id: str) -> list[ImplementationSubgraph]:
    """List every subgraph for a session in insertion order."""

    with _lock:
        return list(_subgraphs.get(session_id, {}).values())


def update_subgraph(subgraph: ImplementationSubgraph) -> ImplementationSubgraph:
    """Persist an updated subgraph (alias for :func:`store_subgraph`)."""

    return store_subgraph(subgraph)


def clear_session(session_id: str) -> None:
    """Drop all subgraphs for a session (used by tests)."""

    with _lock:
        _subgraphs.pop(session_id, None)


def clear_all() -> None:
    """Drop every cached subgraph (used by tests)."""

    with _lock:
        _subgraphs.clear()


__all__ = [
    "store_subgraph",
    "get_subgraph",
    "get_all_subgraphs",
    "update_subgraph",
    "clear_session",
    "clear_all",
]
