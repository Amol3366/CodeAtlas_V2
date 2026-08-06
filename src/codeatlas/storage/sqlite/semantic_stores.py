"""Persistence for the optional semantic layer.

Separate from ``stores.py`` because the split is real: everything here is
optional, and a reader auditing what the deterministic product touches should
be able to see that this file is not in that path.

The stores are thin on purpose. Deciding *whether* to embed, which provider to
use, and whether a budget allows a request are application concerns; this layer
only records what happened, and enforces the invariants SQLite can enforce
better than code can — one active namespace, no policy without a repository, no
column that could hold content.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime

from codeatlas.domain.ids import validate_namespace_id
from codeatlas.domain.semantic import (
    AnswerProviderKind,
    EmbeddingMigration,
    EmbeddingMigrationStatus,
    EmbeddingNamespace,
    EmbeddingProviderKind,
    EmbeddingRecord,
    EmbeddingStatus,
    NamespaceStatus,
    ProviderPolicy,
    ProviderUsage,
)
from codeatlas.storage.sqlite.connection import from_utc_text, to_utc_text

# SQLite has a parameter limit; coverage queries are chunked below it so a
# large repository cannot turn one query into an error.
_MAX_PARAMETERS = 500


class NamespaceStore:
    """Similarity spaces and which one is current."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, namespace: EmbeddingNamespace) -> None:
        # Validated here as well as at construction because a namespace can
        # also arrive from a request body or a restored row, and this ID
        # becomes a directory name under the vectors root.
        validate_namespace_id(namespace.namespace_id)
        self._connection.execute(
            "INSERT INTO embedding_namespaces ("
            " namespace_id, model_id, dimensions, normalization_version, status,"
            " created_at, activated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                namespace.namespace_id,
                namespace.model_id,
                namespace.dimensions,
                namespace.normalization_version,
                namespace.status.value,
                to_utc_text(namespace.created_at),
                to_utc_text(namespace.activated_at) if namespace.activated_at else None,
            ),
        )

    def get(self, namespace_id: str) -> EmbeddingNamespace | None:
        row = self._connection.execute(
            "SELECT * FROM embedding_namespaces WHERE namespace_id = ?",
            (namespace_id,),
        ).fetchone()
        return _namespace_from_row(row) if row is not None else None

    def get_active(self) -> EmbeddingNamespace | None:
        """Any namespace currently marked active.

        Kept for the migration lifecycle, which reasons about namespace status
        directly. **Not** the way to find what answers a repository's queries:
        provider policy is per repository, so ask
        :meth:`get_for_repository`. Since migration `0012` more than one
        namespace may be active at a time, and this returns an arbitrary one of
        them.
        """
        row = self._connection.execute(
            "SELECT * FROM embedding_namespaces WHERE status = ?"
            " ORDER BY activated_at, namespace_id",
            (NamespaceStatus.ACTIVE.value,),
        ).fetchone()
        return _namespace_from_row(row) if row is not None else None

    def get_for_repository(self, repository_id: str) -> EmbeddingNamespace | None:
        """The namespace that answers this repository's queries.

        ``None`` is an ordinary state: it is what every repository looks like
        until a provider is enabled and something has embedded into it.
        """
        row = self._connection.execute(
            "SELECT namespaces.* FROM repository_namespaces AS pointer"
            " JOIN embedding_namespaces AS namespaces"
            "   ON namespaces.namespace_id = pointer.namespace_id"
            " WHERE pointer.repository_id = ?",
            (repository_id,),
        ).fetchone()
        return _namespace_from_row(row) if row is not None else None

    def set_for_repository(
        self, repository_id: str, namespace_id: str, *, updated_at: datetime
    ) -> None:
        """Point a repository at the namespace that answers for it.

        Idempotent, because indexing re-asserts the pointer on every run and a
        run that changed nothing must not be a write conflict.
        """
        validate_namespace_id(namespace_id)
        self._connection.execute(
            "INSERT INTO repository_namespaces"
            " (repository_id, namespace_id, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (repository_id) DO UPDATE SET"
            "  namespace_id = excluded.namespace_id,"
            "  updated_at = excluded.updated_at",
            (repository_id, namespace_id, to_utc_text(updated_at)),
        )

    def list_all(self) -> tuple[EmbeddingNamespace, ...]:
        rows = self._connection.execute(
            "SELECT * FROM embedding_namespaces ORDER BY created_at, namespace_id"
        ).fetchall()
        return tuple(_namespace_from_row(row) for row in rows)

    def set_status(self, namespace_id: str, status: NamespaceStatus) -> None:
        self._connection.execute(
            "UPDATE embedding_namespaces SET status = ? WHERE namespace_id = ?",
            (status.value, namespace_id),
        )

    def activate(self, namespace_id: str, *, activated_at: datetime) -> None:
        """Make one namespace active and retire any previous active one.

        The caller owns the transaction. Both updates must commit together or
        not at all, because two active namespaces would compare scores across
        models and zero active namespaces would silently disable semantic
        retrieval.
        """
        self._connection.execute(
            "UPDATE embedding_namespaces SET status = ? WHERE status = ?",
            (NamespaceStatus.RETIRED.value, NamespaceStatus.ACTIVE.value),
        )
        self._connection.execute(
            "UPDATE embedding_namespaces SET status = ?, activated_at = ?"
            " WHERE namespace_id = ?",
            (
                NamespaceStatus.ACTIVE.value,
                to_utc_text(activated_at),
                namespace_id,
            ),
        )

    def delete(self, namespace_id: str) -> None:
        """Remove a namespace and, by cascade, its embedding records.

        Used to abandon a shadow namespace or to close a rollback window. The
        vectors themselves are removed separately; losing them is recoverable
        because they are derived data.
        """
        self._connection.execute(
            "DELETE FROM embedding_namespaces WHERE namespace_id = ?",
            (namespace_id,),
        )


