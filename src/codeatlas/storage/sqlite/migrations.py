"""Explicit forward-only SQL migrations.

ADR-0002 chose numbered ``.sql`` files over Alembic: Phase 1 has one local
database, one writer, and no ORM, so autogenerate would be unused while the
review surface would grow. Migrations are applied in ascending numeric order and
recorded in ``schema_migrations``, which makes re-running a no-op and makes the
applied version verifiable rather than inferred.

Never edit an applied migration. Add a new numbered file instead.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files

from codeatlas.domain.errors import SchemaVersionUnsupportedError
from codeatlas.storage.sqlite.connection import to_utc_text

SCHEMA_VERSION: int = 12

_MIGRATION_PACKAGE = "codeatlas.storage.sqlite"
_MIGRATION_DIRECTORY = "migrations"
_MIGRATION_PATTERN = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class _Migration:
    version: int
    name: str
    statements: str


def current_version(connection: sqlite3.Connection) -> int:
    """Return the highest applied migration version, or 0 if none."""
    connection.execute(_CREATE_MIGRATIONS_TABLE)
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    highest = row[0] if row is not None else None
    return int(highest) if highest is not None else 0


def pending_versions(applied: int) -> tuple[int, ...]:
    """Return the migration versions that would run against ``applied``."""
    return tuple(
        migration.version
        for migration in _load_migrations()
        if migration.version > applied
    )


def apply_migrations(connection: sqlite3.Connection) -> int:
    """Apply every pending migration and return the resulting version.

    Refuses a database recorded at a *higher* version than this build knows.
    The guard lives here rather than only in the upgrade path so that no call
    site can bypass it by opening a connection and migrating directly: a build
    that quietly serves a schema it has never seen would answer plausibly and
    write into columns whose meaning had changed.
    """
    applied = current_version(connection)
    if applied > SCHEMA_VERSION:
        raise SchemaVersionUnsupportedError(
            "This database was written by a newer version of CodeAtlas.",
            details={
                "found_version": str(applied),
                "supported_version": str(SCHEMA_VERSION),
            },
        )

    for migration in _load_migrations():
        if migration.version <= applied:
            continue
        _apply_one(connection, migration)
        applied = migration.version
    return applied


def _apply_one(connection: sqlite3.Connection, migration: _Migration) -> None:
    # Statements are executed one at a time rather than through
    # `executescript`, which implicitly commits any pending transaction and
    # would therefore leave a failed migration half applied.
    connection.execute("BEGIN IMMEDIATE")
    try:
        for statement in _split_statements(migration.statements):
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (migration.version, to_utc_text(datetime.now(UTC))),
        )
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def _split_statements(script: str) -> tuple[str, ...]:
    """Split a migration script into complete SQL statements.

    Uses SQLite's own completeness check, so a semicolon inside a string literal
    or a trigger body does not split a statement.
    """
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""

    remainder = buffer.strip()
    if remainder:
        raise RuntimeError("migration ends with an incomplete SQL statement")
    return tuple(statements)


def _load_migrations() -> tuple[_Migration, ...]:
    directory = files(_MIGRATION_PACKAGE) / _MIGRATION_DIRECTORY
    migrations: list[_Migration] = []
    for entry in directory.iterdir():
        match = _MIGRATION_PATTERN.match(entry.name)
        if match is None:
            continue
        migrations.append(
            _Migration(
                version=int(match.group(1)),
                name=entry.name,
                statements=entry.read_text(encoding="utf-8"),
            )
        )

    migrations.sort(key=lambda migration: migration.version)
    versions = [migration.version for migration in migrations]
    if len(set(versions)) != len(versions):
        raise RuntimeError("duplicate migration versions are not allowed")
    return tuple(migrations)
