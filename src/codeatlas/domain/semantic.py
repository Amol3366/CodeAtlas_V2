"""Domain types for the optional semantic layer.

Nothing in this module is required for CodeAtlas to answer a question. That is
the phase's central constraint (AGENTS.md Section 4.3): exact, lexical, graph,
and Git retrieval must work with every provider disabled, so these types
describe an *addition* to a complete product rather than a dependency of it.

Two ideas carry most of the weight:

**A namespace is a similarity space.** Vectors produced by different models, or
at different dimensions, or under different normalization, are not comparable —
blueprint 4.7.6 — so they live in separate namespaces and their scores are
never compared. Exactly one namespace answers queries at a time; a second may
exist in shadow while a migration backfills it.

**An embedding record is bookkeeping, not data.** The vector lives in the
vector store; the record says which content, under which namespace, reached
which state. SQLite therefore remains the system of record and the vector store
holds only derived, rebuildable data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EmbeddingProviderKind(StrEnum):
    """Which embedding provider a repository has opted into.

    ``NONE`` is the default everywhere, and it is the value a missing policy
    row resolves to. ``LOCAL`` transmits nothing by construction. Only
    ``OPENAI`` sends repository-derived content off the machine, which is why
    it can never be reached by default or by omission.
    """

    NONE = "none"
    LOCAL = "local"
    OPENAI = "openai"

    @property
    def transmits_off_machine(self) -> bool:
        """Whether choosing this provider sends content to another party.

        Expressed as a property rather than an ``is OPENAI`` check at each call
        site so that adding a second remote provider cannot silently miss one
        of those checks.
        """
        return self is EmbeddingProviderKind.OPENAI


class AnswerProviderKind(StrEnum):
    """Which model, if any, writes a repository's answer prose.

    ``NONE`` is the default everywhere, and it is what a database written
    before answer generation existed upgrades to. ``OLLAMA`` runs on this
    machine and transmits nothing. Only ``OPENAI`` sends evidence excerpts off
    the machine, which is why it can never be reached by default or by
    omission.

    Deliberately not merged with `EmbeddingProviderKind`: they share two member
    names and nothing else. Retrieval and answering have different costs,
    different failure modes, and different providers — Ollama serves answers
    but is not an embedding backend here — so one enum would have members that
    are invalid for half its uses.
    """

    NONE = "none"
    OLLAMA = "ollama"
    OPENAI = "openai"

    @property
    def transmits_off_machine(self) -> bool:
        """Whether choosing this provider sends content to another party.

        A property rather than an ``is OPENAI`` check at each call site, so
        that adding a second remote provider cannot silently miss one.
        """
        return self is AnswerProviderKind.OPENAI


class EmbeddingStatus(StrEnum):
    """Where one piece of content sits in the embedding queue.

    ``FAILED`` is distinct from absent because the two need different
    treatment: absent content is queued, failed content is retried under a
    policy and reported. Neither counts as covered.
    """

    PENDING = "pending"
    EMBEDDED = "embedded"
    FAILED = "failed"


class NamespaceStatus(StrEnum):
    """Whether a similarity space answers queries, is being filled, or is kept
    only so a cutover can be undone."""

    ACTIVE = "active"
    SHADOW = "shadow"
    RETIRED = "retired"


class EmbeddingMigrationStatus(StrEnum):
    """Lifecycle of a shadow namespace migration."""

    BACKFILLING = "backfilling"
    READY_FOR_CUTOVER = "ready_for_cutover"
    ACTIVE = "active"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass(frozen=True)
class EmbeddingNamespace:
    """One similarity space, identified by what makes vectors comparable."""

    namespace_id: str
    model_id: str
    dimensions: int
    normalization_version: str
    status: NamespaceStatus
    created_at: datetime
    # Null while a namespace is shadow: it has been created and may be filling,
    # but it has never answered a query.
    activated_at: datetime | None


@dataclass(frozen=True)
class EmbeddingRecord:
    """That one content hash was embedded under one namespace.

    Carries no vector and no text. ``content_hash`` is a hash of content held
    elsewhere, which is what lets this table be joined for coverage without
    becoming a second copy of the repository.
    """

    embedding_key: str
    namespace_id: str
    content_hash: str
    status: EmbeddingStatus
    created_at: datetime
    embedded_at: datetime | None
    # A code, never a provider message: a message can quote the payload that
    # caused it, and payloads are repository content.
    failure_code: str | None


@dataclass(frozen=True)
class EmbeddingMigration:
    """A repository-specific request to move from one namespace to another."""

    migration_id: str
    repository_id: str
    source_namespace_id: str
    target_namespace_id: str
    status: EmbeddingMigrationStatus
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    rolled_back_at: datetime | None
    failure_code: str | None


@dataclass(frozen=True)
class ProviderPolicy:
    """One repository's provider opt-in and spending limits.

    The absence of a stored policy is meaningful and resolves to this type with
    ``NONE``. Making absence safe rather than undefined is what keeps a failed
    write, a partial restore, or an upgrade from becoming a disclosure.
    """

    repository_id: str
    embedding_provider: EmbeddingProviderKind
    # ``None`` means unlimited, which is only ever reachable for a provider
    # that does not transmit; the application layer enforces that pairing.
    monthly_token_budget: int | None
    per_run_token_budget: int | None
    updated_at: datetime
    # Answering is a separate decision from retrieving, with separate costs. A
    # repository may reasonably retrieve locally and answer remotely, or the
    # reverse, so this is its own field rather than a mode of the one above.
    answer_provider: AnswerProviderKind = AnswerProviderKind.NONE
    # ``None`` means "the configured default for this provider", which is what
    # lets a machine-wide default exist without every repository storing a copy.
    answer_model: str | None = None
    answer_timeout_seconds: int | None = None

    @property
    def transmits_off_machine(self) -> bool:
        """Whether *either* decision sends content to another party.

        Both, deliberately. Every existing caller asks this to decide whether a
        repository is transmitting at all, and answering "no" because only the
        answer provider transmits would be wrong in the reassuring direction.
        """
        return (
            self.embedding_provider.transmits_off_machine
            or self.answer_provider.transmits_off_machine
        )

    @property
    def embedding_transmits_off_machine(self) -> bool:
        """Whether the retrieval decision alone transmits."""
        return self.embedding_provider.transmits_off_machine

    @property
    def answer_transmits_off_machine(self) -> bool:
        """Whether the answering decision alone transmits."""
        return self.answer_provider.transmits_off_machine


@dataclass(frozen=True)
class ProviderUsage:
    """One provider interaction, reduced to what can be counted.

    Section 17 and the phase's gate condition 6: counts, tokens, latency, and
    outcome. There is deliberately no field that could hold a prompt, an
    excerpt, an answer, or a path.
    """

    usage_id: str
    repository_id: str
    operation: str
    provider: EmbeddingProviderKind
    model_id: str
    request_count: int
    token_count: int
    latency_ms: int
    outcome: str
    occurred_at: datetime
