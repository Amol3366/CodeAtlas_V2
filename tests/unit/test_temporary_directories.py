"""Each pytest session owns its own temporary directory.

`--basetemp` used to be pinned to the shared `.test-tmp`, and pytest *deletes
the directory it is given* when the first `tmp_path` is requested -- not a
numbered subdirectory of it, the directory itself. Two runs therefore destroyed
each other's live files, which is why four gate runs in two days were void and
why the post-closeout program carried a rule saying never to run two at once.

These tests pin the replacement: a repository-local root, a per-session leaf,
and a pruner that cannot delete a directory another run is still using.

The helpers arrive as fixtures rather than imports. Importing `tests.conftest`
makes mypy find that file under two module names and refuse the entire run --
the same collision its own comment records for a second conftest module.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _config(basetemp: str | None = None) -> SimpleNamespace:
    """The two attributes the hook reads. A real Config needs a full session."""
    return SimpleNamespace(option=SimpleNamespace(basetemp=basetemp))


def test_the_session_basetemp_is_inside_the_repository_local_root(
    tmp_path: Path, session_tmp_root: Path
) -> None:
    """The root stays in the repository on purpose.

    `docs/operations/development-windows.md` records that a locked-down Windows
    account may be unable to write the system temp directory, which is why this
    is not simply pytest's default.
    """
    assert session_tmp_root.name == ".test-tmp"
    resolved = tmp_path.resolve()
    assert session_tmp_root.resolve() in resolved.parents

    # The session leaf, asserted separately and deliberately. Checking only that
    # the root is *somewhere* above `tmp_path` passes just as well when
    # `--basetemp` is pinned back to the shared directory -- which is exactly
    # what the mutation check caught this test failing to notice.
    session = resolved.relative_to(session_tmp_root.resolve()).parts[0]
    assert session.startswith("s-"), (
        f"expected a per-session directory under {session_tmp_root}, "
        f"got {session}"
    )


def test_two_sessions_are_given_different_directories(
    assign_session_basetemp: Callable[[Any], None],
) -> None:
    """The whole fix in one assertion."""
    first, second = _config(), _config()

    assign_session_basetemp(first)
    assign_session_basetemp(second)

    assert first.option.basetemp != second.option.basetemp


def test_an_explicit_basetemp_is_left_alone(
    assign_session_basetemp: Callable[[Any], None],
) -> None:
    """`pytest --basetemp=X` must still mean X, or debugging loses a tool."""
    config = _config(basetemp="/somewhere/chosen")

    assign_session_basetemp(config)

    assert config.option.basetemp == "/somewhere/chosen"


def test_a_stale_session_directory_is_pruned(
    tmp_path: Path, prune_sessions: Callable[[Path], None]
) -> None:
    stale = tmp_path / "s-1234-abcdef12"
    stale.mkdir()
    (stale / "leftover.txt").write_text("old", encoding="utf-8")
    old = (datetime.now(UTC) - timedelta(hours=48)).timestamp()
    os.utime(stale, (old, old))

    prune_sessions(tmp_path)

    assert not stale.exists()


def test_a_fresh_session_directory_is_kept(
    tmp_path: Path, prune_sessions: Callable[[Path], None]
) -> None:
    """A live run's directory must survive another run's startup.

    This is the property the old design broke. Age is the test rather than
    ownership because a pid is a slot the OS reassigns (ADR-0037), so asking
    "does another pytest still own this?" has no reliable answer.
    """
    live = tmp_path / "s-5678-12345678"
    live.mkdir()
    (live / "in-use.txt").write_text("a run is using this", encoding="utf-8")

    prune_sessions(tmp_path)

    assert (live / "in-use.txt").read_text(encoding="utf-8") == (
        "a run is using this"
    )


def test_pruning_ignores_anything_that_is_not_a_session_directory(
    tmp_path: Path, prune_sessions: Callable[[Path], None]
) -> None:
    """Only `s-*` directories are ours. Nothing else is touched at any age."""
    stranger = tmp_path / "not-a-session"
    stranger.mkdir()
    old = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    os.utime(stranger, (old, old))

    prune_sessions(tmp_path)

    assert stranger.exists()


def test_the_shared_basetemp_is_no_longer_pinned() -> None:
    """The regression guard for the whole task.

    Restoring `--basetemp=.test-tmp` to `addopts` silently reinstates the
    shared directory and every test above keeps passing, because the hook would
    then see a basetemp already set and decline to override it.
    """
    addopts = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "--basetemp" not in addopts
