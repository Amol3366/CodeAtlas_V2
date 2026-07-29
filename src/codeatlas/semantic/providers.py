"""Embedding providers behind one interface.

ADR-0009 decision 1 fixes the shape: ``NoEmbeddingProvider`` is the default,
a pinned local sentence-transformers model is the opt-in that transmits
nothing, and OpenAI is the opt-in that transmits and therefore arrives later
with redaction and budgets around it (P7-07).

Two rules are load-bearing here rather than decorative:

**Nothing optional is imported at module scope.** A CLI invocation on a machine
without the extras must not pay a multi-second torch import, and a machine that
never installed them must still start. Imports happen inside the constructor
that needs them.

**A disabled provider refuses rather than returning zeros.** A zero vector is a
silent lie — every similarity equal, every candidate plausible — and it would
be indistinguishable from a working search returning poor results.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from codeatlas.domain.errors import ProviderDisabledError, ProviderUnavailableError
from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy

# Pinned, per ADR-0009 decision 4: the model ID is recorded on every embedding
# record, and changing it changes the similarity space. A float here would
# silently mix vectors from two models the first time the upstream default
# moved.
LOCAL_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
LOCAL_MODEL_DIMENSIONS = 384

# Bumped when the vector post-processing changes. It participates in the
# embedding key, so a change here invalidates the cache rather than leaving
# differently-normalized vectors in one space.
NORMALIZATION_VERSION = "l2_v1"


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turn text into vectors.

    Documents and queries are separate methods because some models require
    different prefixes or pooling for each, and a single method would force
    every caller to know which is which.
    """

    model_id: str
    dimensions: int
    normalization_version: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_queries(self, texts: list[str]) -> list[list[float]]: ...


class NoEmbeddingProvider:
    """The default. Present so that "no provider" is a value, not a ``None``.

    Callers that hold an ``EmbeddingProvider | None`` end up writing
    ``if provider is not None`` at every use, and one missed check becomes an
    ``AttributeError`` in a background job. Holding this instead means the
    disabled case is exercised by the same code path as the enabled one.
    """

    model_id = "none"
    # Zero, so this can never be given a namespace: `embedding_namespace_id`
    # rejects non-positive dimensions. The type system is not what stops a
    # disabled provider contributing vectors — this is.
    dimensions = 0
    normalization_version = "none"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise ProviderDisabledError(
            "Semantic search is not enabled for this repository."
        )

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        raise ProviderDisabledError(
            "Semantic search is not enabled for this repository."
        )


class LocalSentenceTransformerProvider:
    """A pinned local model. Transmits nothing, by construction.

    "By construction" is exact: there is no network client in this class and no
    configuration that could introduce one. That is what lets the ``local``
    setting be offered without the per-repository opt-in ceremony that
    ``openai`` requires.
    """

    model_id = LOCAL_MODEL_ID
    dimensions = LOCAL_MODEL_DIMENSIONS
    normalization_version = NORMALIZATION_VERSION

    def __init__(self, *, model_id: str = LOCAL_MODEL_ID) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:  # pragma: no cover - exercised without the extra
            raise ProviderUnavailableError(
                "Local embeddings need the 'semantic-local' extra. Install it "
                "with: uv sync --extra semantic-local",
                details={"provider": EmbeddingProviderKind.LOCAL.value},
            ) from error

        self.model_id = model_id
        # CPU is the product profile (the phase plan defers GPU explicitly), and
        # naming it beats inheriting whatever device happens to be visible: a
        # machine that silently used a GPU would produce different timings than
        # the ones recorded at the gate.
        self._model = SentenceTransformer(model_id, device="cpu")
        self.dimensions = _embedding_dimension(self._model)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        # This model uses one representation for both. Kept as a separate
        # method anyway so that a model which does not can be substituted
        # without changing a caller.
        return self._encode(texts)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            texts,
            # Cosine similarity over unit vectors is a dot product, and
            # normalizing at write time means the vector store never has to
            # know which metric was intended.
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in vector] for vector in vectors]


def build_embedding_provider(policy: ProviderPolicy) -> EmbeddingProvider:
    """Return the provider one repository's policy selects.

    The policy is the only input. There is deliberately no environment variable
    or global override that could enable a provider for a repository whose
    stored policy says ``none`` — Section 4.4 draws the boundary per
    repository, and a second way to switch it on is a second way to get it
    wrong.
    """
    kind = policy.embedding_provider
    if kind is EmbeddingProviderKind.NONE:
        return NoEmbeddingProvider()
    if kind is EmbeddingProviderKind.LOCAL:
        return LocalSentenceTransformerProvider()

    # OPENAI lands in P7-07 together with the redaction, budget, and opt-in
    # machinery it must never be usable without. Refusing until then is the
    # honest state: the setting is storable, so something must answer for it.
    raise ProviderUnavailableError(
        "The OpenAI embedding provider is not available in this build.",
        details={"provider": kind.value},
    )


def describe_available_providers() -> dict[EmbeddingProviderKind, bool]:
    """Which providers could run here, without constructing any of them.

    The settings surface has to *show* this. Discovering it by catching
    exceptions from a constructor would mean loading a multi-hundred-megabyte
    model to render a checkbox.
    """
    return {
        EmbeddingProviderKind.NONE: True,
        EmbeddingProviderKind.LOCAL: _module_is_importable("sentence_transformers"),
        EmbeddingProviderKind.OPENAI: False,
    }


def _embedding_dimension(model: object) -> int:
    """Ask the model how wide its vectors are, across the pinned range.

    sentence-transformers renamed this method mid-range (the extra allows
    ``>=5.6,<6``, and the rename lands inside that window). Reading the width
    from the model rather than trusting the constant matters: the width is what
    the namespace is built from, so a model whose real width disagreed with
    ``LOCAL_MODEL_DIMENSIONS`` must be caught rather than assumed.
    """
    for method in ("get_embedding_dimension", "get_sentence_embedding_dimension"):
        reader = getattr(model, method, None)
        if reader is not None:
            return int(reader())
    raise ProviderUnavailableError(
        "The installed sentence-transformers build does not report an "
        "embedding dimension.",
        details={"provider": EmbeddingProviderKind.LOCAL.value},
    )


def _module_is_importable(name: str) -> bool:
    """Whether a module could be imported, without importing it.

    ``find_spec`` reads metadata only. Actually importing to find out would
    defeat the point of the lazy import everywhere else in this module.
    """
    from importlib.util import find_spec

    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):
        return False
