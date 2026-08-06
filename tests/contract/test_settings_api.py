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


class _WorkingProvider:
    """A provider that answers, without a model, a network, or a credential.

    The success branch of `/v1/models/test` went untested from the Phase 7 gate
    until 2026-08-07 because reaching it "needs an available provider". It does
    not: it needs something that returns a vector. Waiting for a real provider
    is what kept the branch uncovered for a week, and once one *was* installed
    the honest version of that test would have issued a real billable request
    on every run.
    """

    model_id = "fake"
    dimensions = 3
    normalization_version = "l2_v1"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)


class _SilentProvider(_WorkingProvider):
    """Answers, but with nothing in it."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


def _use_provider(monkeypatch: pytest.MonkeyPatch, provider: object) -> None:
    """Make `ProviderFactory.build` hand back `provider`.

    Patched at the factory rather than at the transport because the factory is
    the only supported way `test_provider` obtains anything, so this is the one
    seam that cannot be bypassed by a change in how a provider is constructed.
    """
    monkeypatch.setattr(
        "codeatlas.semantic.providers.ProviderFactory.build",
        lambda self, policy: provider,
    )


def test_a_working_provider_is_reported_as_ok(
    client: TestClient, repository_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The success branch: the provider answered, so the answer is yes."""
    client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"embedding_provider": "local"},
    )
    _use_provider(monkeypatch, _WorkingProvider())

    response = client.post(
        "/v1/models/test", params={"repository_id": repository_id}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    # No code, because nothing went wrong. A success carrying a detail code
    # would make "ok" and "detail_code" two ways of saying the same thing that
    # could disagree.
    assert body["detail_code"] is None
    assert body["provider"] == "local"
    assert body["latency_ms"] >= 0


def test_a_provider_that_returns_no_vector_is_not_ok(
    client: TestClient, repository_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Answering is not the same as working.

    A provider that responds with an empty vector has satisfied the call and
    produced nothing usable. Reporting that as success would tell a user their
    semantic setup is fine while every embedding it makes is empty.
    """
    client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"embedding_provider": "local"},
    )
    _use_provider(monkeypatch, _SilentProvider())

    body = client.post(
        "/v1/models/test", params={"repository_id": repository_id}
    ).json()

    assert body["ok"] is False
    assert body["detail_code"] == "PROVIDER_RETURNED_NO_VECTOR"


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
    client: TestClient, repository_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider's own message can quote the request that produced it.

    The credential is removed rather than assumed absent. This assertion is
    about the *shape* of a failure — a code, never the provider's own text —
    so it must hold identically whether or not the `semantic-openai` extra is
    installed and whether or not a key is configured on this machine.

    Asserting the failure without forcing it is what this test did until
    2026-08-06, and it silently tested the environment instead of the code: it
    passed only because no provider was installed, then failed the moment one
    was, and reaching the success branch it had never covered meant issuing a
    real billable request to OpenAI from the test suite. A gate that depends on
    an optional provider and a network is what Section 4.3 forbids.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
    # The invariant the name promises: no free-text provider message anywhere
    # in the payload, because for a transmitting provider that text can quote
    # the content that produced it.
    assert "message" not in body


# --- answer generation ---------------------------------------------------


def test_settings_report_the_answer_provider(
    client: TestClient, repository_id: str
) -> None:
    body = client.get("/v1/settings", params={"repository_id": repository_id}).json()

    assert body["answer_provider"] == "none"
    assert body["answer_model"] is None
    assert body["answer_timeout_seconds"] is None


def test_the_answer_provider_can_be_switched_on(
    client: TestClient, repository_id: str
) -> None:
    response = client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"answer_provider": "ollama", "answer_model": "llama3.2:3b"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["answer_provider"] == "ollama"
    assert response.json()["answer_model"] == "llama3.2:3b"


def test_switching_to_a_transmitting_answer_provider_needs_a_budget(
    client: TestClient, repository_id: str
) -> None:
    """The same rule the embedding provider already obeys, for the same reason."""
    response = client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"answer_provider": "openai"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_a_transmitting_answer_provider_is_allowed_with_a_budget(
    client: TestClient, repository_id: str
) -> None:
    response = client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"answer_provider": "openai", "monthly_token_budget": 50_000},
    )

    assert response.status_code == 200, response.text
    assert response.json()["transmits_off_machine"] is True


def test_changing_the_budget_leaves_the_answer_provider_alone(
    client: TestClient, repository_id: str
) -> None:
    client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"answer_provider": "ollama"},
    )

    client.patch(
        "/v1/settings",
        params={"repository_id": repository_id},
        json={"per_run_token_budget": 1000},
    )

    body = client.get("/v1/settings", params={"repository_id": repository_id}).json()
    assert body["answer_provider"] == "ollama"


def test_the_models_endpoint_lists_answer_providers(client: TestClient) -> None:
    body = client.get("/v1/models").json()

    providers = {model["provider"] for model in body["answer_models"]}
    assert providers == {"none", "ollama", "openai"}


def test_the_local_answer_provider_is_marked_as_not_transmitting(
    client: TestClient,
) -> None:
    body = client.get("/v1/models").json()

    ollama = next(
        model for model in body["answer_models"] if model["provider"] == "ollama"
    )
    assert ollama["transmits_off_machine"] is False
    assert ollama["model_id"] == "llama3.2:3b"


def test_no_answer_setting_ever_returns_a_credential(
    client: TestClient, repository_id: str
) -> None:
    body = client.get("/v1/settings", params={"repository_id": repository_id}).json()

    assert "api_key" not in str(body).lower()
    assert "sk-" not in str(body)


# --- validating an embedding model ---------------------------------------


def test_validating_a_model_reports_its_measured_dimensions(
    client: TestClient,
) -> None:
    """The width is measured, never guessed.

    The namespace is keyed on (model_id, dimensions, normalization_version). A
    wrong width never raises; it just returns worse results indefinitely, so
    the only safe way to admit an arbitrary model id is to load it and ask.
    """
    response = client.post(
        "/v1/models/embedding/validate",
        json={"model_id": "sentence-transformers/all-MiniLM-L6-v2"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_id"] == "sentence-transformers/all-MiniLM-L6-v2"
    if body["ok"]:
        assert body["dimensions"] == 384
    else:
        # Without the semantic-local extra installed there is nothing to load,
        # and a test that assumed otherwise would fail for an environmental
        # reason rather than a code one.
        assert body["dimensions"] is None
        assert body["detail_code"] is not None


def test_validating_an_unloadable_model_reports_a_code_not_a_message(
    client: TestClient,
) -> None:
    """A provider message can quote what produced it. A code cannot."""
    response = client.post(
        "/v1/models/embedding/validate",
        json={"model_id": "codeatlas/definitely-not-a-real-model"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["dimensions"] is None
    assert body["detail_code"] is not None


def test_validating_rejects_a_blank_model_id(client: TestClient) -> None:
    response = client.post("/v1/models/embedding/validate", json={"model_id": "  "})

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
