"""Which model answers for one repository.

The policy decides *whether* generation happens. The environment decides only
*which* model runs when it does. The last test here is the one that matters
most: no variable can turn a `none` repository into a generating one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from codeatlas.domain.semantic import (
    AnswerProviderKind,
    EmbeddingProviderKind,
    ProviderPolicy,
)
from codeatlas.generation.factory import build_answer_provider
from codeatlas.generation.ollama_provider import OllamaAnswerProvider
from codeatlas.generation.openai_provider import OpenAIAnswerProvider
from codeatlas.generation.providers import NoAnswerProvider


def _policy(
    kind: AnswerProviderKind,
    model: str | None = None,
    timeout: int | None = None,
) -> ProviderPolicy:
    return ProviderPolicy(
        repository_id="repo_1",
        embedding_provider=EmbeddingProviderKind.NONE,
        monthly_token_budget=None,
        per_run_token_budget=None,
        updated_at=datetime.now(UTC),
        answer_provider=kind,
        answer_model=model,
        answer_timeout_seconds=timeout,
    )


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test states its own environment.

    Without this the developer's real `.env` decides the outcome, which is how
    a suite passes on one machine and fails on another.
    """
    for variable in (
        "CODEATLAS_OLLAMA_ANSWER_MODEL",
        "CODEATLAS_OLLAMA_BASE_URL",
        "CODEATLAS_OPENAI_ANSWER_MODEL",
        "CODEATLAS_ANSWER_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(variable, raising=False)


def test_none_yields_the_no_op_provider() -> None:
    assert isinstance(
        build_answer_provider(_policy(AnswerProviderKind.NONE)), NoAnswerProvider
    )


def test_ollama_yields_an_ollama_provider_with_the_default_model() -> None:
    provider = build_answer_provider(_policy(AnswerProviderKind.OLLAMA))

    assert isinstance(provider, OllamaAnswerProvider)
    assert provider.model_id == "llama3.2:3b"


def test_openai_yields_an_openai_provider() -> None:
    provider = build_answer_provider(_policy(AnswerProviderKind.OPENAI))

    assert isinstance(provider, OpenAIAnswerProvider)
    assert provider.model_id == "gpt-4o-mini"


def test_a_stored_model_overrides_the_default() -> None:
    provider = build_answer_provider(
        _policy(AnswerProviderKind.OLLAMA, "llama3.1:8b")
    )

    assert provider.model_id == "llama3.1:8b"


def test_an_env_model_is_used_when_the_policy_stores_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEATLAS_OLLAMA_ANSWER_MODEL", "qwen2.5:14b")

    assert build_answer_provider(_policy(AnswerProviderKind.OLLAMA)).model_id == (
        "qwen2.5:14b"
    )


def test_the_stored_model_still_wins_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-repository choice beats the machine-wide default."""
    monkeypatch.setenv("CODEATLAS_OLLAMA_ANSWER_MODEL", "qwen2.5:14b")

    provider = build_answer_provider(
        _policy(AnswerProviderKind.OLLAMA, "llama3.1:8b")
    )

    assert provider.model_id == "llama3.1:8b"


def test_a_stored_timeout_overrides_the_built_in_bound() -> None:
    """A heavier model needs longer, and must be able to say so."""
    provider = build_answer_provider(
        _policy(AnswerProviderKind.OLLAMA, timeout=600)
    )

    assert isinstance(provider, OllamaAnswerProvider)
    # The bound is the subject of this test, so it is read directly rather than
    # inferred from behaviour that would need a slow provider to observe.
    assert provider._timeout == 600.0


def test_no_environment_variable_can_enable_a_none_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`.env` supplies identity, never consent."""
    monkeypatch.setenv("CODEATLAS_OLLAMA_ANSWER_MODEL", "qwen2.5:14b")
    monkeypatch.setenv("CODEATLAS_OPENAI_ANSWER_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    assert isinstance(
        build_answer_provider(_policy(AnswerProviderKind.NONE)), NoAnswerProvider
    )
