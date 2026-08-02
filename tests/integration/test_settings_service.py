"""Turning a provider on, which is the decision this whole phase defers to.

Everything built in P7-01 through P7-07 is inert until something writes a
provider policy. This service is that something, so it is also the last place a
mistake stays cheap: after it, repository content is being sent somewhere.

The rules under test are the ones that make "opt-in" mean opt-in — a
transmitting provider is never reachable by default, by omission, or by a
partial update that forgot to mention it.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.application.settings import SettingsService
from codeatlas.domain.errors import InvalidRequestError, RepositoryNotFoundError
from codeatlas.domain.semantic import EmbeddingProviderKind
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

_NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def connection(tmp_path: Path):  # type: ignore[no-untyped-def]
    with connect(tmp_path / "db.sqlite") as conn:
        apply_migrations(conn)
        conn.execute(
            "INSERT INTO repositories"
            " (repository_id, display_name, canonical_root, created_at)"
            " VALUES ('repo_1', 'demo', 'C:/repos/demo', '2026-07-30T00:00:00Z')"
        )
        yield conn


def _service(connection: sqlite3.Connection) -> SettingsService:
    return SettingsService(connection, now=lambda: _NOW)


# --- the default is off --------------------------------------------------


def test_a_repository_starts_with_no_provider(
    connection: sqlite3.Connection,
) -> None:
    """Absence resolves to `none`, so a failed write, a partial restore, or an
    upgrade cannot become a disclosure."""
    settings = _service(connection).get("repo_1")

    assert settings.embedding_provider is EmbeddingProviderKind.NONE


def test_an_unknown_repository_is_refused(connection: sqlite3.Connection) -> None:
    with pytest.raises(RepositoryNotFoundError):
        _service(connection).get("repo_missing")


# --- turning something on ------------------------------------------------


def test_the_local_provider_can_be_enabled_without_a_budget(
    connection: sqlite3.Connection,
) -> None:
    """`local` transmits nothing by construction, so there is no spending to
    bound and demanding a budget would be ceremony."""
    settings = _service(connection).update(
        "repo_1", embedding_provider=EmbeddingProviderKind.LOCAL
    )

    assert settings.embedding_provider is EmbeddingProviderKind.LOCAL
    assert settings.monthly_token_budget is None


def test_enabling_a_transmitting_provider_requires_a_monthly_budget(
    connection: sqlite3.Connection,
) -> None:
    """`ProviderPolicy` documents that an unlimited budget is only ever
    reachable for a provider that does not transmit. This is the application
    layer enforcing that pairing — an unbounded metered account is how a local
    tool produces a surprising bill."""
    with pytest.raises(InvalidRequestError):
        _service(connection).update(
            "repo_1", embedding_provider=EmbeddingProviderKind.OPENAI
        )


def test_a_transmitting_provider_is_enabled_when_a_budget_is_given(
    connection: sqlite3.Connection,
) -> None:
    settings = _service(connection).update(
        "repo_1",
        embedding_provider=EmbeddingProviderKind.OPENAI,
        monthly_token_budget=100_000,
    )

    assert settings.embedding_provider is EmbeddingProviderKind.OPENAI
    assert settings.monthly_token_budget == 100_000


def test_the_change_is_persisted(connection: sqlite3.Connection) -> None:
    _service(connection).update(
        "repo_1", embedding_provider=EmbeddingProviderKind.LOCAL
    )

    assert (
        _service(connection).get("repo_1").embedding_provider
        is EmbeddingProviderKind.LOCAL
    )


# --- a partial update must not change what it did not mention ------------


def test_updating_only_a_budget_leaves_the_provider_alone(
    connection: sqlite3.Connection,
) -> None:
    service = _service(connection)
    service.update("repo_1", embedding_provider=EmbeddingProviderKind.LOCAL)

    settings = service.update("repo_1", per_run_token_budget=500)

    assert settings.embedding_provider is EmbeddingProviderKind.LOCAL
    assert settings.per_run_token_budget == 500


def test_updating_only_the_provider_leaves_budgets_alone(
    connection: sqlite3.Connection,
) -> None:
    service = _service(connection)
    service.update(
        "repo_1",
        embedding_provider=EmbeddingProviderKind.OPENAI,
        monthly_token_budget=100_000,
    )

    settings = service.update("repo_1", per_run_token_budget=42)

    assert settings.monthly_token_budget == 100_000
    assert settings.embedding_provider is EmbeddingProviderKind.OPENAI


def test_a_transmitting_provider_cannot_have_its_budget_removed(
    connection: sqlite3.Connection,
) -> None:
    """The pairing has to hold under *edits*, not only at the moment of
    enabling. Removing the budget afterwards would reach the same unbounded
    state by a different route."""
    service = _service(connection)
    service.update(
        "repo_1",
        embedding_provider=EmbeddingProviderKind.OPENAI,
        monthly_token_budget=100_000,
    )

    with pytest.raises(InvalidRequestError):
        service.update("repo_1", monthly_token_budget=None, clear_monthly=True)


def test_turning_everything_off_is_always_allowed(
    connection: sqlite3.Connection,
) -> None:
    """The safe direction never needs permission."""
    service = _service(connection)
    service.update(
        "repo_1",
        embedding_provider=EmbeddingProviderKind.OPENAI,
        monthly_token_budget=100_000,
    )

    settings = service.update(
        "repo_1", embedding_provider=EmbeddingProviderKind.NONE
    )

    assert settings.embedding_provider is EmbeddingProviderKind.NONE


def test_a_negative_budget_is_refused(connection: sqlite3.Connection) -> None:
    with pytest.raises(InvalidRequestError):
        _service(connection).update("repo_1", per_run_token_budget=-1)


# --- describing what could run here --------------------------------------


def test_the_model_list_names_every_provider(
    connection: sqlite3.Connection,
) -> None:
    """Including the ones that cannot run, so a settings page can explain why
    an option is unavailable rather than hiding it."""
    kinds = {model.provider for model in _service(connection).models()}

    assert kinds == set(EmbeddingProviderKind)


def test_the_model_list_says_which_providers_transmit(
    connection: sqlite3.Connection,
) -> None:
    """The single most important fact on a settings page."""
    models = {model.provider: model for model in _service(connection).models()}

    assert models[EmbeddingProviderKind.OPENAI].transmits_off_machine is True
    assert models[EmbeddingProviderKind.LOCAL].transmits_off_machine is False
    assert models[EmbeddingProviderKind.NONE].transmits_off_machine is False


def test_the_model_list_carries_no_credential(
    connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 12.5: provider secrets never appear in a GET response.

    Checks for the credential's *value*, not for the string `api_key` — naming
    the environment variable a user must set is guidance, and a test that
    forbade it would be pushing the product towards saying less than it should.
    """
    secret = "sk-" + "livekey" * 6
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    rendered = repr(_service(connection).models())

    assert secret not in rendered


