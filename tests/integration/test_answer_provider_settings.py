"""Per-repository answer-provider settings.

The second provider decision. It is deliberately independent of the embedding
one: a repository may reasonably retrieve locally and answer remotely, or the
reverse, and folding both into one column would make "which provider" ambiguous
at every read site.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.application.settings import SettingsService
from codeatlas.domain.errors import InvalidRequestError
from codeatlas.domain.semantic import AnswerProviderKind, EmbeddingProviderKind
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import RepositoryStore


@pytest.fixture()
def service_and_repository(
    tmp_path: Path, sample_repo: Path
) -> Iterator[tuple[SettingsService, str]]:
    from codeatlas.application.container import build_services

    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        assert RepositoryStore(connection).get(repository.repository_id) is not None
        yield SettingsService(connection), repository.repository_id


def test_a_repository_defaults_to_no_answer_provider(
    service_and_repository: tuple[SettingsService, str],
) -> None:
    service, repository_id = service_and_repository
    assert service.get(repository_id).answer_provider is AnswerProviderKind.NONE


def test_choosing_ollama_stores_the_model(
    service_and_repository: tuple[SettingsService, str],
) -> None:
    service, repository_id = service_and_repository

    updated = service.update(
        repository_id,
        answer_provider=AnswerProviderKind.OLLAMA,
        answer_model="llama3.1:8b",
    )

    assert updated.answer_provider is AnswerProviderKind.OLLAMA
    assert updated.answer_model == "llama3.1:8b"


def test_a_partial_update_does_not_reset_the_answer_provider(
    service_and_repository: tuple[SettingsService, str],
) -> None:
    """The existing sentinel rule extends to the new fields."""
    service, repository_id = service_and_repository
    service.update(repository_id, answer_provider=AnswerProviderKind.OLLAMA)

    service.update(repository_id, monthly_token_budget=5000)

    assert service.get(repository_id).answer_provider is AnswerProviderKind.OLLAMA


def test_a_transmitting_answer_provider_requires_a_monthly_budget(
    service_and_repository: tuple[SettingsService, str],
) -> None:
    service, repository_id = service_and_repository

    with pytest.raises(InvalidRequestError):
        service.update(repository_id, answer_provider=AnswerProviderKind.OPENAI)


def test_ollama_needs_no_budget_because_it_transmits_nothing(
    service_and_repository: tuple[SettingsService, str],
) -> None:
    service, repository_id = service_and_repository

    updated = service.update(
        repository_id, answer_provider=AnswerProviderKind.OLLAMA
    )

    assert updated.monthly_token_budget is None


def test_the_two_provider_decisions_are_independent(
    service_and_repository: tuple[SettingsService, str],
) -> None:
    """Retrieve locally, answer remotely, or the reverse."""
    service, repository_id = service_and_repository

    updated = service.update(
        repository_id,
        embedding_provider=EmbeddingProviderKind.LOCAL,
        answer_provider=AnswerProviderKind.OLLAMA,
    )

    assert updated.embedding_provider is EmbeddingProviderKind.LOCAL
    assert updated.answer_provider is AnswerProviderKind.OLLAMA


def test_a_stored_answer_timeout_survives_a_round_trip(
    service_and_repository: tuple[SettingsService, str],
) -> None:
    """A heavier local model legitimately needs longer than the default."""
    service, repository_id = service_and_repository

    service.update(
        repository_id,
        answer_provider=AnswerProviderKind.OLLAMA,
        answer_timeout_seconds=600,
    )

    assert service.get(repository_id).answer_timeout_seconds == 600
