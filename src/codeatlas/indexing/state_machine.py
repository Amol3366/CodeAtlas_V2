"""Snapshot lifecycle state machine (Blueprint §4.3.6, CLAUDE.md §2.10).

    staging -> validating -> active
       |            |
       +------------+--> failed

Active snapshots may only move to ``superseded`` (when a newer snapshot
activates). ``failed`` and ``superseded`` are terminal. A snapshot activates
only after all stores succeed — enforced by making activation a single
transaction in :class:`SnapshotManager`.
"""

from __future__ import annotations

from codeatlas.domain.enums import SnapshotStatus
from codeatlas.domain.errors import SnapshotError

_ALLOWED: dict[SnapshotStatus, frozenset[SnapshotStatus]] = {
    SnapshotStatus.STAGING: frozenset({SnapshotStatus.VALIDATING, SnapshotStatus.FAILED}),
    SnapshotStatus.VALIDATING: frozenset({SnapshotStatus.ACTIVE, SnapshotStatus.FAILED}),
    SnapshotStatus.ACTIVE: frozenset({SnapshotStatus.SUPERSEDED}),
    SnapshotStatus.FAILED: frozenset(),
    SnapshotStatus.SUPERSEDED: frozenset(),
}

# Pre-active states from which a snapshot may still be activated.
PRE_ACTIVE: frozenset[SnapshotStatus] = frozenset(
    {SnapshotStatus.STAGING, SnapshotStatus.VALIDATING}
)


def can_transition(source: SnapshotStatus, target: SnapshotStatus) -> bool:
    return target in _ALLOWED.get(source, frozenset())


def assert_transition(source: SnapshotStatus, target: SnapshotStatus) -> None:
    if not can_transition(source, target):
        raise SnapshotError(f"Illegal snapshot transition: {source.value} -> {target.value}")
