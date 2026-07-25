"""SQLite connection management for the local single-writer database.

Pragmas are applied per connection because SQLite scopes most of them that way.
``journal_mode`` is the exception — it persists in the database file — but
setting it every time is harmless and keeps a freshly created file correct.

Timestamps are stored as ISO-8601 UTC text with a ``Z`` suffix so that ordering
is lexicographic and no local timezone can leak into stored truth.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

_BUSY_TIMEOUT_MILLISECONDS = 5000
_DEFAULT_DIRECTORY = Path("CodeAtlas") / "data"
_DEFAULT_FILENAME = "codeatlas.db"


def default_database_path() -> Path:
    """Return the configured database path.

    ``CODEATLAS_DB_PATH`` wins so that tests and alternate profiles never touch
    the user's real database. Otherwise the file lives under the local
    application data directory, deliberately outside any indexed repository.
    """
    override = os.environ.get("CODEATLAS_DB_PATH")
    if override:
        return Path(override)

    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / _DEFAULT_DIRECTORY / _DEFAULT_FILENAME


@contextmanager
def connect(database_path: Path) -> Iterator[sqlite3.Connection]:
    """Open a configured connection, creating parent directories as needed."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        database_path,
        timeout=_BUSY_TIMEOUT_MILLISECONDS / 1000,
        isolation_level=None,
    )
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MILLISECONDS}")
        yield connection
    finally:
        connection.close()


@contextmanager
def write_transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a write transaction that commits on success and rolls back on error.

    ``BEGIN IMMEDIATE`` acquires the write lock up front so a concurrent writer
    fails fast instead of failing at commit after doing work.
    """
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def to_utc_text(moment: datetime) -> str:
    """Serialize a timezone-aware datetime as ISO-8601 UTC text."""
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def from_utc_text(value: str) -> datetime:
    """Parse ISO-8601 UTC text back into a timezone-aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
