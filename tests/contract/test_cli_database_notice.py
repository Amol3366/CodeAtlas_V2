"""Every CLI command says which database it opened.

The defect this closes was not a crash. `CODEATLAS_EPHEMERAL` governs `serve`
only -- every other command resolves `default_database_path()` and writes the
real database unconditionally -- so a user running with ephemeral sessions
switched on is right about the web application and wrong about the CLI, and
finds out only by discovering data that "should not exist". That is exactly how
it was found on 2026-08-09, with two repositories still registered from before
ADR-0013 existed.

Both behaviours are deliberate. The failure is that neither surface said which
file it was touching, so the notice is the fix rather than a behaviour change.

The notice goes to **stderr**, and the `--json` test below is the reason: stdout
is a machine-readable contract for every command that takes `--json`, and a
diagnostic line printed into it would break the scripted use that flag exists
for.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from codeatlas.cli.main import EXIT_SUCCESS, app

runner = CliRunner()


def _repository(root: Path) -> Path:
    source = root / "repo"
    (source / "src").mkdir(parents=True)
    (source / "src" / "module.py").write_text(
        "def greet() -> str:\n    return 'hello'\n", encoding="utf-8"
    )
    return source


def test_a_command_names_the_database_it_opened(tmp_path: Path) -> None:
    database = tmp_path / "explicit.db"

    result = runner.invoke(
        app, ["repo", "add", str(_repository(tmp_path)), "--db", str(database)]
    )

    assert result.exit_code == EXIT_SUCCESS
    assert str(database) in result.stderr


def test_the_notice_names_the_resolved_path_not_the_typed_one(
    tmp_path: Path,
) -> None:
    """A relative `--db` must be reported as the file actually opened.

    Reporting the argument back verbatim would be a restatement of the input,
    not a report of what happened, and the whole point is to tell a user which
    file on disk they are about to change.
    """
    database = tmp_path / "nested" / ".." / "resolved.db"

    result = runner.invoke(
        app, ["repo", "add", str(_repository(tmp_path)), "--db", str(database)]
    )

    assert result.exit_code == EXIT_SUCCESS
    assert str(tmp_path / "resolved.db") in result.stderr
    assert ".." not in result.stderr


def test_json_output_stays_parseable_because_the_notice_is_on_stderr(
    tmp_path: Path,
) -> None:
    """The regression this guards against is the notice landing on stdout.

    `--json` exists so a script can consume the output. A human-readable line
    prefixed to that stream would break every such caller, which is a worse
    defect than the one being fixed.
    """
    database = tmp_path / "machine.db"

    result = runner.invoke(
        app,
        [
            "repo",
            "add",
            str(_repository(tmp_path)),
            "--db",
            str(database),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["repository_id"].startswith("repo_")
    assert str(database) in result.stderr
