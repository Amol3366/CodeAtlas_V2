from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codeatlas.storage.session import (
    create_session_directory,
    remove_session_directory,
    sessions_root,
    sweep_stale_sessions,
)


@pytest.fixture()
def fake_local_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def test_sessions_root_sits_under_local_app_data(fake_local_app_data: Path) -> None:
    assert sessions_root() == fake_local_app_data / "CodeAtlas" / "sessions"


def test_create_session_directory_is_empty_and_unique(
    fake_local_app_data: Path,
) -> None:
    now = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)
    first = create_session_directory(pid=111, now=now)
    second = create_session_directory(pid=222, now=now)

    assert first.is_dir()
    assert second.is_dir()
    assert first != second
    assert list(first.iterdir()) == []


def test_create_session_directory_encodes_pid_and_timestamp(
    fake_local_app_data: Path,
) -> None:
    now = datetime(2026, 8, 4, 12, 30, 45, tzinfo=UTC)
    created = create_session_directory(pid=4242, now=now)

    assert created.name.startswith("4242-")
    assert "20260804T123045Z" in created.name


def test_remove_session_directory_deletes_contents(
    fake_local_app_data: Path,
) -> None:
    created = create_session_directory(pid=os.getpid())
    (created / "codeatlas.db").write_text("data", encoding="utf-8")
    (created / "vectors").mkdir()

    remove_session_directory(created)

    assert not created.exists()


def test_remove_session_directory_tolerates_a_missing_directory(
    fake_local_app_data: Path,
) -> None:
    # A second shutdown path, or a user who deleted it, must not raise.
    remove_session_directory(sessions_root() / "999-20260804T000000Z")


def test_sweep_removes_sessions_whose_process_is_dead(
    fake_local_app_data: Path,
) -> None:
    now = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)
    dead = create_session_directory(pid=999_999, now=now)
    alive = create_session_directory(pid=os.getpid(), now=now)

    removed = sweep_stale_sessions(now=now)

    assert dead in removed
    assert not dead.exists()
    assert alive.exists()


def test_sweep_removes_a_live_pid_session_once_it_is_too_old(
    fake_local_app_data: Path,
) -> None:
    created_at = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)
    # A reused pid can make a dead session look alive. Age collects it anyway.
    stale = create_session_directory(pid=os.getpid(), now=created_at)

    removed = sweep_stale_sessions(now=created_at + timedelta(hours=25))

    assert stale in removed
    assert not stale.exists()


def test_sweep_ignores_unrecognized_directory_names(
    fake_local_app_data: Path,
) -> None:
    root = sessions_root()
    root.mkdir(parents=True, exist_ok=True)
    foreign = root / "not-a-session"
    foreign.mkdir()

    removed = sweep_stale_sessions(now=datetime.now(UTC))

    assert foreign not in removed
    assert foreign.exists()


def test_sweep_returns_empty_when_the_root_does_not_exist(
    fake_local_app_data: Path,
) -> None:
    assert sweep_stale_sessions(now=datetime.now(UTC)) == ()
