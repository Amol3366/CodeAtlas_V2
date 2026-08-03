"""Opening an ephemeral session on its configured repositories.

Registration and indexing are tested separately because they run at different
times for a reason: registration happens before the server binds, indexing
happens on a background thread afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.ephemeral_bootstrap import (
    index_repositories,
    register_repositories,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.upgrade import upgrade_database


@pytest.fixture()
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "sample"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text(
        "def greet(name: str) -> str:\n    return f'hi {name}'\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def database(tmp_path: Path) -> Path:
    path = tmp_path / "session" / "codeatlas.db"
    path.parent.mkdir(parents=True)
    upgrade_database(path)
    return path


def test_register_repositories_registers_each_configured_path(
    database: Path, repository: Path
) -> None:
    with connect(database) as connection:
        outcome = register_repositories(build_services(connection), [str(repository)])

    assert len(outcome.registered) == 1
    assert outcome.failures == ()


def test_register_repositories_reports_and_skips_an_unusable_path(
    database: Path, repository: Path, tmp_path: Path
) -> None:
    missing = tmp_path / "does-not-exist"

    with connect(database) as connection:
        outcome = register_repositories(
            build_services(connection), [str(missing), str(repository)]
        )

    # The good path must still be registered: one bad entry cannot block start.
    assert len(outcome.registered) == 1
    assert len(outcome.failures) == 1
    assert outcome.failures[0].path == str(missing)
    assert outcome.failures[0].code


def test_index_repositories_activates_a_snapshot(
    database: Path, repository: Path
) -> None:
    with connect(database) as connection:
        outcome = register_repositories(build_services(connection), [str(repository)])
    repository_id = outcome.registered[0]

    index_repositories(database, [repository_id])

    with connect(database) as connection:
        snapshot = build_services(connection).indexing.get_active_snapshot(
            repository_id
        )
    assert snapshot is not None


def test_index_repositories_continues_after_one_failure(
    database: Path, repository: Path
) -> None:
    with connect(database) as connection:
        outcome = register_repositories(build_services(connection), [str(repository)])
    good = outcome.registered[0]

    # An unknown id must not stop the repositories behind it from indexing.
    index_repositories(database, ["repo_missing", good])

    with connect(database) as connection:
        snapshot = build_services(connection).indexing.get_active_snapshot(good)
    assert snapshot is not None
