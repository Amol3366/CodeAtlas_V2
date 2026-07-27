"""The watch switch over HTTP.

The API is built with `watch=False` here. These tests are about the contract —
what the endpoints report and persist — and starting real observers on temporary
directories would add background threads without adding an assertion.
`tests/integration/test_watcher_end_to_end.py` covers the observer itself.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)
    with TestClient(create_app(database_path, watch=False)) as test_client:
        yield test_client


@pytest.fixture()
def repository_id(client: TestClient, sample_repo: Path) -> str:
    response = client.post("/v1/repositories", json={"path": str(sample_repo)})
    assert response.status_code == 201, response.text
    return str(response.json()["repository_id"])


def test_watching_is_on_by_default(client: TestClient, repository_id: str) -> None:
    """A newly registered repository is watched without being asked.

    The alternative answers "how current is this evidence?" with "stale, and
    you were not told".
    """
    response = client.get(f"/v1/repositories/{repository_id}/watch")

    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is True


def test_the_switch_can_be_turned_off_and_back_on(
    client: TestClient, repository_id: str
) -> None:
    off = client.put(
        f"/v1/repositories/{repository_id}/watch", json={"enabled": False}
    )
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False
    assert client.get(f"/v1/repositories/{repository_id}/watch").json()["enabled"] is (
        False
    )

    on = client.put(f"/v1/repositories/{repository_id}/watch", json={"enabled": True})
    assert on.status_code == 200, on.text
    assert on.json()["enabled"] is True


def test_the_switch_survives_a_restart(tmp_path: Path, sample_repo: Path) -> None:
    # Persisted, not held in memory: turning the watcher off is a decision about
    # the repository, not about the process that happened to be running.
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)

    with TestClient(create_app(database_path, watch=False)) as first:
        registered = first.post("/v1/repositories", json={"path": str(sample_repo)})
        repository_id = registered.json()["repository_id"]
        first.put(
            f"/v1/repositories/{repository_id}/watch", json={"enabled": False}
        )

    with TestClient(create_app(database_path, watch=False)) as second:
        response = second.get(f"/v1/repositories/{repository_id}/watch")

    assert response.json()["enabled"] is False


def test_enabled_and_running_are_reported_separately(
    client: TestClient, repository_id: str
) -> None:
    """They disagree when a watcher could not start, and that case must show.

    Reporting only the stored switch would say "on" about a watcher that is not
    running — the most misleading thing this endpoint could do.
    """
    body = client.get(f"/v1/repositories/{repository_id}/watch").json()

    assert body["enabled"] is True
    assert body["running"] is False
    assert body["failure_count"] == 0
    assert body["last_error"] is None


def test_an_unknown_repository_is_a_404(client: TestClient) -> None:
    response = client.get("/v1/repositories/repo_missing/watch")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"


def test_an_unknown_field_is_refused(client: TestClient, repository_id: str) -> None:
    # A typo'd field must fail loudly rather than silently leaving the switch
    # untouched while reporting success.
    response = client.put(
        f"/v1/repositories/{repository_id}/watch",
        json={"enabled": True, "recursive": True},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
