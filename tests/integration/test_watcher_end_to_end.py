"""The watcher shell: real filesystem events, real threads, real reindex.

`test_watch_service.py` covers the policy by calling `note` and `tick`, which is
fast and deterministic. What it cannot cover is whether the observer is actually
wired to those methods — a watcher that never receives an event would pass every
one of those tests.

So this suite does the one thing that needs real time: it writes a file and
waits for the answer to change. It polls for a condition rather than sleeping a
fixed interval, so it is as fast as the machine allows and does not become
flaky on a slow one.

Gate condition 2: *a file changed on disk is reflected in query results without
an explicit index command, within a declared debounce window.*
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.lookup import SymbolLookupRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.application.watching import WatchService
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

SERVICE_SOURCE = """class PaymentService:
    def capture(self, key: str) -> str:
        return key
"""

# Short windows so the suite is quick; the production defaults are tuned for an
# editor rather than a test.
QUIET_PERIOD = 0.2
MAX_DELAY = 1.0

# Generous relative to the debounce window. It is an upper bound on a machine
# under load, not an expected duration — the poll returns as soon as the
# condition holds.
TIMEOUT_SECONDS = 30.0


@pytest.fixture()
def repository(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "service.py").write_text(SERVICE_SOURCE, encoding="utf-8")

    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        registered = services.registration.register(
            RegisterRepositoryRequest(path=str(root), display_name="watched")
        )
        services.indexing.index(registered.repository_id)
    return root, database, registered.repository_id


def services_factory(database: Path) -> Callable[[], object]:
    @contextmanager
    def factory() -> Iterator[ApplicationServices]:
        with connect(database) as connection:
            yield build_services(connection)

    return factory


def resolves(database: Path, repository_id: str, symbol: str) -> bool:
    with connect(database) as connection:
        response = build_services(connection).lookup.lookup(
            SymbolLookupRequest(
                request_id="req_watch_e2e",
                repository_id=repository_id,
                query=symbol,
            )
        )
    return bool(response.evidence)


def wait_until(predicate: Callable[[], bool]) -> bool:
    """Poll until the condition holds or the bound is reached."""
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_an_edit_on_disk_reaches_query_results_unasked(
    repository: tuple[Path, Path, str],
) -> None:
    root, database, repository_id = repository
    assert not resolves(database, repository_id, "PaymentService.refund")

    service = WatchService(
        services_factory=services_factory(database),  # type: ignore[arg-type]
        quiet_period_seconds=QUIET_PERIOD,
        max_delay_seconds=MAX_DELAY,
    )
    service.start_all()
    try:
        (root / "src" / "service.py").write_text(
            SERVICE_SOURCE
            + "\n    def refund(self, key: str) -> str:\n        return key\n",
            encoding="utf-8",
        )

        assert wait_until(
            lambda: resolves(database, repository_id, "PaymentService.refund")
        ), "the watcher did not refresh the index within the timeout"
    finally:
        service.stop_all()


def test_a_new_file_is_picked_up(repository: tuple[Path, Path, str]) -> None:
    root, database, repository_id = repository

    service = WatchService(
        services_factory=services_factory(database),  # type: ignore[arg-type]
        quiet_period_seconds=QUIET_PERIOD,
        max_delay_seconds=MAX_DELAY,
    )
    service.start_all()
    try:
        (root / "src" / "refunds.py").write_text(
            "class RefundService:\n    def issue(self) -> None:\n        return None\n",
            encoding="utf-8",
        )

        assert wait_until(
            lambda: resolves(database, repository_id, "RefundService.issue")
        ), "a newly created file was never indexed"
    finally:
        service.stop_all()


def test_an_ignored_directory_does_not_trigger_work(
    repository: tuple[Path, Path, str],
) -> None:
    # Writing into an ignored tree must not wake the indexer at all. This is
    # what keeps a watcher affordable on a repository with a dependency
    # directory churning underneath it.
    root, database, repository_id = repository
    (root / ".gitignore").write_text("build/\n", encoding="utf-8")

    service = WatchService(
        services_factory=services_factory(database),  # type: ignore[arg-type]
        quiet_period_seconds=QUIET_PERIOD,
        max_delay_seconds=MAX_DELAY,
    )
    service.start_all()
    try:
        # Let the .gitignore write itself settle first, so the assertion is
        # about the build directory and not about that file.
        time.sleep(QUIET_PERIOD * 4)
        (root / "build").mkdir()
        for index in range(5):
            (root / "build" / f"artifact{index}.py").write_text(
                "x = 1\n", encoding="utf-8"
            )
        time.sleep(QUIET_PERIOD * 4)

        status = service.status()[0]
        assert status.pending is False
        assert not resolves(database, repository_id, "artifact0")
    finally:
        service.stop_all()
