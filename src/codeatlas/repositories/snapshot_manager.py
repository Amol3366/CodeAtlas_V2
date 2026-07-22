"""Snapshot creation and atomic activation (Blueprint §4.3.6-4.3.7, CLAUDE.md §2.10).

Activation is a single coordinated-writer transaction: the newly-activated
snapshot flips to ACTIVE and any prior ACTIVE snapshot is superseded in the same
transaction, so an active-scope query never sees two active snapshots or a
half-activated one (CLAUDE.md §2.7, §2.10).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from codeatlas.domain.entities import Snapshot
from codeatlas.domain.enums import IndexStatus, SnapshotStatus, SnapshotType
from codeatlas.domain.errors import SnapshotError
from codeatlas.indexing.state_machine import PRE_ACTIVE, assert_transition
from codeatlas.logging.setup import get_logger
from codeatlas.storage.sqlite.repositories import SnapshotStore
from codeatlas.storage.sqlite.writer import CoordinatedWriter


def _new_snapshot_id() -> str:
    return f"snap_{uuid.uuid4().hex}"


class SnapshotManager:
    def __init__(self, writer: CoordinatedWriter) -> None:
        self._writer = writer

    async def create_staging(
        self,
        repository_id: str,
        *,
        snapshot_type: SnapshotType,
        parser_bundle_version: str = "0.1.0",
        chunker_version: str = "0.1.0",
        retrieval_policy_version: str = "0.1.0",
        branch: str | None = None,
        commit_sha: str | None = None,
        working_tree_hash: str | None = None,
        now: datetime | None = None,
    ) -> Snapshot:
        snapshot = Snapshot(
            id=_new_snapshot_id(),
            repository_id=repository_id,
            snapshot_type=snapshot_type,
            status=SnapshotStatus.STAGING,
            parser_bundle_version=parser_bundle_version,
            chunker_version=chunker_version,
            retrieval_policy_version=retrieval_policy_version,
            deterministic_index_status=IndexStatus.PENDING,
            semantic_index_status=IndexStatus.PENDING,
            branch=branch,
            commit_sha=commit_sha,
            working_tree_hash=working_tree_hash,
            created_at=now or datetime.now(UTC),
        )
        async with self._writer.transaction() as session:
            await SnapshotStore(session).add(snapshot)
        return snapshot

    async def begin_validation(self, snapshot_id: str) -> None:
        async with self._writer.transaction() as session:
            store = SnapshotStore(session)
            snapshot = await store.get(snapshot_id)
            if snapshot is None:
                raise SnapshotError(f"Unknown snapshot: {snapshot_id}")
            assert_transition(snapshot.status, SnapshotStatus.VALIDATING)
            await store.set_status(snapshot_id, SnapshotStatus.VALIDATING)

    async def activate(self, snapshot_id: str, *, now: datetime | None = None) -> None:
        """Atomically activate a snapshot, superseding any prior active one."""
        async with self._writer.transaction() as session:
            store = SnapshotStore(session)
            snapshot = await store.get(snapshot_id)
            if snapshot is None:
                raise SnapshotError(f"Unknown snapshot: {snapshot_id}")
            if snapshot.status not in PRE_ACTIVE:
                raise SnapshotError(f"Cannot activate snapshot in state {snapshot.status.value}")
            prior = await store.get_active(snapshot.repository_id)
            if prior is not None and prior.id != snapshot_id:
                await store.set_status(prior.id, SnapshotStatus.SUPERSEDED)
            await store.update_fields(
                snapshot_id,
                status=SnapshotStatus.ACTIVE.value,
                deterministic_index_status=IndexStatus.READY.value,
                activated_at=now or datetime.now(UTC),
            )
        get_logger(repository_id=snapshot.repository_id).info(
            "snapshot.activated", snapshot_id=snapshot_id
        )

    async def fail(self, snapshot_id: str) -> None:
        async with self._writer.transaction() as session:
            await SnapshotStore(session).set_status(snapshot_id, SnapshotStatus.FAILED)
