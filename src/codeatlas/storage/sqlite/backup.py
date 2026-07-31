"""Backup, integrity validation, and restore for the local database.

A backup a user believes in but cannot restore from is worse than no backup,
because it displaces the caution they would otherwise have. Everything here is
shaped by that: a backup is verified before it is called one, and a restore that
cannot succeed refuses **before** it has replaced anything (ADR-0007 decision 4).

Three rules earn their keep.

* **Copy through SQLite, never through the filesystem.** In WAL mode recent
  commits may still live in the ``-wal`` side file, so copying the main file
  alone can miss them or capture a torn page. The online backup API takes a
  consistent copy of an open database; `shutil.copy` does not.
* **Validate, then replace.** Schema version and integrity are checked against
  the *backup* first. A restore that fails must leave the user exactly where
  they started, not halfway.
* **Restore is offline.** Swapping the file underneath a serving API is a
  well-known way to corrupt a database, so restore refuses when the target is
  locked and asks the user to start CodeAtlas afterwards.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from codeatlas.domain.errors import (
    BackupFailedError,
    IntegrityCheckFailedError,
    RestoreIncompatibleError,
)
from codeatlas.storage.sqlite.migrations import SCHEMA_VERSION

# `integrity_check` walks every page; `quick_check` skips the most expensive
# cross-checks. The full check is the right default here because it runs once
# per backup or restore, not per query, and its whole purpose is to be believed.
_INTEGRITY_PRAGMA = "PRAGMA integrity_check"
_INTEGRITY_OK = "ok"

# WAL side files belong to the database they were written beside. Leaving one
# next to a restored file can resurrect pages the restore just replaced.
_SIDE_FILE_SUFFIXES = ("-wal", "-shm")


@contextmanager
def _opened(database: Path, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Open a connection that is actually closed afterwards.

    `with sqlite3.connect(...)` manages the *transaction*, not the connection —
    the file stays open. On Windows an open handle makes the file unmovable, so
    every `os.replace` here would fail with a sharing violation. This is the
    difference between the two, made explicit.
    """
    target = f"file:{database}?mode=ro" if read_only else str(database)
    connection = sqlite3.connect(target, uri=read_only, timeout=0 if read_only else 5)
    try:
        yield connection
    finally:
        connection.close()


@dataclass(frozen=True)
class BackupResult:
    """A completed, verified backup."""

    path: Path
    schema_version: int
    size_bytes: int


@dataclass(frozen=True)
class RestoreResult:
    """A completed restore, and where the replaced database was kept."""

    path: Path
    schema_version: int
    replaced_path: Path | None


