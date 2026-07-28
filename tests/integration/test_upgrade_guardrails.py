"""The rules around upgrading, separate from any one prior version.

Three of them decide whether an upgrade is safe rather than merely successful:
a first run is not an upgrade and should not manufacture a checkpoint; a
checkpoint that cannot be written stops the migration instead of proceeding
without it; and a database written by a *newer* build is refused rather than
quietly used, because migrations are forward-only and there is no honest way to
read a schema this build has never seen.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codeatlas.domain.errors import (
    BackupFailedError,
    ErrorCode,
    SchemaVersionUnsupportedError,
)
from codeatlas.storage.sqlite.backup import read_schema_version
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import (
    SCHEMA_VERSION,
    apply_migrations,
    pending_versions,
)
from codeatlas.storage.sqlite.upgrade import (
    checkpoint_path_for,
    plan_upgrade,
    upgrade_database,
)


def _migrated(path: Path) -> Path:
    with connect(path) as connection:
        apply_migrations(connection)
    return path


def _at_version(database: Path, version: int) -> None:
    """Roll the recorded version back so an upgrade has work to do.

    Only the bookkeeping row is removed: the tables stay. That is enough for the
    checkpoint policy under test, which reads the recorded version and never
    inspects the shape of what it is copying.
    """
    with connect(database) as connection:
        connection.execute(
            "DELETE FROM schema_migrations WHERE version > ?", (version,)
        )


def _claiming_version(path: Path, version: int) -> Path:
    """A database that records a schema version this build does not have."""
    _migrated(path)
    with connect(path) as connection:
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, "2030-01-01T00:00:00Z"),
        )
    return path


# --- planning -------------------------------------------------------------


def test_planning_does_not_create_the_database(tmp_path: Path) -> None:
    """`doctor` plans before it opens. Planning must not be what creates the
    file it was asked to describe."""
    absent = tmp_path / "absent.db"

    plan = plan_upgrade(absent)

    assert plan.current_version == 0
    assert plan.target_version == SCHEMA_VERSION
    assert plan.pending == pending_versions(0)
    assert not absent.exists()


def test_an_up_to_date_database_needs_no_upgrade(tmp_path: Path) -> None:
    database = _migrated(tmp_path / "db.sqlite")

    plan = plan_upgrade(database)

    assert plan.current_version == SCHEMA_VERSION
    assert plan.pending == ()
    assert not plan.is_required


# --- checkpoints ----------------------------------------------------------


def test_a_first_run_is_not_an_upgrade(tmp_path: Path) -> None:
    """Version 0 has nothing to lose. A checkpoint of an empty file would be
    noise in a directory where every file is supposed to mean something."""
    database = tmp_path / "db.sqlite"

    result = upgrade_database(database)

    assert result.from_version == 0
    assert result.to_version == SCHEMA_VERSION
    assert result.checkpoint_path is None
    assert list(tmp_path.glob("*.pre-upgrade-*")) == []


def test_a_checkpoint_that_cannot_be_written_stops_the_upgrade(
    prior_version_database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The constraint is that the migration is *preceded* by a checkpoint. If
    the checkpoint fails, proceeding would satisfy the letter of an upgrade and
    none of its purpose."""
    before = read_schema_version(prior_version_database)

    def refuse(*_: object, **__: object) -> None:
        raise BackupFailedError("disk is full")

    monkeypatch.setattr("codeatlas.storage.sqlite.upgrade.create_backup", refuse)

    with pytest.raises(BackupFailedError):
        upgrade_database(prior_version_database)

    assert read_schema_version(prior_version_database) == before, (
        "it migrated without a checkpoint"
    )


# --- refusing a newer database --------------------------------------------


def test_a_newer_database_is_refused(tmp_path: Path) -> None:
    database = _claiming_version(tmp_path / "db.sqlite", SCHEMA_VERSION + 1)

    with pytest.raises(SchemaVersionUnsupportedError) as raised:
        upgrade_database(database)

    assert raised.value.code is ErrorCode.SCHEMA_VERSION_UNSUPPORTED
    assert not raised.value.retryable
    # The versions belong in the error: "upgrade CodeAtlas" is only actionable
    # advice if the user can see which side is behind.
    assert raised.value.details["found_version"] == str(SCHEMA_VERSION + 1)
    assert raised.value.details["supported_version"] == str(SCHEMA_VERSION)


def test_applying_migrations_refuses_a_newer_database_too(tmp_path: Path) -> None:
    """The guard lives in `apply_migrations`, not only in the upgrade path, so
    a call site that opens a database directly cannot bypass it."""
    database = _claiming_version(tmp_path / "db.sqlite", SCHEMA_VERSION + 5)

    with connect(database) as connection, pytest.raises(SchemaVersionUnsupportedError):
        apply_migrations(connection)


def test_a_refused_database_is_left_untouched(tmp_path: Path) -> None:
    database = _claiming_version(tmp_path / "db.sqlite", SCHEMA_VERSION + 1)
    before = database.read_bytes()

    with pytest.raises(SchemaVersionUnsupportedError):
        upgrade_database(database)

    assert database.read_bytes() == before
    assert list(tmp_path.glob("*.pre-upgrade-*")) == []


def test_the_checkpoint_is_named_for_the_version_it_preserves(
    prior_version_database: Path,
) -> None:
    """A user hunting for a way back looks for "the database as it was", so the
    name carries the version being left behind rather than the new one."""
    found = read_schema_version(prior_version_database)

    result = upgrade_database(prior_version_database)

    assert result.checkpoint_path is not None
    assert result.checkpoint_path.name.endswith(f"pre-upgrade-v{found}")
    assert result.checkpoint_path == checkpoint_path_for(prior_version_database, found)


def test_the_checkpoint_is_a_real_database(prior_version_database: Path) -> None:
    result = upgrade_database(prior_version_database)

    assert result.checkpoint_path is not None
    with sqlite3.connect(result.checkpoint_path) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    assert row[0] == "ok"
