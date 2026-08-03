"""Two ephemeral runs must share no repository, snapshot, or conversation.

The unit tests prove each piece resolves a fresh path. This proves the whole
mode does what was asked: a second run starts empty even though a first run
registered and indexed a repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.ephemeral_bootstrap import (
    index_repositories,
    register_repositories,
)
from codeatlas.cli.main import _resolve_serve_database
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.upgrade import upgrade_database


@pytest.fixture()
def fake_local_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    return tmp_path


@pytest.fixture()
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "sample"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text(
        "def greet(name: str) -> str:\n    return f'hi {name}'\n",
        encoding="utf-8",
    )
    return root


def test_a_second_session_starts_empty(
    fake_local_app_data: Path, repository: Path
) -> None:
    first, first_session = _resolve_serve_database(database=None, ephemeral=True)
    upgrade_database(first)

    with connect(first) as connection:
        outcome = register_repositories(build_services(connection), [str(repository)])
    index_repositories(first, outcome.registered)

    with connect(first) as connection:
        assert len(build_services(connection).repositories.list_all()) == 1

    # A new run of the same command.
    second, second_session = _resolve_serve_database(database=None, ephemeral=True)
    upgrade_database(second)

    assert second_session != first_session
    with connect(second) as connection:
        assert build_services(connection).repositories.list_all() == ()


def test_a_session_directory_holds_its_own_vectors(
    fake_local_app_data: Path,
) -> None:
    # The vector directory is derived from the database's parent, so a fresh
    # session directory is what makes embeddings fresh too. If this ever stops
    # being true, the mode silently reuses another run's vectors.
    resolved, session = _resolve_serve_database(database=None, ephemeral=True)

    assert session is not None
    assert resolved.parent == session
