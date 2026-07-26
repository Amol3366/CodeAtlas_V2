"""Explicit forward migrations against real SQLite."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import (
    SCHEMA_VERSION,
    apply_migrations,
    current_version,
)


def test_migrations_are_idempotent_and_record_version(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        assert apply_migrations(connection) == SCHEMA_VERSION
        assert apply_migrations(connection) == SCHEMA_VERSION
        assert current_version(connection) == SCHEMA_VERSION


def test_version_is_zero_before_any_migration(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        assert current_version(connection) == 0


def test_pragmas_are_applied(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal_mode.lower() == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_connect_creates_missing_parent_directories(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "deeper" / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)
    assert database_path.exists()


def test_expected_tables_exist(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
    names = {row[0] for row in rows}
    assert {
        "schema_migrations",
        "repositories",
        "snapshots",
        "files",
        "symbols",
        "index_jobs",
    } <= names


def test_schema_version_is_four() -> None:
    assert SCHEMA_VERSION == 4


def test_chunk_tables_and_fts_projections_exist(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        rows = connection.execute(
            "SELECT name, type FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    names = {row[0] for row in rows}
    assert {"chunks", "snapshot_chunk_membership", "chunk_search", "file_search"} <= (
        names
    )


def _apply_only_version_one(connection: sqlite3.Connection) -> None:
    """Bring a database to schema version 1 exactly, as a pre-Phase-2 install."""
    from codeatlas.storage.sqlite.migrations import _apply_one, _load_migrations

    current_version(connection)  # creates the bookkeeping table
    for migration in _load_migrations():
        if migration.version == 1:
            _apply_one(connection, migration)


def test_upgrading_an_existing_version_1_database_preserves_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        _apply_only_version_one(connection)
        assert current_version(connection) == 1
        _insert_repository(connection, "repo_1")
        _insert_snapshot(connection, "snap_1", "repo_1", "active")

    with connect(database) as connection:
        assert apply_migrations(connection) == SCHEMA_VERSION
        repositories = connection.execute(
            "SELECT COUNT(*) FROM repositories"
        ).fetchone()[0]
        snapshots = connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    assert repositories == 1
    assert snapshots == 1
    assert chunks == 0


def _insert_chunk(
    connection: sqlite3.Connection,
    snapshot_id: str,
    logical_chunk_id: str,
    file_id: str = "file_1",
) -> None:
    connection.execute(
        "INSERT INTO chunks ("
        " snapshot_id, logical_chunk_id, chunk_version_id, file_id, symbol_id,"
        " role, qualified_name, heading_path, start_line, end_line, content_hash,"
        " retrieval_text, part_index, part_count"
        ") VALUES (?, ?, 'chunkv_1', ?, NULL, 'symbol', 'A', '', 1, 2, 'hash',"
        " 'text', 0, 1)",
        (snapshot_id, logical_chunk_id, file_id),
    )
    connection.execute(
        "INSERT INTO snapshot_chunk_membership ("
        " snapshot_id, logical_chunk_id, chunk_version_id, part_index"
        ") VALUES (?, ?, 'chunkv_1', 0)",
        (snapshot_id, logical_chunk_id),
    )


def test_deleting_a_snapshot_cascades_to_chunks_and_membership(
    tmp_path: Path,
) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        _insert_repository(connection, "repo_1")
        _insert_snapshot(connection, "snap_1", "repo_1", "active")
        connection.execute(
            "INSERT INTO files ("
            " snapshot_id, file_id, relative_path, display_path, content_hash,"
            " size_bytes, line_count, language, classification"
            ") VALUES ('snap_1', 'file_1', 'a.py', 'a.py', 'hash', 1, 1,"
            " 'python', 'source_code')"
        )
        _insert_chunk(connection, "snap_1", "chunk_1")

        connection.execute("DELETE FROM snapshots WHERE snapshot_id = 'snap_1'")

        assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
        remaining_membership = connection.execute(
            "SELECT COUNT(*) FROM snapshot_chunk_membership"
        ).fetchone()[0]
        assert remaining_membership == 0


def test_a_chunk_requires_a_file_in_the_same_snapshot(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        _insert_repository(connection, "repo_1")
        _insert_snapshot(connection, "snap_1", "repo_1", "active")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_chunk(connection, "snap_1", "chunk_1", file_id="missing_file")


def _insert_repository(connection: sqlite3.Connection, repository_id: str) -> None:
    connection.execute(
        "INSERT INTO repositories"
        " (repository_id, display_name, canonical_root, created_at)"
        " VALUES (?, ?, ?, ?)",
        (repository_id, "demo", f"C:/repos/{repository_id}", "2026-07-25T00:00:00Z"),
    )


def _insert_snapshot(
    connection: sqlite3.Connection,
    snapshot_id: str,
    repository_id: str,
    state: str,
) -> None:
    connection.execute(
        "INSERT INTO snapshots ("
        " snapshot_id, repository_id, state, git_head, git_branch, git_dirty,"
        " working_tree_fingerprint, file_count, parsed_file_count,"
        " skipped_file_count, parse_error_count, parser_bundle_version,"
        " index_version, created_at, activated_at"
        ") VALUES (?, ?, ?, NULL, NULL, 0, ?, 0, 0, 0, 0, '1.0.0', '1.0.0', ?, NULL)",
        (snapshot_id, repository_id, state, "fingerprint", "2026-07-25T00:00:00Z"),
    )


def test_only_one_active_snapshot_per_repository_is_allowed(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        _insert_repository(connection, "repo_1")
        _insert_snapshot(connection, "snap_1", "repo_1", "active")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_snapshot(connection, "snap_2", "repo_1", "active")


def test_two_repositories_may_each_have_an_active_snapshot(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        _insert_repository(connection, "repo_1")
        _insert_repository(connection, "repo_2")
        _insert_snapshot(connection, "snap_1", "repo_1", "active")
        _insert_snapshot(connection, "snap_2", "repo_2", "active")
        count = connection.execute(
            "SELECT COUNT(*) FROM snapshots WHERE state = 'active'"
        ).fetchone()[0]
    assert count == 2


def test_canonical_root_is_unique(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO repositories"
            " (repository_id, display_name, canonical_root, created_at)"
            " VALUES (?, ?, ?, ?)",
            ("repo_1", "demo", "C:/repos/demo", "2026-07-25T00:00:00Z"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO repositories"
                " (repository_id, display_name, canonical_root, created_at)"
                " VALUES (?, ?, ?, ?)",
                ("repo_2", "demo", "C:/repos/demo", "2026-07-25T00:00:00Z"),
            )


def test_deleting_a_repository_cascades_to_snapshots_files_and_symbols(
    tmp_path: Path,
) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        _insert_repository(connection, "repo_1")
        _insert_snapshot(connection, "snap_1", "repo_1", "active")
        connection.execute(
            "INSERT INTO files ("
            " snapshot_id, file_id, relative_path, display_path, content_hash,"
            " size_bytes, line_count, language, classification"
            ") VALUES ('snap_1', 'file_1', 'a.py', 'a.py', 'hash', 1, 1,"
            " 'python', 'source_code')"
        )
        connection.execute(
            "INSERT INTO symbols ("
            " snapshot_id, symbol_id, symbol_version_id, file_id, kind, name,"
            " qualified_name, module_path, signature, start_line, end_line,"
            " start_byte, end_byte, content_hash, visibility"
            ") VALUES ('snap_1', 'sym_1', 'symv_1', 'file_1', 'CLASS', 'A', 'A',"
            " 'a', NULL, 1, 1, 0, 1, 'hash', 'public')"
        )

        connection.execute("DELETE FROM repositories WHERE repository_id = 'repo_1'")

        assert connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0


def test_a_symbol_requires_a_file_in_the_same_snapshot(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        _insert_repository(connection, "repo_1")
        _insert_snapshot(connection, "snap_1", "repo_1", "active")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO symbols ("
                " snapshot_id, symbol_id, symbol_version_id, file_id, kind, name,"
                " qualified_name, module_path, signature, start_line, end_line,"
                " start_byte, end_byte, content_hash, visibility"
                ") VALUES ('snap_1', 'sym_1', 'symv_1', 'missing_file', 'CLASS',"
                " 'A', 'A', 'a', NULL, 1, 1, 0, 1, 'hash', 'public')"
            )


def test_write_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    from codeatlas.storage.sqlite.connection import write_transaction

    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        with pytest.raises(RuntimeError), write_transaction(connection):
            _insert_repository(connection, "repo_1")
            raise RuntimeError("boom")
        remaining = connection.execute(
            "SELECT COUNT(*) FROM repositories"
        ).fetchone()[0]
        assert remaining == 0


def test_timestamps_round_trip_as_utc(tmp_path: Path) -> None:
    from codeatlas.storage.sqlite.connection import from_utc_text, to_utc_text

    moment = datetime(2026, 7, 25, 18, 30, 15, tzinfo=UTC)
    assert from_utc_text(to_utc_text(moment)) == moment