def test_the_model_list_names_the_variable_a_user_must_set(
    connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the same concern: an option that is unavailable has
    to say what is missing, or the settings page reads as broken."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    models = {model.provider: model for model in _service(connection).models()}

    requires = models[EmbeddingProviderKind.OPENAI].requires

    assert requires is not None
    assert "OPENAI_API_KEY" in requires


def test_models_report_the_configured_local_model(
    connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeatlas.settings.env_file import LOCAL_MODEL_VARIABLE

    monkeypatch.setenv(LOCAL_MODEL_VARIABLE, "BAAI/bge-small-en-v1.5")

    models = SettingsService(connection).models()
    local = next(m for m in models if m.provider is EmbeddingProviderKind.LOCAL)

    assert local.model_id == "BAAI/bge-small-en-v1.5"
    # Unknown until the model loads, and loading it to render a form is what
    # this function exists to avoid.
    assert local.dimensions is None


def test_models_explain_a_custom_openai_model_missing_its_width(
    connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeatlas.settings.env_file import (
        OPENAI_DIMENSIONS_VARIABLE,
        OPENAI_MODEL_VARIABLE,
    )

    monkeypatch.setenv(OPENAI_MODEL_VARIABLE, "text-embedding-3-large")
    monkeypatch.delenv(OPENAI_DIMENSIONS_VARIABLE, raising=False)

    models = SettingsService(connection).models()
    openai = next(m for m in models if m.provider is EmbeddingProviderKind.OPENAI)

    assert openai.available is False
    assert openai.requires is not None
    assert OPENAI_DIMENSIONS_VARIABLE in openai.requires
