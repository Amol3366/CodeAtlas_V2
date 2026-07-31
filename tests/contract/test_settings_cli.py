"""`codeatlas settings` and `codeatlas models`.

Section 13: the CLI wraps the same use cases as REST and produces the same
model. These tests exist mostly to keep that true — the CLI is where a
convenience shortcut is most tempting, and a CLI that could enable a
transmitting provider on terms the API refuses would be a hole in the opt-in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codeatlas.cli.main import app
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

runner = CliRunner()


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "db.sqlite"
    with connect(path) as connection:
        apply_migrations(connection)
    return path


def _register(database: Path, repo: Path) -> str:
    result = runner.invoke(
        app, ["repo", "add", str(repo), "--db", str(database), "--json"]
    )
    assert result.exit_code == 0, result.output
    return str(json.loads(result.stdout)["repository_id"])


def test_settings_show_the_default(tmp_path: Path, sample_repo: Path) -> None:
    database = _database(tmp_path)
    repository_id = _register(database, sample_repo)

    result = runner.invoke(
        app, ["settings", repository_id, "--db", str(database), "--json"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["embedding_provider"] == "none"


def test_a_provider_can_be_enabled(tmp_path: Path, sample_repo: Path) -> None:
    database = _database(tmp_path)
    repository_id = _register(database, sample_repo)

    result = runner.invoke(
        app,
        [
            "settings",
            repository_id,
            "--provider",
            "local",
            "--db",
            str(database),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["embedding_provider"] == "local"


def test_the_cli_enforces_the_same_budget_rule_as_the_api(
    tmp_path: Path, sample_repo: Path
) -> None:
    """The rule lives in the application service, so both adapters inherit it.
    A CLI that could bypass it would make the opt-in a suggestion."""
    database = _database(tmp_path)
    repository_id = _register(database, sample_repo)

    result = runner.invoke(
        app,
        ["settings", repository_id, "--provider", "openai", "--db", str(database)],
    )

    assert result.exit_code != 0
    assert "INVALID_REQUEST" in result.output


def test_an_unknown_repository_exits_non_zero(tmp_path: Path) -> None:
    database = _database(tmp_path)

    result = runner.invoke(app, ["settings", "repo_missing", "--db", str(database)])

    assert result.exit_code != 0
    assert "REPOSITORY_NOT_FOUND" in result.output


def test_models_lists_every_provider(tmp_path: Path) -> None:
    database = _database(tmp_path)

    result = runner.invoke(app, ["models", "--db", str(database), "--json"])

    assert result.exit_code == 0, result.output
    providers = {item["provider"] for item in json.loads(result.stdout)["models"]}
    assert providers == {"none", "local", "openai"}


def test_models_output_carries_no_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-" + "livekey" * 6
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    database = _database(tmp_path)

    result = runner.invoke(app, ["models", "--db", str(database), "--json"])

    assert secret not in result.output


def test_the_human_output_names_what_transmits(tmp_path: Path) -> None:
    """The one fact a person scanning the list has to see."""
    database = _database(tmp_path)

    result = runner.invoke(app, ["models", "--db", str(database)])

    assert result.exit_code == 0, result.output
    assert "transmits" in result.output.lower()
