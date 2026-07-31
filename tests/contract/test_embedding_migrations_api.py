"""The Section 12.5 embedding migration endpoints."""

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
    identifier = str(response.json()["repository_id"])
    assert client.post(f"/v1/repositories/{identifier}/index").status_code == 200
    return identifier


def test_a_disabled_repository_cannot_start_a_model_migration(
    client: TestClient, repository_id: str
) -> None:
    response = client.post(
        "/v1/models/embedding-migrations",
        json={"repository_id": repository_id},
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "PROVIDER_DISABLED"


def test_unknown_repository_uses_the_error_envelope(client: TestClient) -> None:
    response = client.post(
        "/v1/models/embedding-migrations",
        json={"repository_id": "repo_missing"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"


def test_get_unknown_migration_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get("/v1/models/embedding-migrations/mig_missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EMBEDDING_MIGRATION_NOT_FOUND"


def test_activate_unknown_migration_uses_the_error_envelope(
    client: TestClient,
) -> None:
    response = client.post("/v1/models/embedding-migrations/mig_missing/activate")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EMBEDDING_MIGRATION_NOT_FOUND"


def test_activate_rejects_an_unknown_target(client: TestClient) -> None:
    response = client.post(
        "/v1/models/embedding-migrations/mig_missing/activate",
        json={"target": "elsewhere"},
    )

    assert response.status_code == 422


def test_no_absolute_path_appears_in_migration_errors(
    client: TestClient, repository_id: str, sample_repo: Path
) -> None:
    response = client.post(
        "/v1/models/embedding-migrations",
        json={"repository_id": repository_id},
    )

    assert str(sample_repo) not in response.text