def create_backup(source: Path, destination: Path) -> BackupResult:
    """Copy an open database to ``destination`` and verify the result.

    The copy is written to a temporary file beside the destination and moved
    into place only once it has passed its integrity check, so a failure can
    never leave a half-written file that someone later trusts — or destroy the
    previous backup at the same path.
    """
    if not source.is_file():
        raise BackupFailedError("The database to back up does not exist.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f"{destination.name}.partial")
    _remove_quietly(staging)

    try:
        with _opened(source) as origin, _opened(staging) as copy:
            origin.backup(copy)
    except sqlite3.Error as error:
        _remove_quietly(staging)
        raise BackupFailedError("The database could not be backed up.") from error

    try:
        check_integrity(staging)
        version = read_schema_version(staging)
    except (IntegrityCheckFailedError, sqlite3.Error) as error:
        _remove_quietly(staging)
        raise BackupFailedError(
            "The backup was written but did not pass its integrity check."
        ) from error

    # `os.replace` is atomic on Windows and POSIX alike, so the destination is
    # either the old backup or the new one — never a mixture.
    os.replace(staging, destination)
    return BackupResult(
        path=destination,
        schema_version=version,
        size_bytes=destination.stat().st_size,
    )


def check_integrity(database: Path) -> None:
    """Raise unless SQLite reports the database as structurally sound."""
    if not database.is_file():
        raise IntegrityCheckFailedError("The database file does not exist.")

    try:
        with _opened(database, read_only=True) as connection:
            rows = connection.execute(_INTEGRITY_PRAGMA).fetchall()
    except sqlite3.DatabaseError as error:
        # Includes "file is not a database": an unreadable file is a failed
        # check rather than a crash, because the caller asked a yes/no question.
        raise IntegrityCheckFailedError(
            "The file could not be read as a database."
        ) from error

    if [row[0] for row in rows] != [_INTEGRITY_OK]:
        raise IntegrityCheckFailedError("The database failed its integrity check.")


def read_schema_version(database: Path) -> int:
    """Return the highest migration version recorded in the database.

    The database is self-describing, which is why a backup needs no sidecar
    manifest: there is no second copy of the version to drift out of step.
    """
    with _opened(database, read_only=True) as connection:
        row = connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()
    return int(row[0]) if row is not None and row[0] is not None else 0


def restore(backup: Path, target: Path) -> RestoreResult:
    """Replace ``target`` with ``backup``, refusing rather than half-restoring.

    Every check happens before anything is written. The database being replaced
    is preserved beside the target, because restore is the most destructive
    operation the product has and a user who restores the wrong file needs a way
    back (`CLAUDE.md` Section 15).
    """
    if not backup.is_file():
        raise RestoreIncompatibleError("The backup file does not exist.")

    check_integrity(backup)

    version = read_schema_version(backup)
    if version > SCHEMA_VERSION:
        raise RestoreIncompatibleError(
            "That backup was written by a newer version of CodeAtlas."
        )

    _require_not_in_use(target)

    target.parent.mkdir(parents=True, exist_ok=True)

    # Build the replacement completely before disturbing what is already
    # there. The earlier order preserved the target first, so a copy that
    # failed — a full disk, a revoked handle, a sharing violation — left
    # nothing at the expected path and only a `.replaced` file the user had no
    # reason to know about. Staging first means every failure below this point
    # either changes nothing or is rolled back.
    staging = target.with_name(f"{target.name}.incoming")
    _remove_quietly(staging)
    try:
        with _opened(backup) as origin, _opened(staging) as copy:
            origin.backup(copy)
    except (sqlite3.Error, OSError) as error:
        _remove_quietly(staging)
        raise RestoreIncompatibleError("The backup could not be restored.") from error

    # Something must move for a restore to happen, so this window cannot be
    # removed — only made recoverable.
    replaced = _preserve_replaced(target)
    try:
        os.replace(staging, target)
    except (sqlite3.Error, OSError) as error:
        _remove_quietly(staging)
        if replaced is not None:
            # Put the user back where they started rather than leaving them
            # with no database at all.
            try:
                os.replace(replaced, target)
            except OSError:  # pragma: no cover - the rollback itself failing
                raise RestoreIncompatibleError(
                    "The backup could not be restored, and the database it "
                    f"replaced is at {replaced}.",
                ) from error
        raise RestoreIncompatibleError("The backup could not be restored.") from error

    # The restored file is a fresh copy, so any side files still beside the
    # target belong to the database that was just replaced.
    for suffix in _SIDE_FILE_SUFFIXES:
        _remove_quietly(target.with_name(f"{target.name}{suffix}"))

    return RestoreResult(path=target, schema_version=version, replaced_path=replaced)


def _require_not_in_use(target: Path) -> None:
    """Refuse when another process holds the database.

    Restore is offline by decision. Detection is best-effort — a lock can be
    taken the moment after this returns — but it catches the common mistake of
    restoring while the API is running, which is the one that silently corrupts.
    """
    if not target.is_file():
        return

    try:
        with _opened(target) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("ROLLBACK")
    except sqlite3.OperationalError as error:
        raise RestoreIncompatibleError(
            "The database is in use. Stop CodeAtlas and try again."
        ) from error


def _preserve_replaced(target: Path) -> Path | None:
    """Keep the database about to be overwritten, if there is one."""
    if not target.is_file():
        return None

    kept = target.with_name(f"{target.name}.replaced")
    _remove_quietly(kept)
    os.replace(target, kept)
    return kept


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
