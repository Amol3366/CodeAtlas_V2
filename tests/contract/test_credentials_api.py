"""The credential endpoints (`AGENTS.md` Section 12.5).

Every test here is ultimately the same assertion in a different place: the
value goes in and never comes back out.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.settings.credentials import OPENAI_CREDENTIAL_NAME
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

SECRET = "sk-" + "contract" * 5


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # No ambient key: these tests are about what the endpoints do, not about
    # what happens to be configured on the machine running them.
    #
    # Set empty rather than deleted. `create_app` calls `load_env_file`, which
    # applies `.env` to any key the environment does not already have — so a
    # deleted variable is refilled from the developer's real `.env` before the
    # first request, and the suite would pass or fail depending on whose
    # machine it ran on. An empty value is present, so the file cannot
    # override it, and it resolves to `None`.
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "")
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)
    with TestClient(create_app(database_path, watch=False)) as test_client:
        yield test_client


def test_status_reports_nothing_configured(client: TestClient) -> None:
    response = client.get("/v1/credentials")

    assert response.status_code == 200, response.text
    body = response.json()["openai"]
    assert body["configured"] is False
    assert body["source"] is None
    assert "store_available" in body


def test_status_never_carries_a_value_field(client: TestClient) -> None:
    """Section 12.5 has no exception for part of a secret, so there is no
    field a value could occupy - not even a masked one.

    Asserted as an exact key set rather than a `not in`, so adding a
    `masked_key` later fails here instead of passing review.
    """
    body = client.get("/v1/credentials").json()["openai"]

    assert set(body) == {"configured", "source", "store_available"}


def test_an_empty_key_is_refused(client: TestClient) -> None:
    response = client.put("/v1/credentials/openai", json={"api_key": ""})

    assert response.status_code == 422


def test_an_overlong_key_is_refused(client: TestClient) -> None:
    response = client.put("/v1/credentials/openai", json={"api_key": "s" * 501})

    assert response.status_code == 422


def test_an_unknown_field_is_refused(client: TestClient) -> None:
    response = client.put(
        "/v1/credentials/openai", json={"api_key": SECRET, "extra": 1}
    )

    assert response.status_code == 422


def test_deleting_an_absent_credential_succeeds(client: TestClient) -> None:
    """Idempotent: the caller wants "no key stored", and that already holds."""
    response = client.delete("/v1/credentials/openai")

    assert response.status_code == 200, response.text
    assert response.json()["openai"]["configured"] is False


def test_an_env_key_is_reported_as_such(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, SECRET)

    body = client.get("/v1/credentials").json()["openai"]

    assert body["configured"] is True
    assert body["source"] == "env"


def test_no_endpoint_echoes_the_key_back(client: TestClient) -> None:
    """The single assertion this whole surface exists to keep.

    Skipped where no credential store exists, because there is nowhere to
    write the key and the PUT correctly refuses.
    """
    written = client.put("/v1/credentials/openai", json={"api_key": SECRET})
    if written.status_code != 200:
        pytest.skip("no credential store on this platform")

    try:
        bodies = [
            written.text,
            client.get("/v1/credentials").text,
            client.get("/v1/models").text,
        ]
        assert all(SECRET not in body for body in bodies)
    finally:
        client.delete("/v1/credentials/openai")


def test_a_stored_key_round_trips_as_status_only(client: TestClient) -> None:
    written = client.put("/v1/credentials/openai", json={"api_key": SECRET})
    if written.status_code != 200:
        pytest.skip("no credential store on this platform")

    try:
        body = client.get("/v1/credentials").json()["openai"]
        assert body["configured"] is True
        assert body["source"] == "credential_store"
    finally:
        client.delete("/v1/credentials/openai")
