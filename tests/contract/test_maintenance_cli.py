"""The maintenance commands: backup, restore, repo remove, and purge.

Restore is CLI-only by decision (P6-05): swapping the database file underneath
a serving API is how a database gets silently corrupted, and `CLAUDE.md`
Section 12 specifies no endpoint for it. Backup, being non-destructive, would be
safe over HTTP but has no caller asking for it yet.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.cli.main import (
    EXIT_INTERNAL_FAILURE,
    EXIT_INVALID_INPUT,
    EXIT_SUCCESS,
    app,
)
from codeatlas.storage.sqlite.backup import check_integrity
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

runner = CliRunner()


def _prepare(database: Path, root: Path) -> str:
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        services.indexing.index(repository.repository_id)
        return repository.repository_id


def _run(*arguments: str) -> tuple[int, str]:
    result = runner.invoke(app, list(arguments))
    return result.exit_code, result.stdout


# --- backup ---------------------------------------------------------------


def test_backup_writes_a_usable_copy(tmp_path: Path, sample_repo: Path) -> None:
    database = tmp_path / "db.sqlite"
    _prepare(database, sample_repo)
    destination = tmp_path / "atlas.sqlite"

    code, output = _run("backup", str(destination), "--db", str(database), "--json")

    assert code == EXIT_SUCCESS
    payload = json.loads(output)
    assert payload["schema_version"] > 0
    check_integrity(destination)


def test_backup_of_a_missing_database_exits_with_internal_failure(
    tmp_path: Path,
) -> None:
    code, _ = _run(
        "backup",
        str(tmp_path / "out.sqlite"),
        "--db",
        str(tmp_path / "absent.sqlite"),
    )

    assert code == EXIT_INTERNAL_FAILURE


# --- restore --------------------------------------------------------------


def test_restore_replaces_the_database(tmp_path: Path, sample_repo: Path) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)
    backup = tmp_path / "atlas.sqlite"
    _run("backup", str(backup), "--db", str(database), "--json")

    code, output = _run("restore", str(backup), "--db", str(database), "--json")

    assert code == EXIT_SUCCESS
    assert json.loads(output)["restored"] is True
    with connect(database) as connection:
        found = connection.execute(
            "SELECT COUNT(*) FROM repositories WHERE repository_id = ?",
            (repository_id,),
        ).fetchone()[0]
    assert found == 1


def test_restore_tells_the_user_to_start_codeatlas_again(
    tmp_path: Path, sample_repo: Path
) -> None:
    """Restore is offline, so the next step is not obvious unless it is said."""
    database = tmp_path / "db.sqlite"
    _prepare(database, sample_repo)
    backup = tmp_path / "atlas.sqlite"
    _run("backup", str(backup), "--db", str(database))

    _, output = _run("restore", str(backup), "--db", str(database))

    assert "start" in output.lower()


def test_restore_from_a_missing_file_is_invalid_input(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    _prepare(database, sample_repo)

    code, _ = _run("restore", str(tmp_path / "absent.sqlite"), "--db", str(database))

    assert code == EXIT_INVALID_INPUT


# --- repo remove ----------------------------------------------------------


def test_repo_remove_deletes_a_repository(tmp_path: Path, sample_repo: Path) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)

    code, _ = _run("repo", "remove", repository_id, "--db", str(database))

    assert code == EXIT_SUCCESS
    with connect(database) as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM repositories"
        ).fetchone()[0]
    assert remaining == 0


def test_repo_remove_refuses_while_conversations_exist(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)
    with connect(database) as connection:
        build_services(connection).conversations.create(repository_id)

    code, _ = _run("repo", "remove", repository_id, "--db", str(database))

    assert code == EXIT_INVALID_INPUT
    with connect(database) as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM repositories"
        ).fetchone()[0]
    assert remaining == 1


def test_repo_remove_cascades_when_told_to(tmp_path: Path, sample_repo: Path) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)
    with connect(database) as connection:
        build_services(connection).conversations.create(repository_id)

    code, _ = _run(
        "repo", "remove", repository_id, "--cascade", "--db", str(database)
    )

    assert code == EXIT_SUCCESS


def test_repo_remove_leaves_the_source_files_alone(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)

    _run("repo", "remove", repository_id, "--db", str(database))

    assert (sample_repo / "src" / "payments" / "service.py").exists()


# --- purge ----------------------------------------------------------------


def test_purge_removes_conversations_deleted_past_the_window(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)
    with connect(database) as connection:
        services = build_services(connection)
        conversation = services.conversations.create(repository_id)
        services.conversations.delete(conversation.conversation_id)
        deleted = datetime.now(UTC) - timedelta(days=90)
        old = deleted.isoformat().replace("+00:00", "Z")
        connection.execute(
            "UPDATE conversations SET deleted_at = ? WHERE conversation_id = ?",
            (old, conversation.conversation_id),
        )
        connection.commit()

    code, output = _run("purge", "--db", str(database), "--json")

    assert code == EXIT_SUCCESS
    assert json.loads(output)["purged"] == 1


def test_purge_can_be_told_to_take_everything_deleted(
    tmp_path: Path, sample_repo: Path
) -> None:
    """`--older-than-days 0` is the user saying "gone now"."""
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)
    with connect(database) as connection:
        services = build_services(connection)
        conversation = services.conversations.create(repository_id)
        services.conversations.delete(conversation.conversation_id)

    code, output = _run(
        "purge", "--older-than-days", "0", "--db", str(database), "--json"
    )

    assert code == EXIT_SUCCESS
    assert json.loads(output)["purged"] == 1


def test_purge_leaves_a_recent_deletion_recoverable_by_default(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)
    with connect(database) as connection:
        services = build_services(connection)
        conversation = services.conversations.create(repository_id)
        services.conversations.delete(conversation.conversation_id)

    _, output = _run("purge", "--db", str(database), "--json")

    assert json.loads(output)["purged"] == 0


def test_purge_rejects_a_negative_window(tmp_path: Path, sample_repo: Path) -> None:
    database = tmp_path / "db.sqlite"
    _prepare(database, sample_repo)

    code, _ = _run("purge", "--older-than-days", "-1", "--db", str(database))

    assert code == EXIT_INVALID_INPUT
