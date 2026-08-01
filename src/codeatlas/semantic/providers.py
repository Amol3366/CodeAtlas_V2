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

from collections.abc import Callable
from functools import lru_cache
from typing import Protocol, runtime_checkable

from codeatlas.domain.errors import ProviderDisabledError, ProviderUnavailableError
from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
from codeatlas.settings.env_file import (
    OPENAI_DIMENSIONS_VARIABLE,
    OPENAI_MODEL_VARIABLE,
    configured_local_model,
    configured_openai_dimensions,
    configured_openai_model,
)

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


OPENAI_MODEL_ID = "text-embedding-3-small"
OPENAI_DIMENSIONS = 1536
OPENAI_TIMEOUT_SECONDS = 30.0
OPENAI_API_KEY_VARIABLE = "OPENAI_API_KEY"


def resolve_local_embedding_model() -> str:
    """Which sentence-transformers model the local provider loads.

    Safe to configure freely: the provider reads the true width from the model
    it loaded, and the namespace is derived from that. A different model simply
    means a different namespace.
    """
    return configured_local_model() or LOCAL_MODEL_ID


def resolve_openai_embedding_model() -> tuple[str, int]:
    """The configured OpenAI model and the width its vectors will have.

    The width cannot be discovered for free — asking OpenAI costs a billable
    call per construction — so a non-default model must declare it. Refusing is
    the only safe answer: `embedding_namespace_id` labels the namespace with
    this number, and a wrong label puts vectors of one width into a space
    describing another. That never raises; it just returns worse results,
    indefinitely.
    """
    model = configured_openai_model()
    width = configured_openai_dimensions()

    if model is None or model == OPENAI_MODEL_ID:
        if width is not None and width != OPENAI_DIMENSIONS:
            raise ProviderUnavailableError(
                f"{OPENAI_DIMENSIONS_VARIABLE} is {width}, but "
                f"{OPENAI_MODEL_ID} returns {OPENAI_DIMENSIONS}. CodeAtlas does "
                "not request shortened embeddings, so the two must agree.",
                details={
                    "provider": EmbeddingProviderKind.OPENAI.value,
                    "variable": OPENAI_DIMENSIONS_VARIABLE,
                },
            )
        return OPENAI_MODEL_ID, OPENAI_DIMENSIONS

    if width is None:
        raise ProviderUnavailableError(
            f"{OPENAI_MODEL_VARIABLE} is set to '{model}', so "
            f"{OPENAI_DIMENSIONS_VARIABLE} must also be set — CodeAtlas labels "
            "its vector index with that width and will not guess it. "
            "text-embedding-3-large is 3072.",
            details={
                "provider": EmbeddingProviderKind.OPENAI.value,
                "variable": OPENAI_DIMENSIONS_VARIABLE,
            },
        )
    return model, width


class OpenAIEmbeddingProvider:
    """The transmitting provider. Never construct one outside `ProviderFactory`.

    Reaching this class directly skips redaction, budgets, and telemetry, which
    is why the only supported route to it applies all three. It is public so it
    can be tested against a fake transport, not so it can be used.

    **The credential is never held here.** It is read once, handed to the
    client, and forgotten: an API key kept as an attribute reaches a `repr`, a
    traceback, and a diagnostic bundle, all of which Section 4.4 says it must
    not. It is read from the environment rather than the database because
    storing it in SQLite would put a live credential in every backup the
    product takes.
    """

    model_id = OPENAI_MODEL_ID
    dimensions = OPENAI_DIMENSIONS
    normalization_version = NORMALIZATION_VERSION

    def __init__(
        self,
        *,
        model_id: str = OPENAI_MODEL_ID,
        dimensions: int | None = None,
        client: object | None = None,
        timeout: float = OPENAI_TIMEOUT_SECONDS,
    ) -> None:
        self.model_id = model_id
        # Instance-level, because the class attribute describes the pinned
        # model only. The namespace is built from this number.
        self.dimensions = OPENAI_DIMENSIONS if dimensions is None else dimensions
        if client is not None:
            self._client = client
            return

        # The credential is checked before the import, and the order is chosen
        # so each real misconfiguration gets its own accurate message. Reading
        # an environment variable is free and needs no package; a user with a
        # key but no package is told to install it, and a user with the package
        # but no key is told to set it. Importing first would answer the second
        # user's problem with the first user's instruction.
        import os

        api_key = os.environ.get(OPENAI_API_KEY_VARIABLE)
        if not api_key:
            raise ProviderUnavailableError(
                f"The OpenAI provider needs {OPENAI_API_KEY_VARIABLE} in the "
                "environment.",
                details={"provider": EmbeddingProviderKind.OPENAI.value},
            )

        try:
            from openai import OpenAI
        except ImportError as error:  # pragma: no cover - exercised without extra
            raise ProviderUnavailableError(
                "The OpenAI provider needs the 'semantic-openai' extra. "
                "Install it with: uv sync --extra semantic-openai",
                details={"provider": EmbeddingProviderKind.OPENAI.value},
            ) from error
        # Handed over, not retained. `api_key` goes out of scope with this call.
        self._client = OpenAI(api_key=api_key, timeout=timeout)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            # A request with nothing in it is a billable no-op.
            return []
        response = self._client.embeddings.create(  # type: ignore[attr-defined]
            model=self.model_id, input=texts
        )
        return [_normalize(list(item.embedding)) for item in response.data]


