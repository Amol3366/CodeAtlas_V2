"""The Section 12.5 settings and models endpoints.

The surface that finally lets a user turn the semantic layer on — which makes it
the surface where "provider secrets never appear in GET responses, logs, browser
storage, exported history, or diagnostic bundles" has to be true rather than
intended.
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


# --- reading settings ----------------------------------------------------


def test_settings_default_to_no_provider(
    client: TestClient, repository_id: str
) -> None:
    response = client.get("/v1/settings", params={"repository_id": repository_id})

    assert response.status_code == 200, response.text
    assert response.json()["embedding_provider"] == "none"


def test_settings_for_an_unknown_repository_use_the_error_envelope(
    client: TestClient,
) -> None:
    response = client.get("/v1/settings", params={"repository_id": "repo_missing"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"


def test_settings_require_a_repository(client: TestClient) -> None:
    """The policy is per repository (ADR-0009 decision 5). A settings call with
    no repository would have to invent a default scope, and the safe default
    for a privacy setting is not a guess."""
    assert client.get("/v1/settings").status_code == 422


# --- changing settings ---------------------------------------------------


def test_the_local_provider_can_be_enabled(
    client: TestClient, repository_id: str
) -> None:
    response = client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"embedding_provider": "local"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["embedding_provider"] == "local"


def test_enabling_a_transmitting_provider_without_a_budget_is_refused(
    client: TestClient, repository_id: str
) -> None:
    response = client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"embedding_provider": "openai"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_a_transmitting_provider_is_accepted_with_a_budget(
    client: TestClient, repository_id: str
) -> None:
    response = client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"embedding_provider": "openai", "monthly_token_budget": 50000},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["embedding_provider"] == "openai"
    assert body["transmits_off_machine"] is True


def test_an_unknown_provider_is_rejected(
    client: TestClient, repository_id: str
) -> None:
    response = client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"embedding_provider": "some-other-service"},
    )

    assert response.status_code == 422


def test_the_change_survives_a_read(
    client: TestClient, repository_id: str
) -> None:
    client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"embedding_provider": "local", "per_run_token_budget": 200},
    )

    body = client.get(
        "/v1/settings", params={"repository_id": repository_id}
    ).json()
    assert body["embedding_provider"] == "local"
    assert body["per_run_token_budget"] == 200


def test_an_empty_patch_changes_nothing(
    client: TestClient, repository_id: str
) -> None:
    """A PATCH that reset unmentioned fields would let someone drop a budget by
    editing something unrelated."""
    client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"embedding_provider": "openai", "monthly_token_budget": 50000},
    )

    response = client.patch(
        "/v1/settings", params={"repository_id": repository_id}, json={}
    )

    assert response.status_code == 200, response.text
    assert response.json()["monthly_token_budget"] == 50000


# --- models --------------------------------------------------------------


def test_the_model_list_is_returned(client: TestClient) -> None:
    response = client.get("/v1/models")

    assert response.status_code == 200, response.text
    providers = {model["provider"] for model in response.json()["models"]}
    assert providers == {"none", "local", "openai"}


def test_the_model_list_marks_what_transmits(client: TestClient) -> None:
    models = {
        model["provider"]: model
        for model in client.get("/v1/models").json()["models"]
    }

    assert models["openai"]["transmits_off_machine"] is True
    assert models["local"]["transmits_off_machine"] is False


def test_no_credential_appears_in_any_response(
    client: TestClient, repository_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 12.5, asserted across the whole surface."""
    secret = "sk-" + "livekey" * 6
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    bodies = [
        client.get("/v1/models").text,
        client.get("/v1/settings", params={"repository_id": repository_id}).text,
        client.post(
            "/v1/models/test", params={"repository_id": repository_id}
        ).text,
    ]

    assert all(secret not in body for body in bodies)


# --- testing a provider --------------------------------------------------


def test_testing_a_disabled_provider_reports_disabled(
    client: TestClient, repository_id: str
) -> None:
    """Not an error: asking whether a switched-off provider works has an
    answer, and it is "it is switched off"."""
    response = client.post(
        "/v1/models/test", params={"repository_id": repository_id}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["detail_code"] == "PROVIDER_DISABLED"


def test_testing_reports_a_code_not_a_provider_message(
    client: TestClient, repository_id: str
) -> None:
    """A provider's own message can quote the request that produced it."""
    client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"embedding_provider": "openai", "monthly_token_budget": 50000},
    )

    body = client.post(
        "/v1/models/test", params={"repository_id": repository_id}
    ).json()

    assert body["ok"] is False
    assert body["detail_code"] == "PROVIDER_UNAVAILABLE"
