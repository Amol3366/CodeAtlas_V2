"""`codeatlas upgrade`, and the implicit upgrade every other command performs.

Both paths exist on purpose (P6-07). Opening a database still migrates it, so a
packaged upgrade simply works when the user double-clicks the new build; the
explicit command exists so that an upgrade of years of history can be inspected
and has a record — version from, version to, and where the checkpoint went.

They share one implementation. A second code path that migrates would be a
second set of rules about when to checkpoint.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from codeatlas.cli.main import (
    EXIT_SUCCESS,
    EXIT_UNAVAILABLE,
    app,
)
from codeatlas.storage.sqlite.backup import read_schema_version
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import SCHEMA_VERSION, apply_migrations

runner = CliRunner()

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "upgrade" / "schema_0008.db"
)


def _expected_pending() -> list[int]:
    """Every schema version the fixture still has to cross to reach this build.

    Derived, not written out: the fixture is a real older artifact and stays
    put, so the list grows with each migration. Since 0010 it has more than one
    entry, which is the multi-step upgrade a literal would have stopped
    covering.
    """
    return list(range(read_schema_version(_FIXTURE) + 1, SCHEMA_VERSION + 1))


def _run(*arguments: str) -> tuple[int, str]:
    """Return the exit code and everything the command printed.

    Refusals are written to stderr, so a helper that returned stdout alone
    would make an error message untestable — and the message is the point of
    refusing rather than failing.
    """
    result = runner.invoke(app, list(arguments))
    return result.exit_code, result.stdout + result.stderr


def _prior(tmp_path: Path) -> Path:
    target = tmp_path / "codeatlas.db"
    shutil.copy2(_FIXTURE, target)
    return target


def _from_the_future(tmp_path: Path) -> Path:
    database = tmp_path / "future.db"
    with connect(database) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION + 1, "2030-01-01T00:00:00Z"),
        )
    return database


# --- the explicit command -------------------------------------------------


def test_upgrade_reports_the_versions_and_the_checkpoint(tmp_path: Path) -> None:
    database = _prior(tmp_path)

    code, output = _run("upgrade", "--db", str(database), "--json")

    assert code == EXIT_SUCCESS
    payload = json.loads(output)
    assert payload["upgraded"] is True
    assert payload["from_version"] == 8
    assert payload["to_version"] == SCHEMA_VERSION
    assert payload["applied"] == _expected_pending()
    assert Path(payload["checkpoint_path"]).is_file()
    assert payload["counts"]["conversations"] == 3


def test_upgrade_names_the_checkpoint_in_its_human_output(tmp_path: Path) -> None:
    """A user who needs the checkpoint needs it after something went wrong.
    Printing the path is how they find it without knowing the naming rule."""
    database = _prior(tmp_path)

    code, output = _run("upgrade", "--db", str(database))

    assert code == EXIT_SUCCESS
    assert "pre-upgrade-v8" in output
    assert f"{SCHEMA_VERSION}" in output


def test_upgrade_of_a_current_database_says_so(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)

    code, output = _run("upgrade", "--db", str(database), "--json")

    assert code == EXIT_SUCCESS
    payload = json.loads(output)
    assert payload["upgraded"] is False
    assert payload["applied"] == []
    assert payload["checkpoint_path"] is None


def test_upgrade_refuses_a_database_from_a_newer_build(tmp_path: Path) -> None:
    database = _from_the_future(tmp_path)

    code, output = _run("upgrade", "--db", str(database), "--json")

    assert code == EXIT_UNAVAILABLE
    assert "SCHEMA_VERSION_UNSUPPORTED" in output


# --- the implicit upgrade -------------------------------------------------


def test_an_ordinary_command_upgrades_the_database(tmp_path: Path) -> None:
    """The packaged case: the user runs the new build and it just works."""
    database = _prior(tmp_path)

    code, output = _run("repo", "list", "--db", str(database), "--json")

    assert code == EXIT_SUCCESS
    assert len(json.loads(output)) == 1
    assert read_schema_version(database) == SCHEMA_VERSION


def test_an_ordinary_command_checkpoints_before_upgrading(tmp_path: Path) -> None:
    database = _prior(tmp_path)

    _run("repo", "list", "--db", str(database), "--json")

    assert list(tmp_path.glob("*.pre-upgrade-v8")), "no checkpoint was written"


def test_an_ordinary_command_refuses_a_database_from_a_newer_build(
    tmp_path: Path,
) -> None:
    """Silently running against a schema this build has never seen is exactly
    the silent corruption ADR-0007 exists to prevent."""
    database = _from_the_future(tmp_path)

    code, output = _run("repo", "list", "--db", str(database), "--json")

    assert code == EXIT_UNAVAILABLE
    assert "SCHEMA_VERSION_UNSUPPORTED" in output


# --- doctor ---------------------------------------------------------------


def test_doctor_reports_the_schema_it_found(tmp_path: Path) -> None:
    """Doctor plans before it opens, so it reports the version it *found* — and
    says that opening the database is what moved it."""
    database = _prior(tmp_path)

    code, output = _run("doctor", "--db", str(database), "--json")

    payload = json.loads(output)
    assert payload["schema"]["found_version"] == 8
    assert payload["schema"]["expected_version"] == SCHEMA_VERSION
    assert payload["schema"]["pending"] == _expected_pending()
    assert code in (EXIT_SUCCESS, 4)  # the fixture's repository root is long gone


def test_doctor_on_a_current_database_reports_nothing_pending(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)

    code, output = _run("doctor", "--db", str(database), "--json")

    assert code == EXIT_SUCCESS
    payload = json.loads(output)
    assert payload["schema"]["pending"] == []
    assert payload["schema"]["found_version"] == SCHEMA_VERSION
