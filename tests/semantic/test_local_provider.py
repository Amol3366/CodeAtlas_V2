"""The local provider against the real model.

Runs only when the `semantic-local` extra is installed (see conftest). Nothing
here is mocked: a mocked embedding provider would assert that the code calls a
function, which is not the question. The question is whether the vectors it
produces are the right shape, stable across runs, and ordered such that a
related snippet outranks an unrelated one — because everything downstream, from
the cache key to the uplift measurement, assumes all three.
"""

from __future__ import annotations

import math

import pytest

from codeatlas.semantic.providers import (
    LOCAL_MODEL_DIMENSIONS,
    NORMALIZATION_VERSION,
    LocalSentenceTransformerProvider,
)


def test_the_pinned_model_reports_the_pinned_width(
    local_provider: LocalSentenceTransformerProvider,
) -> None:
    """The declared width is what the namespace is built from. If the model's
    real width ever disagreed, vectors would be written into a space of a
    different size."""
    assert local_provider.dimensions == LOCAL_MODEL_DIMENSIONS
    assert local_provider.normalization_version == NORMALIZATION_VERSION


def test_a_vector_has_the_declared_width(
    local_provider: LocalSentenceTransformerProvider,
) -> None:
    [vector] = local_provider.embed_documents(["def capture(): ..."])

    assert len(vector) == LOCAL_MODEL_DIMENSIONS


def test_vectors_are_unit_length(
    local_provider: LocalSentenceTransformerProvider,
) -> None:
    """`l2_v1` is a claim recorded on every embedding record and baked into the
    embedding key. Cosine similarity over unit vectors is a dot product, and
    the vector store is built assuming that."""
    [vector] = local_provider.embed_documents(["some code"])

    magnitude = math.sqrt(sum(value * value for value in vector))
    assert magnitude == pytest.approx(1.0, abs=1e-4)


def test_the_same_text_embeds_identically_across_calls(
    local_provider: LocalSentenceTransformerProvider,
) -> None:
    """Content-addressed caching assumes determinism. A model that drifted
    between calls would make a cached vector disagree with a fresh one while
    both claimed the same key."""
    first = local_provider.embed_documents(["def capture(): ..."])
    second = local_provider.embed_documents(["def capture(): ..."])

    assert first == second


def test_related_text_scores_above_unrelated_text(
    local_provider: LocalSentenceTransformerProvider,
) -> None:
    """The weakest useful claim, and the one worth making: this model has some
    signal on code-shaped text. It is not a quality measurement — that is
    P7-06's uplift evaluation against the declared corpus."""
    [query] = local_provider.embed_queries(["how are payments captured"])
    related, unrelated = local_provider.embed_documents(
        [
            "def capture_payment(order): charge the customer for the order",
            "def parse_yaml_config(path): read configuration from disk",
        ]
    )

    assert _dot(query, related) > _dot(query, unrelated)


def test_embedding_nothing_returns_nothing(
    local_provider: LocalSentenceTransformerProvider,
) -> None:
    """An empty batch reaches the provider whenever a snapshot changed no
    chunk. It must not become a model call with a degenerate input."""
    assert local_provider.embed_documents([]) == []


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))
