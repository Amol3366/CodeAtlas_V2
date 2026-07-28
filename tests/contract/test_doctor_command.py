"""`codeatlas doctor` — one place that says what is wrong and what is not.

Blueprint section 6.2 lists `doctor` among the required MVP commands. It lands
with P6-04 because the thing it most needs to report is what recovery found:
a repository whose last index was interrupted, or one whose indexing is blocked
by a run nobody owns.

The command answers the product's fifth question — "what does CodeAtlas not
know?" — for the installation rather than for a query.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.cli.main import EXIT_PARTIAL, EXIT_SUCCESS, app
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

runner = CliRunner()


def _prepare(database: Path, root: Path, *, index: bool = True) -> str:
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        if index:
            services.indexing.index(repository.repository_id)
        return repository.repository_id


def _strand(database: Path, repository_id: str) -> None:
    """Leave the state a killed process leaves: an open, unowned job."""
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with connect(database) as connection:
        connection.execute(
            "INSERT INTO index_jobs (job_id, repository_id, snapshot_id, stage,"
            " status, attempts, started_at, updated_at, diagnostics)"
            " VALUES ('job_stranded', ?, 'snap_stranded', 'parsing', 'running',"
            " 1, ?, ?, '[]')",
            (repository_id, now, now),
        )
        connection.commit()


def _run(database: Path, *arguments: str) -> tuple[int, str]:
    result = runner.invoke(app, ["doctor", "--db", str(database), *arguments])
    return result.exit_code, result.stdout


def test_doctor_reports_a_healthy_repository(tmp_path: Path, sample_repo: Path) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)

    code, output = _run(database, "--json")

    assert code == EXIT_SUCCESS
    payload = json.loads(output)
    entry = next(
        item
        for item in payload["repositories"]
        if item["repository_id"] == repository_id
    )
    assert entry["active_snapshot_id"] is not None
    assert entry["interrupted_run"] is None
    assert entry["problems"] == []
    assert payload["healthy"] is True


def test_doctor_reports_a_never_indexed_repository_as_a_problem(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    _prepare(database, sample_repo, index=False)

    code, output = _run(database, "--json")

    assert code == EXIT_PARTIAL
    payload = json.loads(output)
    entry = payload["repositories"][0]
    assert entry["active_snapshot_id"] is None
    assert "NEVER_INDEXED" in entry["problems"]


def test_doctor_distinguishes_interrupted_from_never_indexed(
    tmp_path: Path, sample_repo: Path
) -> None:
    """The distinction ADR-0007 decision 3 exists for."""
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)
    _strand(database, repository_id)

    code, output = _run(database, "--json")

    assert code == EXIT_PARTIAL
    entry = json.loads(output)["repositories"][0]
    assert "INDEX_RUN_INTERRUPTED" in entry["problems"]
    assert "NEVER_INDEXED" not in entry["problems"]
    assert entry["interrupted_run"]["stage"] == "parsing"


def test_doctor_names_a_run_that_is_blocking_indexing(
    tmp_path: Path, sample_repo: Path, monkeypatch: object
) -> None:
    """A live-looking owner is the one case recovery deliberately leaves.

    It is also the case a user cannot diagnose without help: indexing simply
    refuses, with nothing on screen to say why. `doctor` names the run and the
    process it belongs to.
    """
    import os

    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with connect(database) as connection:
        connection.execute(
            "INSERT INTO index_jobs (job_id, repository_id, snapshot_id, stage,"
            " status, attempts, started_at, updated_at, diagnostics)"
            " VALUES ('job_owned', ?, 'snap_owned', 'parsing', 'running', 1,"
            " ?, ?, ?)",
            (
                repository_id,
                now,
                now,
                json.dumps({"owner": {"pid": os.getpid(), "token": "other"}}),
            ),
        )
        connection.commit()

    code, output = _run(database, "--json")

    assert code == EXIT_PARTIAL
    entry = json.loads(output)["repositories"][0]
    assert "INDEX_RUN_IN_PROGRESS" in entry["problems"]
    blocking = entry["open_jobs"][0]
    assert blocking["job_id"] == "job_owned"
    assert blocking["owner_pid"] == os.getpid()


def _second_repository(tmp_path: Path) -> Path:
    root = tmp_path / "other_repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def run() -> int:\n    return 1\n", "utf-8")
    return root


def test_doctor_covers_every_repository_when_none_is_named(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    first = _prepare(database, sample_repo)
    second = _prepare(database, _second_repository(tmp_path), index=False)

    _, output = _run(database, "--json")

    reported = {item["repository_id"] for item in json.loads(output)["repositories"]}
    assert reported == {first, second}


def test_doctor_can_be_narrowed_to_one_repository(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    first = _prepare(database, sample_repo)
    _prepare(database, _second_repository(tmp_path), index=False)

    code, output = _run(database, first, "--json")

    payload = json.loads(output)
    assert [item["repository_id"] for item in payload["repositories"]] == [first]
    # The unhealthy repository was not asked about, so it does not change the
    # verdict for the one that was.
    assert code == EXIT_SUCCESS


def test_doctor_prints_human_readable_output_by_default(
    tmp_path: Path, sample_repo: Path
) -> None:
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)

    _, output = _run(database)

    assert repository_id in output
    assert output.strip().startswith("CodeAtlas doctor")


def test_doctor_reports_an_empty_installation_without_failing(
    tmp_path: Path,
) -> None:
    """No repositories is a fact, not a fault."""
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)

    code, output = _run(database, "--json")

    assert code == EXIT_SUCCESS
    assert json.loads(output)["repositories"] == []


def test_doctor_does_not_leak_the_absolute_root_into_json(
    tmp_path: Path, sample_repo: Path
) -> None:
    """The CLI is local, but its JSON is what gets pasted into an issue.

    A display name is enough to identify a repository; the absolute path is
    the part that carries a username.
    """
    database = tmp_path / "db.sqlite"
    _prepare(database, sample_repo)

    _, output = _run(database, "--json")

    assert str(sample_repo) not in output


def test_doctor_survives_a_repository_whose_root_has_vanished(
    tmp_path: Path, sample_repo: Path
) -> None:
    """Diagnosis must not need the thing being diagnosed to be healthy."""
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)
    with connect(database) as connection:
        connection.execute(
            "UPDATE repositories SET canonical_root = ? WHERE repository_id = ?",
            (str(tmp_path / "gone"), repository_id),
        )
        connection.commit()

    code, output = _run(database, "--json")

    assert code == EXIT_PARTIAL
    entry = json.loads(output)["repositories"][0]
    assert "ROOT_MISSING" in entry["problems"]


def test_doctor_leaves_the_database_unchanged_apart_from_recovery(
    tmp_path: Path, sample_repo: Path
) -> None:
    """`doctor` diagnoses. The only writes are the recovery every command does."""
    database = tmp_path / "db.sqlite"
    repository_id = _prepare(database, sample_repo)

    def snapshot_rows() -> list[tuple[object, ...]]:
        with connect(database) as connection:
            connection.row_factory = sqlite3.Row
            return [
                tuple(row)
                for row in connection.execute(
                    "SELECT snapshot_id, state FROM snapshots ORDER BY snapshot_id"
                )
            ]

    before = snapshot_rows()
    _run(database, repository_id, "--json")

    assert snapshot_rows() == before