class EmbeddingStore:
    """The content-addressed embedding cache."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(self, record: EmbeddingRecord) -> None:
        """Record an embedding key, or leave an existing one as it is.

        Re-indexing an unchanged tree must be a no-op here. `DO NOTHING` rather
        than `DO UPDATE` because an existing row may already be `embedded`, and
        a repeat index run must not push it back to `pending` and re-embed
        content that has not changed.
        """
        self._connection.execute(
            "INSERT INTO embeddings ("
            " embedding_key, namespace_id, content_hash, status, created_at,"
            " embedded_at, failure_code"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (embedding_key) DO NOTHING",
            (
                record.embedding_key,
                record.namespace_id,
                record.content_hash,
                record.status.value,
                to_utc_text(record.created_at),
                to_utc_text(record.embedded_at) if record.embedded_at else None,
                record.failure_code,
            ),
        )

    def get(self, embedding_key: str) -> EmbeddingRecord | None:
        row = self._connection.execute(
            "SELECT * FROM embeddings WHERE embedding_key = ?",
            (embedding_key,),
        ).fetchone()
        return _embedding_from_row(row) if row is not None else None

    def mark_embedded(self, embedding_key: str, *, embedded_at: datetime) -> None:
        self._connection.execute(
            "UPDATE embeddings"
            " SET status = ?, embedded_at = ?, failure_code = NULL"
            " WHERE embedding_key = ?",
            (
                EmbeddingStatus.EMBEDDED.value,
                to_utc_text(embedded_at),
                embedding_key,
            ),
        )

    def mark_failed(self, embedding_key: str, *, failure_code: str) -> None:
        self._connection.execute(
            "UPDATE embeddings SET status = ?, failure_code = ?"
            " WHERE embedding_key = ?",
            (EmbeddingStatus.FAILED.value, failure_code, embedding_key),
        )

    def missing_content_hashes(
        self,
        namespace_id: str,
        *,
        content_hashes: Iterable[str],
    ) -> tuple[str, ...]:
        """Which of these hashes are not yet embedded in this namespace.

        This is the cost contract as a query. The embedding queue is derived by
        subtracting what is already covered from what the snapshot contains, so
        an edit costs the changed content and nothing else.

        Anything not `embedded` counts as missing — pending work may have died
        with a process, and failed work must be retried rather than mistaken
        for coverage.
        """
        wanted = list(dict.fromkeys(content_hashes))
        if not wanted:
            return ()

        covered: set[str] = set()
        for start in range(0, len(wanted), _MAX_PARAMETERS):
            batch = wanted[start : start + _MAX_PARAMETERS]
            placeholders = ", ".join("?" for _ in batch)
            rows = self._connection.execute(
                "SELECT content_hash FROM embeddings"
                f" WHERE namespace_id = ? AND status = ?"
                f" AND content_hash IN ({placeholders})",
                (namespace_id, EmbeddingStatus.EMBEDDED.value, *batch),
            ).fetchall()
            covered.update(row[0] for row in rows)

        return tuple(sorted(hash_ for hash_ in wanted if hash_ not in covered))

    def count(self, namespace_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM embeddings WHERE namespace_id = ?",
            (namespace_id,),
        ).fetchone()
        return int(row[0])

    def count_embedded(self, namespace_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM embeddings WHERE namespace_id = ? AND status = ?",
            (namespace_id, EmbeddingStatus.EMBEDDED.value),
        ).fetchone()
        return int(row[0])


class EmbeddingMigrationStore:
    """Repository-specific model migration records."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(self, migration: EmbeddingMigration) -> None:
        self._connection.execute(
            "INSERT INTO embedding_migrations ("
            " migration_id, repository_id, source_namespace_id,"
            " target_namespace_id, status, created_at, updated_at,"
            " activated_at, rolled_back_at, failure_code"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (repository_id, source_namespace_id, target_namespace_id)"
            " DO UPDATE SET"
            " status = excluded.status,"
            " updated_at = excluded.updated_at,"
            " activated_at = COALESCE(embedding_migrations.activated_at,"
            "                         excluded.activated_at),"
            " rolled_back_at = COALESCE(embedding_migrations.rolled_back_at,"
            "                          excluded.rolled_back_at),"
            " failure_code = excluded.failure_code",
            (
                migration.migration_id,
                migration.repository_id,
                migration.source_namespace_id,
                migration.target_namespace_id,
                migration.status.value,
                to_utc_text(migration.created_at),
                to_utc_text(migration.updated_at),
                (
                    to_utc_text(migration.activated_at)
                    if migration.activated_at
                    else None
                ),
                (
                    to_utc_text(migration.rolled_back_at)
                    if migration.rolled_back_at
                    else None
                ),
                migration.failure_code,
            ),
        )

    def get(self, migration_id: str) -> EmbeddingMigration | None:
        row = self._connection.execute(
            "SELECT * FROM embedding_migrations WHERE migration_id = ?",
            (migration_id,),
        ).fetchone()
        return _migration_from_row(row) if row is not None else None

    def set_status(
        self,
        migration_id: str,
        *,
        status: EmbeddingMigrationStatus,
        updated_at: datetime,
        activated_at: datetime | None = None,
        rolled_back_at: datetime | None = None,
        failure_code: str | None = None,
    ) -> None:
        self._connection.execute(
            "UPDATE embedding_migrations"
            " SET status = ?, updated_at = ?, activated_at = COALESCE(?, activated_at),"
            " rolled_back_at = COALESCE(?, rolled_back_at), failure_code = ?"
            " WHERE migration_id = ?",
            (
                status.value,
                to_utc_text(updated_at),
                to_utc_text(activated_at) if activated_at else None,
                to_utc_text(rolled_back_at) if rolled_back_at else None,
                failure_code,
                migration_id,
            ),
        )


