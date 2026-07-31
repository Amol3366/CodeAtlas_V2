"""The provider seam, with no provider installed.

Every test here runs in the default environment — no torch, no lancedb, no
openai — because that is the environment gate condition 2 is about. If any of
these needed an optional package, the thing being asserted would no longer be
"a non-opted-in installation behaves like Phases 0-6".
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import find_spec

import pytest

from codeatlas.domain.errors import ProviderDisabledError, ProviderUnavailableError
from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
from codeatlas.semantic.providers import (
    NoEmbeddingProvider,
    build_embedding_provider,
    describe_available_providers,
)

_NOW = datetime(2026, 7, 29, tzinfo=UTC)


def _policy(kind: EmbeddingProviderKind) -> ProviderPolicy:
    return ProviderPolicy(
        repository_id="repo_1",
        embedding_provider=kind,
        monthly_token_budget=None,
        per_run_token_budget=None,
        updated_at=_NOW,
    )


def test_the_default_policy_yields_the_no_op_provider() -> None:
    provider = build_embedding_provider(_policy(EmbeddingProviderKind.NONE))

    assert isinstance(provider, NoEmbeddingProvider)


def test_the_no_op_provider_refuses_rather_than_returning_zeros() -> None:
    """A zero vector would be a silent lie: every similarity equal, every
    result plausible. Refusing is what lets the caller fall back."""
    provider = NoEmbeddingProvider()

    with pytest.raises(ProviderDisabledError):
        provider.embed_documents(["anything"])
    with pytest.raises(ProviderDisabledError):
        provider.embed_queries(["anything"])


def test_the_no_op_provider_never_claims_a_similarity_space() -> None:
    """It has no model and no dimensions, so it cannot be given a namespace —
    which is the structural reason it can never contribute a vector."""
    provider = NoEmbeddingProvider()

    assert provider.dimensions == 0
    assert provider.model_id == "none"


def test_building_a_local_provider_without_the_extra_names_the_extra() -> None:
    """The failure a user actually hits: they switched the setting on before
    installing anything. It must say what to install, and it must not be an
    ImportError surfacing from three frames down.
    """
    if find_spec("sentence_transformers") is not None:
        pytest.skip("semantic-local is installed in this environment")

    with pytest.raises(ProviderUnavailableError) as raised:
        build_embedding_provider(_policy(EmbeddingProviderKind.LOCAL))

    assert "semantic-local" in str(raised.value)


def test_an_unavailable_provider_is_retryable() -> None:
    """Installing the extra fixes it, so a client that distinguishes retryable
    from permanent should offer the retry."""
    if find_spec("sentence_transformers") is not None:
        pytest.skip("semantic-local is installed in this environment")

    with pytest.raises(ProviderUnavailableError) as raised:
        build_embedding_provider(_policy(EmbeddingProviderKind.LOCAL))

    assert raised.value.retryable is True


def test_importing_the_provider_module_pulls_in_nothing_optional() -> None:
    """The lazy import is the whole mechanism. If `providers` imported
    sentence_transformers at module scope, every CLI invocation on every
    installation would pay a multi-second import — and a machine without the
    extra could not start at all.
    """
    if find_spec("sentence_transformers") is not None:
        pytest.skip("default-environment assertion; semantic-local is installed")

    import sys

    assert "sentence_transformers" not in sys.modules
    assert "torch" not in sys.modules


def test_availability_can_be_reported_without_raising() -> None:
    """The settings surface needs to *show* what is installed, which it cannot
    do by catching exceptions from a constructor."""
    available = describe_available_providers()

    assert available[EmbeddingProviderKind.NONE] is True
    # In the default environment neither extra is installed. This asserts the
    # probe works, not that the answer is always False.
    assert isinstance(available[EmbeddingProviderKind.LOCAL], bool)
    assert isinstance(available[EmbeddingProviderKind.OPENAI], bool)


def test_a_disabled_provider_is_not_retryable() -> None:
    """Nothing to retry: the user turned it off. Distinguishing this from
    unavailability is what stops a client from looping on a deliberate
    setting."""
    provider = NoEmbeddingProvider()

    with pytest.raises(ProviderDisabledError) as raised:
        provider.embed_documents(["x"])

    assert raised.value.retryable is False
