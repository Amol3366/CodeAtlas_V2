"""The API must survive the concurrent requests a browser always makes.

Every contract test so far has driven the API one request at a time, which is
not how it is used. Opening the web application fires the repository list, the
index status, the diagnostics, and the conversation list at once, and FastAPI
runs synchronous handlers on a thread pool — so those land on several threads
simultaneously.

A single `sqlite3.Connection` shared across them raises
``InterfaceError: bad parameter or other API misuse`` under exactly that load,
and can also hand one request another's result columns. It is intermittent, it
surfaces as a 500 on a random one of the four requests, and it stayed invisible
until a real browser drove the application.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

# Enough overlap to make the interleaving reliable rather than lucky. The bug
# needs two threads inside `execute` at once; a handful of rounds across a
# handful of workers gets there every time.
WORKERS = 8
ROUNDS = 12


class IndexedApi(NamedTuple):
    """A running API with one repository already indexed."""

    client: TestClient
    repository_id: str


@pytest.fixture()
def indexed(tmp_path: Path, sample_repo: Path) -> Iterator[IndexedApi]:
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)
    with TestClient(create_app(database_path)) as client:
        created = client.post("/v1/repositories", json={"path": str(sample_repo)})
        assert created.status_code == 201, created.text
        repository_id = str(created.json()["repository_id"])
        indexed = client.post(f"/v1/repositories/{repository_id}/index")
        assert indexed.status_code == 200, indexed.text
        yield IndexedApi(client, repository_id)


def test_concurrent_reads_do_not_corrupt_the_connection(indexed: IndexedApi) -> None:
    """The four requests a page load makes, overlapping, must all succeed."""
    paths = [
        "/v1/repositories",
        f"/v1/repositories/{indexed.repository_id}/status",
        f"/v1/repositories/{indexed.repository_id}/diagnostics",
        f"/v1/conversations?repository_id={indexed.repository_id}",
    ]

    def fetch(path: str) -> tuple[str, int, str]:
        response = indexed.client.get(path)
        return path, response.status_code, response.text

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(fetch, paths * ROUNDS))

    failures = [(path, status, body) for path, status, body in results if status != 200]
    assert not failures, f"concurrent requests failed: {failures[:3]}"


def test_concurrent_writes_and_reads_do_not_corrupt_the_connection(
    indexed: IndexedApi,
) -> None:
    """Writes interleaved with reads, which is what submitting a message does.

    WAL serializes writers at the database; what must not happen is two threads
    reaching the same connection object at once.
    """

    def create_conversation(index: int) -> int:
        response = indexed.client.post(
            "/v1/conversations",
            json={
                "repository_id": indexed.repository_id,
                "title": f"thread {index}",
            },
        )
        return int(response.status_code)

    def read(_: int) -> int:
        return int(
            indexed.client.get(
                f"/v1/repositories/{indexed.repository_id}/status"
            ).status_code
        )

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        written = list(pool.map(create_conversation, range(ROUNDS)))
        read_back = list(pool.map(read, range(ROUNDS)))

    assert set(written) == {201}, written
    assert set(read_back) == {200}, read_back

    listed = indexed.client.get(
        f"/v1/conversations?repository_id={indexed.repository_id}"
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["items"]) == ROUNDS
