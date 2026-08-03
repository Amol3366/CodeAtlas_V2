"""How `serve` decides which database to open, and what it cleans up.

The resolution is tested directly rather than through a live server: it is the
whole of the mode's decision-making, and a bound port would add nothing to what
these assertions prove.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.cli.main import _ephemeral_requested, _resolve_serve_database


@pytest.fixture()
def fake_local_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def test_default_mode_uses_the_real_database(
    fake_local_app_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODEATLAS_DB_PATH", raising=False)
    resolved, session = _resolve_serve_database(database=None, ephemeral=False)

    assert session is None
    assert resolved.name == "codeatlas.db"
    assert "sessions" not in resolved.parts


def test_ephemeral_mode_uses_a_fresh_session_database(
    fake_local_app_data: Path,
) -> None:
    resolved, session = _resolve_serve_database(database=None, ephemeral=True)

    assert session is not None
    assert resolved == session / "codeatlas.db"
    assert session.is_dir()


def test_two_ephemeral_sessions_do_not_share_a_directory(
    fake_local_app_data: Path,
) -> None:
    first, first_session = _resolve_serve_database(database=None, ephemeral=True)
    second, second_session = _resolve_serve_database(database=None, ephemeral=True)

    assert first != second
    assert first_session != second_session


def test_explicit_database_wins_over_ephemeral(
    fake_local_app_data: Path, tmp_path: Path
) -> None:
    # An explicit --database is a deliberate instruction. Silently ignoring it
    # in favour of a throwaway directory would lose the user's data selection.
    explicit = tmp_path / "chosen.db"
    resolved, session = _resolve_serve_database(database=explicit, ephemeral=True)

    assert resolved == explicit
    assert session is None


def test_ephemeral_env_variable_enables_the_mode(
    fake_local_app_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEATLAS_EPHEMERAL", "1")
    assert _ephemeral_requested(flag=False) is True

    monkeypatch.setenv("CODEATLAS_EPHEMERAL", "0")
    assert _ephemeral_requested(flag=False) is False
    assert _ephemeral_requested(flag=True) is True


def test_ephemeral_is_off_when_the_variable_is_absent(
    fake_local_app_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODEATLAS_EPHEMERAL", raising=False)
    assert _ephemeral_requested(flag=False) is False
