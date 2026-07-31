"""Backup, restore, and the integrity checks that make them worth having.

A backup a user believes in but cannot restore from is worse than no backup,
because it displaces the caution they would otherwise have. So every test here
asks one of two questions: does the copy actually contain the data, and does a
restore that cannot succeed refuse *before* it has destroyed anything?

SQLite in WAL mode cannot be safely copied while open — a file copy can capture
a torn page — so backup uses the online backup API (ADR-0007 decision 4).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.lookup import SymbolLookupRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.errors import (
    BackupFailedError,
    IntegrityCheckFailedError,
    RestoreIncompatibleError,
)
from codeatlas.storage.sqlite import backup as backup_module
from codeatlas.storage.sqlite.backup import (
    check_integrity,
    create_backup,
    read_schema_version,
    restore,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import SCHEMA_VERSION, apply_migrations


def _populate(database: Path, root: Path) -> str:
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        services.indexing.index(repository.repository_id)
        return repository.repository_id


# --- Backup ---------------------------------------------------------------


def test_a_backup_contains_the_data_it_was_taken_from(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _populate(database, sample_repo)
    destination = tmp_path / "backups" / "atlas.sqlite"

    result = create_backup(database, destination)

    assert result.path == destination
    assert destination.exists()
    with connect(destination) as connection:
        services = build_services(connection)
        found = services.lookup.lookup(
            SymbolLookupRequest(repository_id, "PaymentService.capture", "req-1")
        )
    assert found.evidence


def test_a_backup_is_taken_while_the_database_is_open(
    tmp_path: Path, sample_repo: Path
) -> None:
    """The case a file copy cannot handle safely.

    WAL means recent commits may live in the -wal side file, so a naive copy of
    the main file alone can miss them or capture a torn page. The online backup
    API is what makes an open database copyable at all.
    """
    database = tmp_path / "db.sqlite"
    repository_id = _populate(database, sample_repo)
    destination = tmp_path / "open-backup.sqlite"

    with connect(database) as live:
        # A write that is committed but may still be in the WAL.
        live.execute(
            "UPDATE repositories SET display_name = 'renamed'"
            " WHERE repository_id = ?",
            (repository_id,),
        )
        live.commit()
        create_backup(database, destination)

    with connect(destination) as connection:
        name = connection.execute(
            "SELECT display_name FROM repositories WHERE repository_id = ?",
            (repository_id,),
        ).fetchone()[0]
    assert name == "renamed"


def test_a_backup_passes_its_own_integrity_check(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    _populate(database, sample_repo)
    destination = tmp_path / "atlas.sqlite"

    create_backup(database, destination)

    check_integrity(destination)  # raises if it does not


def test_a_backup_records_the_schema_version_it_captured(
    tmp_path: Path, sample_repo: Path
) -> None:
    """The database is self-describing, so no sidecar manifest can drift."""
    database = tmp_path / "db.sqlite"
    _populate(database, sample_repo)
    destination = tmp_path / "atlas.sqlite"

    result = create_backup(database, destination)

    assert result.schema_version == SCHEMA_VERSION
    assert read_schema_version(destination) == SCHEMA_VERSION


def test_backing_up_a_missing_database_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(BackupFailedError):
        create_backup(tmp_path / "absent.sqlite", tmp_path / "out.sqlite")


def test_a_failed_backup_leaves_no_half_written_file(tmp_path: Path) -> None:
    """A partial file at the destination is a backup someone will later trust."""
    destination = tmp_path / "out.sqlite"

    with pytest.raises(BackupFailedError):
        create_backup(tmp_path / "absent.sqlite", destination)

    assert not destination.exists()


def test_a_backup_does_not_overwrite_the_previous_one_until_it_succeeds(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    _populate(database, sample_repo)
    destination = tmp_path / "atlas.sqlite"
    create_backup(database, destination)
    first_size = destination.stat().st_size

    with pytest.raises(BackupFailedError):
        create_backup(tmp_path / "absent.sqlite", destination)

    assert destination.stat().st_size == first_size
    check_integrity(destination)


# --- Integrity ------------------------------------------------------------


def test_a_corrupted_database_fails_its_integrity_check(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)

    # Overwrite pages in the middle of the file: valid header, damaged content.
    with database.open("r+b") as handle:
        handle.seek(4096)
        handle.write(b"\x00" * 8192)

    with pytest.raises(IntegrityCheckFailedError):
        check_integrity(database)


def test_a_file_that_is_not_a_database_fails_its_integrity_check(
    tmp_path: Path,
) -> None:
    impostor = tmp_path / "notes.txt"
    impostor.write_text("this is not a database", encoding="utf-8")

    with pytest.raises(IntegrityCheckFailedError):
        check_integrity(impostor)


# --- Restore --------------------------------------------------------------


def test_restore_replaces_the_target_with_the_backup(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _populate(database, sample_repo)
    backup = tmp_path / "atlas.sqlite"
    create_backup(database, backup)

    # Move on: the live database gains a repository the backup never had.
    other = tmp_path / "other"
    (other / "src").mkdir(parents=True)
    (other / "src" / "later.py").write_text(
        "def later() -> int:\n    return 1\n", encoding="utf-8"
    )
    with connect(database) as connection:
        services = build_services(connection)
        services.registration.register(RegisterRepositoryRequest(path=str(other)))

    restore(backup, database)

    with connect(database) as connection:
        ids = [
            row[0]
            for row in connection.execute("SELECT repository_id FROM repositories")
        ]
    assert ids == [repository_id]


def test_restore_keeps_the_database_it_replaced(
    tmp_path: Path, sample_repo: Path
) -> None:
    """CLAUDE.md section 15: back up before a destructive operation.

    Restore is the most destructive thing the product does, so the database it
    overwrites is preserved. A user who restores the wrong file has a way back.
    """
    database = tmp_path / "db.sqlite"
    _populate(database, sample_repo)
    backup = tmp_path / "atlas.sqlite"
    create_backup(database, backup)

    result = restore(backup, database)

    assert result.replaced_path is not None
    assert result.replaced_path.exists()
    check_integrity(result.replaced_path)


def test_restore_refuses_a_database_from_a_newer_schema(
    tmp_path: Path, sample_repo: Path
) -> None:
    """Migrations are forward-only, so there is no honest way to accept it."""
    database = tmp_path / "db.sqlite"
    _populate(database, sample_repo)
    backup = tmp_path / "future.sqlite"
    create_backup(database, backup)
    with connect(backup) as connection:
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at)"
            " VALUES (?, '2099-01-01T00:00:00Z')",
            (SCHEMA_VERSION + 1,),
        )
        connection.commit()

    with pytest.raises(RestoreIncompatibleError):
        restore(backup, database)


def test_restore_accepts_an_older_schema_because_migrations_move_forward(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    _populate(database, sample_repo)
    backup = tmp_path / "older.sqlite"
    create_backup(database, backup)
    with connect(backup) as connection:
        connection.execute(
            "DELETE FROM schema_migrations WHERE version = ?", (SCHEMA_VERSION,)
        )
        connection.commit()

    result = restore(backup, database)

    assert result.schema_version == SCHEMA_VERSION - 1


def test_restore_refuses_a_corrupted_backup_without_touching_the_target(
    tmp_path: Path, sample_repo: Path
) -> None:
    """The test that matters most: refusing must happen *before* replacing."""
    database = tmp_path / "db.sqlite"
    repository_id = _populate(database, sample_repo)
    backup = tmp_path / "atlas.sqlite"
    create_backup(database, backup)
    with backup.open("r+b") as handle:
        handle.seek(4096)
        handle.write(b"\x00" * 8192)

    with pytest.raises(IntegrityCheckFailedError):
        restore(backup, database)

    # The live database is untouched and still answers.
    with connect(database) as connection:
        services = build_services(connection)
        found = services.lookup.lookup(
            SymbolLookupRequest(repository_id, "PaymentService.capture", "req-2")
        )
    assert found.evidence


def test_a_failed_copy_leaves_the_live_database_where_it_was(
    tmp_path: Path, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-checks are not the only way a restore can fail.

    A corrupted backup is refused before anything moves, and the test above
    covers that. This covers the other half: the backup passes every check and
    the *copy* then fails — a full disk, a revoked handle, a sharing violation.
    Until this was fixed the live database had already been renamed to
    `.replaced` by then, so the failure left nothing at the expected path at
    all and the user had to know to go looking for a file they were never told
    about.
    """
    database = tmp_path / "db.sqlite"
    repository_id = _populate(database, sample_repo)
    backup = tmp_path / "atlas.sqlite"
    create_backup(database, backup)

    real_opened = backup_module._opened

    def fail_on_staging(path: Path, *, read_only: bool = False):  # type: ignore[no-untyped-def]
        if path.name.endswith(".incoming"):
            raise sqlite3.OperationalError("disk I/O error")
        return real_opened(path, read_only=read_only)

    monkeypatch.setattr(backup_module, "_opened", fail_on_staging)

    with pytest.raises(RestoreIncompatibleError):
        restore(backup, database)

    assert database.is_file(), "the live database was moved away and not put back"
    assert not database.with_name(f"{database.name}.incoming").exists()
    with connect(database) as connection:
        services = build_services(connection)
        found = services.lookup.lookup(
            SymbolLookupRequest(repository_id, "PaymentService.capture", "req-3")
        )
    assert found.evidence


