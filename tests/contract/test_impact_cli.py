"""The `impact` and `analysis` commands.

These exist because `--format pr` once shipped advertised in `--help` and
rejected by the command's own guard: the help string and the allow-list were
two separate lists, and only one was updated. The parameterised tests below
derive from `ADVERTISED_FORMATS`, so a format added without a guard fails here
rather than in a user's terminal.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.cli.main import (
    ADVERTISED_FORMATS,
    EXIT_INVALID_INPUT,
    EXIT_RISK_THRESHOLD,
    app,
)
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


@pytest.mark.parametrize("report_format", sorted(ADVERTISED_FORMATS))
def test_every_advertised_format_is_accepted_by_impact(
    tmp_path: Path, git_repo: Path, report_format: str
) -> None:
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)

    code, output = _run(
        "impact",
        repository_id,
        "--format",
        report_format,
        "--db",
        str(database),
    )

    # Exit 4 means the analysis ran and found nothing, which is existing
    # documented behaviour and not what this test is about.
    assert code in (0, 4), output
    assert "INVALID_REQUEST" not in output


@pytest.mark.parametrize("report_format", sorted(ADVERTISED_FORMATS))
def test_every_advertised_format_is_accepted_by_analysis(
    tmp_path: Path, git_repo: Path, report_format: str
) -> None:
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)
    _run("impact", repository_id, "--format", "json", "--db", str(database))

    with connect(database) as connection:
        services = build_services(connection)
        stored = services.change_analysis.list_for_repository(repository_id)
    assert stored, "the impact run stored no analysis to read back"

    code, output = _run(
        "analysis", stored[0], "--format", report_format, "--db", str(database)
    )

    assert code == 0, output


def test_an_unknown_format_is_refused(tmp_path: Path, git_repo: Path) -> None:
    # A typo must fail loudly, not quietly select a default.
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)

    code, _ = _run(
        "impact", repository_id, "--format", "prr", "--db", str(database)
    )

    # The exit code is the contract. The message goes to stderr, which this
    # runner keeps separate from stdout, and the suite's convention throughout
    # is to assert the code rather than the wording.
    assert code == EXIT_INVALID_INPUT


def test_a_bare_impact_prints_the_terminal_rendering(
    tmp_path: Path, git_repo: Path
) -> None:
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)

    _, output = _run("impact", repository_id, "--db", str(database))

    assert "risk ·" in output
    assert "# Change analysis" not in output


def test_markdown_is_still_available_and_unchanged(
    tmp_path: Path, git_repo: Path
) -> None:
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)

    _, output = _run(
        "impact", repository_id, "--format", "markdown", "--db", str(database)
    )

    assert "# Change analysis" in output


def test_analysis_still_defaults_to_markdown(
    tmp_path: Path, git_repo: Path
) -> None:
    # `analysis` prints a stored record, which is the archival case.
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)
    _run("impact", repository_id, "--format", "json", "--db", str(database))
    with connect(database) as connection:
        stored = build_services(connection).change_analysis.list_for_repository(
            repository_id
        )

    _, output = _run("analysis", stored[0], "--db", str(database))

    assert "# Change analysis" in output


def _change_a_public_signature(root: Path) -> None:
    """Edit the working tree so the analysis has a high-severity finding.

    A signature change on a public method is what produces
    PUBLIC_SIGNATURE_CHANGED; the fixture is committed clean, so without an
    edit there is nothing for --fail-on to act on.
    """
    service = root / "src" / "payments" / "service.py"
    service.write_text(
        service.read_text(encoding="utf-8").replace(
            "def capture(self, key: str) -> str:",
            "def capture(self, key: str, retries: int = 0) -> str:",
        ),
        encoding="utf-8",
    )


def test_fail_on_exits_seven_when_a_finding_meets_the_threshold(
    tmp_path: Path, git_repo: Path
) -> None:
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)
    _change_a_public_signature(git_repo)

    code, output = _run(
        "impact", repository_id, "--fail-on", "low", "--db", str(database)
    )

    assert code == EXIT_RISK_THRESHOLD, output


def test_fail_on_exits_zero_when_nothing_meets_the_threshold(
    tmp_path: Path, git_repo: Path
) -> None:
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)
    _change_a_public_signature(git_repo)

    code, output = _run(
        "impact", repository_id, "--fail-on", "critical", "--db", str(database)
    )

    assert code == 0, output


def test_fail_on_still_prints_the_report(tmp_path: Path, git_repo: Path) -> None:
    # A CI log showing only an exit code is not diagnosable.
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)
    _change_a_public_signature(git_repo)

    _, output = _run(
        "impact", repository_id, "--fail-on", "low", "--db", str(database)
    )

    assert "risk ·" in output


def test_an_unknown_fail_on_value_is_refused(
    tmp_path: Path, git_repo: Path
) -> None:
    # A typo in a CI config must fail loudly, not silently disable the check.
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)

    code, _ = _run(
        "impact", repository_id, "--fail-on", "sever", "--db", str(database)
    )

    assert code == EXIT_INVALID_INPUT


def test_without_fail_on_the_exit_codes_are_unchanged(
    tmp_path: Path, git_repo: Path
) -> None:
    # Exit 4 for no findings is documented existing behaviour and stays.
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)

    code, _ = _run("impact", repository_id, "--db", str(database))

    assert code in (0, 4)


def test_since_and_commits_together_are_refused(
    tmp_path: Path, git_repo: Path
) -> None:
    # A silent precedence rule would analyse a range the user did not ask for.
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)

    code, _ = _run(
        "impact",
        repository_id,
        "--since",
        "main",
        "--commits",
        "HEAD..HEAD",
        "--db",
        str(database),
    )

    assert code == EXIT_INVALID_INPUT


def test_since_analyses_from_the_merge_base(
    tmp_path: Path, git_repo: Path
) -> None:
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)

    code, output = _run(
        "impact", repository_id, "--since", "main", "--db", str(database)
    )

    assert code in (0, 4), output
    assert "risk ·" in output


def test_an_unresolvable_since_ref_is_reported(
    tmp_path: Path, git_repo: Path
) -> None:
    database = tmp_path / "cli.sqlite"
    repository_id = _prepare(database, git_repo)

    code, _ = _run(
        "impact", repository_id, "--since", "no-such-branch", "--db", str(database)
    )

    # GIT_REF_UNRESOLVABLE maps through the existing error table; the point is
    # that it is reported rather than crashing.
    assert code != 0