class ProviderPolicyStore:
    """Per-repository provider opt-in.

    The one rule that matters: a repository with no row transmits nothing.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, repository_id: str) -> ProviderPolicy:
        """Return the stored policy, or the safe default when none exists.

        Never returns ``None``. A caller forced to handle an optional policy
        would eventually handle it as "unset, so carry on", and carrying on is
        the wrong default when the question is whether to send source code to
        a third party.
        """
        row = self._connection.execute(
            "SELECT * FROM repository_provider_policy WHERE repository_id = ?",
            (repository_id,),
        ).fetchone()
        if row is None:
            return ProviderPolicy(
                repository_id=repository_id,
                embedding_provider=EmbeddingProviderKind.NONE,
                monthly_token_budget=None,
                per_run_token_budget=None,
                updated_at=_EPOCH,
            )
        return _policy_of(row)

    def set(self, policy: ProviderPolicy) -> None:
        self._connection.execute(
            "INSERT INTO repository_provider_policy ("
            " repository_id, embedding_provider, monthly_token_budget,"
            " per_run_token_budget, updated_at, answer_provider, answer_model,"
            " answer_timeout_seconds, embedding_model"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (repository_id) DO UPDATE SET"
            " embedding_provider = excluded.embedding_provider,"
            " monthly_token_budget = excluded.monthly_token_budget,"
            " per_run_token_budget = excluded.per_run_token_budget,"
            " updated_at = excluded.updated_at,"
            " answer_provider = excluded.answer_provider,"
            " answer_model = excluded.answer_model,"
            " answer_timeout_seconds = excluded.answer_timeout_seconds,"
            " embedding_model = excluded.embedding_model",
            (
                policy.repository_id,
                policy.embedding_provider.value,
                policy.monthly_token_budget,
                policy.per_run_token_budget,
                to_utc_text(policy.updated_at),
                policy.answer_provider.value,
                policy.answer_model,
                policy.answer_timeout_seconds,
                policy.embedding_model,
            ),
        )

    def list_opted_in(self) -> tuple[ProviderPolicy, ...]:
        """Every repository that has opted into any provider.

        Exists so that "what is currently able to transmit?" is one query with
        one answer, rather than something a support conversation reconstructs.

        Both decisions are checked. A repository answering through OpenAI
        transmits evidence excerpts even when its embedding provider is
        ``none``, and a query that missed it would under-report exactly the
        thing it exists to report.
        """
        rows = self._connection.execute(
            "SELECT * FROM repository_provider_policy"
            " WHERE embedding_provider <> ? OR answer_provider <> ?"
            " ORDER BY repository_id",
            (EmbeddingProviderKind.NONE.value, AnswerProviderKind.NONE.value),
        ).fetchall()
        return tuple(_policy_of(row) for row in rows)


class ProviderUsageStore:
    """Counts, tokens, latency, and outcome. Nothing else fits."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def record(self, usage: ProviderUsage) -> None:
        self._connection.execute(
            "INSERT INTO provider_usage ("
            " usage_id, repository_id, operation, provider, model_id,"
            " request_count, token_count, latency_ms, outcome, occurred_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                usage.usage_id,
                usage.repository_id,
                usage.operation,
                usage.provider.value,
                usage.model_id,
                usage.request_count,
                usage.token_count,
                usage.latency_ms,
                usage.outcome,
                to_utc_text(usage.occurred_at),
            ),
        )

    def tokens_since(self, repository_id: str, *, since: datetime) -> int:
        """Tokens spent by this repository at or after an instant.

        Timestamps are lexicographically ordered UTC text, so the comparison is
        a plain string comparison and the index on
        ``(repository_id, occurred_at)`` serves it directly.
        """
        row = self._connection.execute(
            "SELECT COALESCE(SUM(token_count), 0) FROM provider_usage"
            " WHERE repository_id = ? AND occurred_at >= ?",
            (repository_id, to_utc_text(since)),
        ).fetchone()
        return int(row[0])