def test_a_failed_final_swap_puts_the_preserved_database_back(
    tmp_path: Path, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The narrowest window: the copy succeeded, the swap did not.

    Something has to be moved for a restore to happen, so this window cannot be
    eliminated — but it can be rolled back, and a user left with no database is
    not "exactly where they started".
    """
    database = tmp_path / "db.sqlite"
    repository_id = _populate(database, sample_repo)
    backup = tmp_path / "atlas.sqlite"
    create_backup(database, backup)

    real_replace = os.replace

    def fail_the_swap(src, dst):  # type: ignore[no-untyped-def]
        if str(src).endswith(".incoming"):
            raise OSError("sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_the_swap)

    with pytest.raises(RestoreIncompatibleError):
        restore(backup, database)

    assert database.is_file(), "the preserved database was not rolled back"
    with connect(database) as connection:
        services = build_services(connection)
        found = services.lookup.lookup(
            SymbolLookupRequest(repository_id, "PaymentService.capture", "req-4")
        )
    assert found.evidence


def test_restore_refuses_a_missing_backup(tmp_path: Path, sample_repo: Path) -> None:
    database = tmp_path / "db.sqlite"
    _populate(database, sample_repo)

    with pytest.raises(RestoreIncompatibleError):
        restore(tmp_path / "absent.sqlite", database)


def test_restore_into_a_fresh_location_needs_no_prior_database(
    tmp_path: Path, sample_repo: Path
) -> None:
    """First run after reinstalling: there is nothing to replace."""
    database = tmp_path / "db.sqlite"
    _populate(database, sample_repo)
    backup = tmp_path / "atlas.sqlite"
    create_backup(database, backup)

    target = tmp_path / "fresh" / "db.sqlite"
    result = restore(backup, target)

    assert target.exists()
    assert result.replaced_path is None
    check_integrity(target)


def test_a_restored_database_is_usable_end_to_end(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _populate(database, sample_repo)
    backup = tmp_path / "atlas.sqlite"
    create_backup(database, backup)
    target = tmp_path / "restored" / "db.sqlite"

    restore(backup, target)

    with connect(target) as connection:
        services = build_services(connection)
        found = services.lookup.lookup(
            SymbolLookupRequest(repository_id, "IdempotencyStore.claim", "req-3")
        )
        assert found.evidence
        # And it still accepts writes, which a read-only-looking copy would not.
        services.indexing.index(repository_id)


def test_restore_leaves_no_wal_side_files_from_the_replaced_database(
    tmp_path: Path, sample_repo: Path
) -> None:
    """A stale -wal beside a restored database can resurrect replaced pages."""
    database = tmp_path / "db.sqlite"
    _populate(database, sample_repo)
    backup = tmp_path / "atlas.sqlite"
    create_backup(database, backup)

    restore(backup, database)

    assert not (tmp_path / "db.sqlite-wal").exists()
    assert not (tmp_path / "db.sqlite-shm").exists()


def test_restore_refuses_while_the_database_is_in_use(
    tmp_path: Path, sample_repo: Path
) -> None:
    """Restore is offline by decision: swapping the file under a serving API is
    how a database gets silently corrupted (the answer to P6-05 question 1)."""
    database = tmp_path / "db.sqlite"
    _populate(database, sample_repo)
    backup = tmp_path / "atlas.sqlite"
    create_backup(database, backup)

    holder = sqlite3.connect(database)
    try:
        holder.execute("BEGIN EXCLUSIVE")
        with pytest.raises(RestoreIncompatibleError):
            restore(backup, database)
    finally:
        holder.close()
