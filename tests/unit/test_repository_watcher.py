"""The watcher's decision logic, without threads or real filesystem events.

`RepositoryWatcher` keeps its policy in two plain methods — `note` for an
observed path and `tick` for one drain pass — so everything that matters can be
tested by calling them. The observer thread is a thin shell around these, and
the integration test covers that the shell is wired up.

The rule under test throughout is ADR-0007 decision 1: **an event names a
candidate, it does not establish that work is needed.** The watcher's job is to
decide what is worth looking at and to say so once.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.indexing.debounce import Debouncer
from codeatlas.indexing.watcher import RepositoryWatcher
from codeatlas.repositories.ignore_rules import IgnoreRules


class FakeClock:
    """A clock the test advances explicitly."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


def build(
    root: Path, clock: FakeClock, batches: list[tuple[str, ...]]
) -> RepositoryWatcher:
    return RepositoryWatcher(
        repository_id="repo_1",
        root=root,
        rules=IgnoreRules.load(root),
        on_batch=batches.append,
        debouncer=Debouncer(quiet_period_seconds=0.5, max_delay_seconds=3.0),
        clock=clock,
    )


def test_a_changed_source_file_is_reported_as_a_relative_path(
    root: Path, clock: FakeClock
) -> None:
    batches: list[tuple[str, ...]] = []
    watcher = build(root, clock, batches)

    watcher.note(root / "src" / "service.py", is_directory=False)
    clock.advance(1.0)
    watcher.tick()

    # Forward slashes regardless of platform: the batch names repository paths,
    # which are the identities the rest of the system uses.
    assert batches == [("src/service.py",)]


def test_a_burst_produces_one_batch(root: Path, clock: FakeClock) -> None:
    batches: list[tuple[str, ...]] = []
    watcher = build(root, clock, batches)

    watcher.note(root / "src" / "a.py", is_directory=False)
    watcher.note(root / "src" / "b.py", is_directory=False)
    watcher.tick()  # still gathering
    clock.advance(1.0)
    watcher.tick()

    assert batches == [("src/a.py", "src/b.py")]


def test_nothing_is_dispatched_while_the_batch_is_gathering(
    root: Path, clock: FakeClock
) -> None:
    batches: list[tuple[str, ...]] = []
    watcher = build(root, clock, batches)

    watcher.note(root / "src" / "a.py", is_directory=False)
    clock.advance(0.2)
    watcher.tick()

    assert batches == []


def test_an_ignored_path_is_never_a_candidate(root: Path, clock: FakeClock) -> None:
    # A dependency directory changes constantly and means nothing to the index.
    # Waking the indexer for it would burn the battery to learn nothing.
    batches: list[tuple[str, ...]] = []
    watcher = build(root, clock, batches)

    watcher.note(root / "node_modules" / "left-pad" / "index.js", is_directory=False)
    clock.advance(1.0)
    watcher.tick()

    assert batches == []


def test_git_internals_are_never_candidates(root: Path, clock: FakeClock) -> None:
    # Git rewrites its own directory constantly, including during the checkout
    # that a watcher most wants to notice. Following it would be a feedback loop.
    batches: list[tuple[str, ...]] = []
    watcher = build(root, clock, batches)

    watcher.note(root / ".git" / "index", is_directory=False)
    clock.advance(1.0)
    watcher.tick()

    assert batches == []


def test_a_path_outside_the_root_is_refused(root: Path, clock: FakeClock) -> None:
    # Canonicalized paths must stay inside the approved root (`AGENTS.md`
    # Section 4.4). A watch that followed a junction out of the tree would index
    # somewhere the user never approved.
    batches: list[tuple[str, ...]] = []
    watcher = build(root, clock, batches)

    watcher.note(root.parent / "elsewhere" / "secret.py", is_directory=False)
    clock.advance(1.0)
    watcher.tick()

    assert batches == []


def test_the_repository_root_itself_is_not_a_candidate(
    root: Path, clock: FakeClock
) -> None:
    batches: list[tuple[str, ...]] = []
    watcher = build(root, clock, batches)

    watcher.note(root, is_directory=True)
    clock.advance(1.0)
    watcher.tick()

    assert batches == []


def test_a_failing_callback_does_not_stop_the_watcher(
    root: Path, clock: FakeClock
) -> None:
    # If one reindex fails, freshness must not stop forever. A watcher that died
    # on its first error would leave the index silently stale — the exact
    # failure this phase exists to prevent.
    seen: list[tuple[str, ...]] = []

    def explode(batch: tuple[str, ...]) -> None:
        seen.append(batch)
        raise RuntimeError("indexing blew up")

    watcher = RepositoryWatcher(
        repository_id="repo_1",
        root=root,
        rules=IgnoreRules.load(root),
        on_batch=explode,
        debouncer=Debouncer(quiet_period_seconds=0.5, max_delay_seconds=3.0),
        clock=clock,
    )

    watcher.note(root / "src" / "a.py", is_directory=False)
    clock.advance(1.0)
    watcher.tick()

    watcher.note(root / "src" / "b.py", is_directory=False)
    clock.advance(1.0)
    watcher.tick()

    assert seen == [("src/a.py",), ("src/b.py",)]
    assert watcher.failure_count == 2
    assert watcher.last_error is not None


def test_a_dropped_batch_is_counted_rather_than_lost_silently(
    root: Path, clock: FakeClock
) -> None:
    """A failure is visible in diagnostics, not just in a log nobody reads."""
    watcher = RepositoryWatcher(
        repository_id="repo_1",
        root=root,
        rules=IgnoreRules.load(root),
        on_batch=lambda _: (_ for _ in ()).throw(OSError("disk full")),
        debouncer=Debouncer(quiet_period_seconds=0.5, max_delay_seconds=3.0),
        clock=clock,
    )

    watcher.note(root / "src" / "a.py", is_directory=False)
    clock.advance(1.0)
    watcher.tick()

    assert watcher.failure_count == 1
    assert "OSError" in str(watcher.last_error)
