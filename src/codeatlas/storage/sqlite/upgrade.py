"""Upgrading an existing database to the schema this build understands.

Applying migrations is the easy half. The half that matters is what happens
around it, and Phase 6 fixes three rules (ADR-0007 Outcome, P6-07):

* **A migration that can lose data is preceded by a checkpoint.** Before any
  pending migration runs against a database that already holds something, a
  verified copy is written beside it. If the checkpoint cannot be written, the
  migration does not run — proceeding would satisfy the letter of an upgrade
  and none of its purpose.
* **A first run is not an upgrade.** A database at version 0 has nothing to
  lose, so it is created rather than checkpointed.
* **A newer database is refused, not used.** Migrations are forward-only. A
  build that opened a schema from the future would answer plausibly right up
  until it wrote into a column whose meaning had changed.

Both entry points — the implicit upgrade every command performs on open, and
the explicit ``codeatlas upgrade`` — go through :func:`upgrade_database`. A
second path that migrated would be a second set of rules about when to
checkpoint, and the two would drift.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from codeatlas.domain.errors import SchemaVersionUnsupportedError
from codeatlas.storage.sqlite.backup import create_backup, read_schema_version
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import (
    SCHEMA_VERSION,
    apply_migrations,
    pending_versions,
)

# Named for the version it preserves, not the one it upgrades to: a user
# hunting for a way back is looking for "the database as it was".
_CHECKPOINT_TEMPLATE = "{name}.pre-upgrade-v{version}"

# The rows an upgrade must never lose. Snapshots and conversations are the two
# the Phase 6 gate names; the rest are what they would be meaningless without.
_DURABLE_TABLES = (
    "repositories",
    "snapshots",
    "files",
    "symbols",
    "conversations",
    "messages",
)

ROWS_LOST_WARNING = "UPGRADE_ROW_COUNT_DECREASED"


@dataclass(frozen=True)
class UpgradePlan:
    """What an upgrade would do, determined without touching the database."""

    path: Path
    current_version: int
    target_version: int
    pending: tuple[int, ...]

    @property
    def is_required(self) -> bool:
        return bool(self.pending)


@dataclass(frozen=True)
class UpgradeResult:
    """What an upgrade did."""

    path: Path
    from_version: int
    to_version: int
    applied: tuple[int, ...]
    checkpoint_path: Path | None
    counts: Mapping[str, int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def upgraded(self) -> bool:
        return bool(self.applied)


def plan_upgrade(database: Path) -> UpgradePlan:
    """Describe the upgrade without performing it, and without creating a file.

    ``doctor`` calls this before opening the database, so that it can report the
    version it *found* rather than the one it caused.
    """
    current = read_schema_version(database) if database.is_file() else 0
    return UpgradePlan(
        path=database,
        current_version=current,
        target_version=SCHEMA_VERSION,
        pending=pending_versions(current),
    )


def upgrade_database(database: Path) -> UpgradeResult:
    """Bring ``database`` to this build's schema, checkpointing first."""
    plan = plan_upgrade(database)

    if plan.current_version > SCHEMA_VERSION:
        # Raised before anything is opened for writing, so a refused database is
        # left byte-for-byte as it was found.
        raise SchemaVersionUnsupportedError(
            "This database was written by a newer version of CodeAtlas.",
            details={
                "found_version": str(plan.current_version),
                "supported_version": str(SCHEMA_VERSION),
                "path": database.name,
            },
        )

    if not plan.is_required:
        with connect(database) as connection:
            counts = _row_counts(connection)
        return UpgradeResult(
            path=database,
            from_version=plan.current_version,
            to_version=plan.current_version,
            applied=(),
            checkpoint_path=None,
            counts=counts,
        )

    checkpoint = _checkpoint(database, plan.current_version)

    with connect(database) as connection:
        before = _row_counts(connection)
        apply_migrations(connection)
        after = _row_counts(connection)

    lost = sorted(
        table for table, count in before.items() if after.get(table, 0) < count
    )
    return UpgradeResult(
        path=database,
        from_version=plan.current_version,
        to_version=SCHEMA_VERSION,
        applied=plan.pending,
        checkpoint_path=checkpoint,
        counts=after,
        # Reported rather than raised: by the time this is known the migration
        # has committed. The checkpoint above is the way back, and saying so is
        # more use than a failure that cannot undo anything.
        warnings=(ROWS_LOST_WARNING,) if lost else (),
    )


def checkpoint_path_for(database: Path, version: int) -> Path:
    """Where the pre-upgrade copy of ``database`` at ``version`` is kept."""
    return database.with_name(
        _CHECKPOINT_TEMPLATE.format(name=database.name, version=version)
    )


def _checkpoint(database: Path, version: int) -> Path | None:
    """Copy the database before migrating it, unless there is nothing to keep.

    Version 0 means the file is about to be created. Checkpointing that would
    leave an empty database beside the real one, which is worse than useless:
    it looks like a way back.
    """
    if version <= 0 or not database.is_file():
        return None

    destination = checkpoint_path_for(database, version)
    create_backup(database, destination)
    return destination


def _row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """Count the durable tables that exist right now.

    The set is filtered by what the database actually has, because these counts
    are taken on both sides of a migration and the older side may predate a
    table the newer one introduced.
    """
    present = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    counts: dict[str, int] = {}
    for table in _DURABLE_TABLES:
        if table not in present:
            continue
        row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        counts[table] = int(row[0])
    return counts