def _normalize(vector: list[float]) -> list[float]:
    """Scale to unit length, matching every other provider.

    The vector store compares within a namespace by cosine similarity, and the
    local provider normalizes at write time. A provider that did not would put
    differently-scaled vectors into one similarity space.
    """
    length = sum(value * value for value in vector) ** 0.5
    if length == 0.0:
        return vector
    return [value / length for value in vector]


class ProviderFactory:
    """The only supported way to obtain a provider for a repository policy.

    It exists because governance needs a database connection — to read the
    month's spending and to record usage — and `build_embedding_provider` has
    none. Rather than widen that function's signature and leave an ungoverned
    path next to a governed one, the transmitting provider is reachable *only*
    from here, and only wrapped.
    """

    def __init__(
        self,
        connection: object,
        *,
        open_client: Callable[[], object] | None = None,
    ) -> None:
        self._connection = connection
        # Injection point for the fake transport the tests use. Left unset in
        # production, so a real client is built with a real credential.
        self._open_client = open_client

    def build(self, policy: ProviderPolicy) -> EmbeddingProvider:
        kind = policy.embedding_provider
        if kind is not EmbeddingProviderKind.OPENAI:
            return build_embedding_provider(policy)

        from codeatlas.semantic.governance import GovernedEmbeddingProvider

        client = self._open_client() if self._open_client is not None else None
        model_id, dimensions = resolve_openai_embedding_model()
        return GovernedEmbeddingProvider(
            inner=OpenAIEmbeddingProvider(
                client=client, model_id=model_id, dimensions=dimensions
            ),
            policy=policy,
            connection=self._connection,  # type: ignore[arg-type]
        )


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
        return _cached_local_provider(resolve_local_embedding_model())

    # OPENAI is deliberately unreachable from here, and stays that way. This
    # function has no database connection, so it cannot read a budget or record
    # usage — a provider returned from it would transmit ungoverned. `ProviderFactory`
    # is the supported route, and it wraps.
    raise ProviderUnavailableError(
        "The OpenAI embedding provider must be built through ProviderFactory, "
        "which applies redaction, budgets, and usage telemetry.",
        details={"provider": kind.value},
    )


def describe_available_providers() -> dict[EmbeddingProviderKind, bool]:
    """Which providers could run here, without constructing any of them.

    The settings surface has to *show* this. Discovering it by catching
    exceptions from a constructor would mean loading a multi-hundred-megabyte
    model to render a checkbox.
    """
    import os

    return {
        EmbeddingProviderKind.NONE: True,
        EmbeddingProviderKind.LOCAL: _module_is_importable("sentence_transformers"),
        # Both halves are required, and neither is sufficient. The package
        # decides whether the call *could* be made; the credential decides
        # whether it would succeed. Reporting the package alone would offer the
        # user a provider that fails at the first embed, and reporting `False`
        # unconditionally — which this did until the OpenAI provider shipped in
        # P7-07 — leaves the option permanently disabled in the web settings
        # form, which binds its radio to this flag.
        EmbeddingProviderKind.OPENAI: (
            _module_is_importable("openai")
            and bool(os.environ.get(OPENAI_API_KEY_VARIABLE))
        ),
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


@lru_cache(maxsize=1)
def _cached_local_provider(
    model_id: str = LOCAL_MODEL_ID,
) -> LocalSentenceTransformerProvider:
    """Reuse the local model inside one process.

    Loading sentence-transformers is the expensive part of local embeddings.
    Reconstructing it for every index and every semantic query makes the
    optional layer dominate latency even when only one content hash changed.
    """
    return LocalSentenceTransformerProvider(model_id=model_id)


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