_EPOCH = datetime.fromisoformat("1970-01-01T00:00:00+00:00")


def _policy_of(row: sqlite3.Row) -> ProviderPolicy:
    """Map one policy row.

    Shared by `get` and `list_opted_in` rather than written twice: the two
    drifted apart once already, and a read path that silently omits a field is
    the kind of bug that only shows up as a setting mysteriously resetting.
    """
    return ProviderPolicy(
        repository_id=row["repository_id"],
        embedding_provider=EmbeddingProviderKind(row["embedding_provider"]),
        monthly_token_budget=row["monthly_token_budget"],
        per_run_token_budget=row["per_run_token_budget"],
        updated_at=from_utc_text(row["updated_at"]),
        answer_provider=AnswerProviderKind(row["answer_provider"]),
        answer_model=row["answer_model"],
        answer_timeout_seconds=row["answer_timeout_seconds"],
        embedding_model=row["embedding_model"],
    )


def _namespace_from_row(row: sqlite3.Row) -> EmbeddingNamespace:
    return EmbeddingNamespace(
        namespace_id=row["namespace_id"],
        model_id=row["model_id"],
        dimensions=int(row["dimensions"]),
        normalization_version=row["normalization_version"],
        status=NamespaceStatus(row["status"]),
        created_at=from_utc_text(row["created_at"]),
        activated_at=(
            from_utc_text(row["activated_at"])
            if row["activated_at"] is not None
            else None
        ),
    )


def _embedding_from_row(row: sqlite3.Row) -> EmbeddingRecord:
    return EmbeddingRecord(
        embedding_key=row["embedding_key"],
        namespace_id=row["namespace_id"],
        content_hash=row["content_hash"],
        status=EmbeddingStatus(row["status"]),
        created_at=from_utc_text(row["created_at"]),
        embedded_at=(
            from_utc_text(row["embedded_at"])
            if row["embedded_at"] is not None
            else None
        ),
        failure_code=row["failure_code"],
    )


def _migration_from_row(row: sqlite3.Row) -> EmbeddingMigration:
    return EmbeddingMigration(
        migration_id=row["migration_id"],
        repository_id=row["repository_id"],
        source_namespace_id=row["source_namespace_id"],
        target_namespace_id=row["target_namespace_id"],
        status=EmbeddingMigrationStatus(row["status"]),
        created_at=from_utc_text(row["created_at"]),
        updated_at=from_utc_text(row["updated_at"]),
        activated_at=(
            from_utc_text(row["activated_at"])
            if row["activated_at"] is not None
            else None
        ),
        rolled_back_at=(
            from_utc_text(row["rolled_back_at"])
            if row["rolled_back_at"] is not None
            else None
        ),
        failure_code=row["failure_code"],
    )
