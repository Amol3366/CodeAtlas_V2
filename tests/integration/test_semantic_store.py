"""Semantic bookkeeping against real SQLite.

Migration `0010` stores *what was embedded and under which model*, never the
content itself. SQLite stays the system of record; LanceDB will hold derived,
rebuildable vectors. Every test here is about that split holding.

The provider policy tests are the privacy boundary in its smallest form: a
repository with no policy row must read as `none`, because the failure mode of
getting that wrong is source code leaving the machine.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.domain.errors import PathSafetyError
from codeatlas.domain.ids import embedding_key, embedding_namespace_id
from codeatlas.domain.semantic import (
    EmbeddingNamespace,
    EmbeddingProviderKind,
    EmbeddingRecord,
    EmbeddingStatus,
    NamespaceStatus,
    ProviderPolicy,
    ProviderUsage,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.semantic_stores import (
    EmbeddingStore,
    NamespaceStore,
    ProviderPolicyStore,
    ProviderUsageStore,
)

_NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def connection(tmp_path: Path):  # type: ignore[no-untyped-def]
    with connect(tmp_path / "db.sqlite") as conn:
        apply_migrations(conn)
        conn.execute(
            "INSERT INTO repositories"
            " (repository_id, display_name, canonical_root, created_at)"
            " VALUES ('repo_1', 'demo', 'C:/repos/demo', '2026-07-29T00:00:00Z')"
        )
        yield conn


def _namespace(model_id: str = "minilm", dimensions: int = 384) -> EmbeddingNamespace:
    return EmbeddingNamespace(
        namespace_id=embedding_namespace_id(model_id, dimensions, "l2_v1"),
        model_id=model_id,
        dimensions=dimensions,
        normalization_version="l2_v1",
        status=NamespaceStatus.ACTIVE,
        created_at=_NOW,
        activated_at=_NOW,
    )


# --- namespaces ----------------------------------------------------------


def test_a_namespace_round_trips(connection: sqlite3.Connection) -> None:
    store = NamespaceStore(connection)
    namespace = _namespace()

    store.add(namespace)

    assert store.get(namespace.namespace_id) == namespace


def test_one_similarity_space_cannot_be_registered_twice(
    connection: sqlite3.Connection,
) -> None:
    """Two rows for one model/dimensions/normalization would let two namespaces
    claim the same similarity space, and nothing downstream could tell which
    vectors belonged where."""
    store = NamespaceStore(connection)
    store.add(_namespace())

    with pytest.raises(sqlite3.IntegrityError):
        store.add(_namespace())


def test_exactly_one_namespace_answers_for_a_repository(
    connection: sqlite3.Connection,
) -> None:
    """The invariant is per repository, not global (ADR-0010).

    It used to be global, enforced by a unique index over `status = 'active'`.
    That contradicted the per-repository provider setting: with one repository
    already active, the second to opt in could only get a *shadow* namespace,
    and shadows answer nothing — so it embedded into a space no query read.
    The pointer replaces the index, and a repository still has exactly one.
    """
    store = NamespaceStore(connection)
    store.add(_namespace())
    bigger = EmbeddingNamespace(
        namespace_id=embedding_namespace_id("bigger", 768, "l2_v1"),
        model_id="bigger",
        dimensions=768,
        normalization_version="l2_v1",
        status=NamespaceStatus.ACTIVE,
        created_at=_NOW,
        activated_at=_NOW,
    )
    # Two active namespaces are now legal, because two repositories may sit on
    # different providers at the same time.
    store.add(bigger)

    store.set_for_repository("repo_1", _namespace().namespace_id, updated_at=_NOW)
    assert store.get_for_repository("repo_1") is not None
    assert store.get_for_repository("repo_1").namespace_id == _namespace().namespace_id  # type: ignore[union-attr]

    # Re-pointing replaces rather than accumulating: a repository cannot end up
    # being served by two spaces whose scores are not comparable.
    store.set_for_repository("repo_1", bigger.namespace_id, updated_at=_NOW)
    assert store.get_for_repository("repo_1").namespace_id == bigger.namespace_id  # type: ignore[union-attr]
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM repository_namespaces WHERE repository_id = ?",
            ("repo_1",),
        ).fetchone()[0]
        == 1
    )

    # A repository that has never opted in is served by nothing at all.
    assert store.get_for_repository("repo_absent") is None


# --- embedding records ---------------------------------------------------


def _record(
    content_hash: str,
    namespace_id: str,
    status: EmbeddingStatus = EmbeddingStatus.PENDING,
) -> EmbeddingRecord:
    return EmbeddingRecord(
        embedding_key=embedding_key(content_hash, "minilm", 384, "l2_v1"),
        namespace_id=namespace_id,
        content_hash=content_hash,
        status=status,
        created_at=_NOW,
        embedded_at=_NOW if status is EmbeddingStatus.EMBEDDED else None,
        failure_code=None,
    )


def test_an_embedding_record_round_trips(connection: sqlite3.Connection) -> None:
    namespace = _namespace()
    NamespaceStore(connection).add(namespace)
    store = EmbeddingStore(connection)
    record = _record("hash_a", namespace.namespace_id)

    store.upsert(record)

    assert store.get(record.embedding_key) == record


def test_recording_the_same_key_twice_is_idempotent(
    connection: sqlite3.Connection,
) -> None:
    """Re-indexing an unchanged tree must not fail and must not duplicate.

    Idempotent indexing is a Phase 2 guarantee; the embedding queue inherits
    it rather than becoming the one stage that breaks on a repeat run.
    """
    namespace = _namespace()
    NamespaceStore(connection).add(namespace)
    store = EmbeddingStore(connection)
    record = _record("hash_a", namespace.namespace_id)

    store.upsert(record)
    store.upsert(record)

    assert store.count(namespace.namespace_id) == 1


def test_marking_embedded_preserves_the_key_and_sets_the_time(
    connection: sqlite3.Connection,
) -> None:
    namespace = _namespace()
    NamespaceStore(connection).add(namespace)
    store = EmbeddingStore(connection)
    record = _record("hash_a", namespace.namespace_id)
    store.upsert(record)

    store.mark_embedded(record.embedding_key, embedded_at=_NOW)

    stored = store.get(record.embedding_key)
    assert stored is not None
    assert stored.status is EmbeddingStatus.EMBEDDED
    assert stored.embedded_at == _NOW


def test_a_failure_is_recorded_by_code_not_by_message(
    connection: sqlite3.Connection,
) -> None:
    """A provider error message can quote the payload it choked on. Storing a
    code keeps a diagnostic path open without storing content."""
    namespace = _namespace()
    NamespaceStore(connection).add(namespace)
    store = EmbeddingStore(connection)
    record = _record("hash_a", namespace.namespace_id)
    store.upsert(record)

    store.mark_failed(record.embedding_key, failure_code="PROVIDER_TIMEOUT")

    stored = store.get(record.embedding_key)
    assert stored is not None
    assert stored.status is EmbeddingStatus.FAILED
    assert stored.failure_code == "PROVIDER_TIMEOUT"


def test_missing_hashes_are_exactly_the_ones_not_yet_embedded(
    connection: sqlite3.Connection,
) -> None:
    """This query is the cost contract in executable form.

    A one-symbol edit must embed only changed unique content (blueprint 8.21).
    The queue is therefore derived by asking which content hashes have no
    embedded record — never by re-listing the corpus.
    """
    namespace = _namespace()
    NamespaceStore(connection).add(namespace)
    store = EmbeddingStore(connection)
    store.upsert(_record("unchanged", namespace.namespace_id, EmbeddingStatus.EMBEDDED))
    store.upsert(_record("in_flight", namespace.namespace_id, EmbeddingStatus.PENDING))

    missing = store.missing_content_hashes(
        namespace.namespace_id,
        content_hashes=("unchanged", "in_flight", "brand_new"),
    )

    assert missing == ("brand_new", "in_flight")


def test_a_failed_embedding_is_retried_rather_than_treated_as_covered(
    connection: sqlite3.Connection,
) -> None:
    namespace = _namespace()
    NamespaceStore(connection).add(namespace)
    store = EmbeddingStore(connection)
    store.upsert(_record("broken", namespace.namespace_id, EmbeddingStatus.FAILED))

    assert store.missing_content_hashes(
        namespace.namespace_id, content_hashes=("broken",)
    ) == ("broken",)


def test_the_same_content_in_two_namespaces_is_two_records(
    connection: sqlite3.Connection,
) -> None:
    """Reuse is per similarity space. Sharing across models is the exact error
    blueprint 4.7.6 forbids."""
    first = _namespace()
    second = _namespace(model_id="other", dimensions=768)
    namespaces = NamespaceStore(connection)
    namespaces.add(first)
    namespaces.add(
        EmbeddingNamespace(
            namespace_id=second.namespace_id,
            model_id=second.model_id,
            dimensions=second.dimensions,
            normalization_version=second.normalization_version,
            status=NamespaceStatus.SHADOW,
            created_at=_NOW,
            activated_at=None,
        )
    )
    store = EmbeddingStore(connection)

    store.upsert(
        EmbeddingRecord(
            embedding_key=embedding_key("shared", "minilm", 384, "l2_v1"),
            namespace_id=first.namespace_id,
            content_hash="shared",
            status=EmbeddingStatus.EMBEDDED,
            created_at=_NOW,
            embedded_at=_NOW,
            failure_code=None,
        )
    )

    assert store.missing_content_hashes(
        second.namespace_id, content_hashes=("shared",)
    ) == ("shared",)


def test_dropping_a_namespace_drops_its_records_only(
    connection: sqlite3.Connection,
) -> None:
    """Rollback after a migration removes the retired space and nothing else."""
    namespaces = NamespaceStore(connection)
    keep = _namespace()
    namespaces.add(keep)
    doomed = EmbeddingNamespace(
        namespace_id=embedding_namespace_id("doomed", 768, "l2_v1"),
        model_id="doomed",
        dimensions=768,
        normalization_version="l2_v1",
        status=NamespaceStatus.SHADOW,
        created_at=_NOW,
        activated_at=None,
    )
    namespaces.add(doomed)
    store = EmbeddingStore(connection)
    store.upsert(_record("a", keep.namespace_id))
    store.upsert(
        EmbeddingRecord(
            embedding_key=embedding_key("a", "doomed", 768, "l2_v1"),
            namespace_id=doomed.namespace_id,
            content_hash="a",
            status=EmbeddingStatus.PENDING,
            created_at=_NOW,
            embedded_at=None,
            failure_code=None,
        )
    )

    namespaces.delete(doomed.namespace_id)

    assert store.count(keep.namespace_id) == 1
    assert store.count(doomed.namespace_id) == 0


# --- provider policy: the privacy boundary -------------------------------


def test_a_repository_with_no_policy_row_transmits_nothing(
    connection: sqlite3.Connection,
) -> None:
    """The default must be `none`, and it must come from the *absence* of a row.

    A default that depended on a row being written correctly would make an
    upgrade, a failed insert, or a restored backup into a privacy incident.
    """
    policy = ProviderPolicyStore(connection).get("repo_1")

    assert policy.embedding_provider is EmbeddingProviderKind.NONE
    assert policy.monthly_token_budget is None


def test_an_unknown_repository_also_reads_as_none(
    connection: sqlite3.Connection,
) -> None:
    assert (
        ProviderPolicyStore(connection).get("repo_missing").embedding_provider
        is EmbeddingProviderKind.NONE
    )


def test_a_policy_round_trips(connection: sqlite3.Connection) -> None:
    store = ProviderPolicyStore(connection)
    policy = ProviderPolicy(
        repository_id="repo_1",
        embedding_provider=EmbeddingProviderKind.LOCAL,
        monthly_token_budget=1_000_000,
        per_run_token_budget=50_000,
        updated_at=_NOW,
    )

    store.set(policy)

    assert store.get("repo_1") == policy


def test_a_policy_can_be_changed_back_to_none(connection: sqlite3.Connection) -> None:
    """Opting out must be as easy as opting in, and must actually take effect."""
    store = ProviderPolicyStore(connection)
    store.set(
        ProviderPolicy(
            repository_id="repo_1",
            embedding_provider=EmbeddingProviderKind.OPENAI,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=_NOW,
        )
    )

    store.set(
        ProviderPolicy(
            repository_id="repo_1",
            embedding_provider=EmbeddingProviderKind.NONE,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=_NOW,
        )
    )

    assert (
        store.get("repo_1").embedding_provider is EmbeddingProviderKind.NONE
    )


def test_a_policy_for_an_unknown_repository_is_refused(
    connection: sqlite3.Connection,
) -> None:
    """Opt-in is per repository; a policy with no repository could only ever be
    applied to the wrong one."""
    with pytest.raises(sqlite3.IntegrityError):
        ProviderPolicyStore(connection).set(
            ProviderPolicy(
                repository_id="repo_missing",
                embedding_provider=EmbeddingProviderKind.OPENAI,
                monthly_token_budget=None,
                per_run_token_budget=None,
                updated_at=_NOW,
            )
        )


def test_deleting_a_repository_removes_its_opt_in(
    connection: sqlite3.Connection,
) -> None:
    """A re-registered path must not inherit the previous owner's opt-in."""
    store = ProviderPolicyStore(connection)
    store.set(
        ProviderPolicy(
            repository_id="repo_1",
            embedding_provider=EmbeddingProviderKind.OPENAI,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=_NOW,
        )
    )

    connection.execute("DELETE FROM repositories WHERE repository_id = 'repo_1'")

    assert store.get("repo_1").embedding_provider is EmbeddingProviderKind.NONE


# --- usage telemetry: counts, never content ------------------------------


def test_usage_is_recorded_and_totalled(connection: sqlite3.Connection) -> None:
    store = ProviderUsageStore(connection)
    for index in range(2):
        store.record(
            ProviderUsage(
                usage_id=f"use_{index}",
                repository_id="repo_1",
                operation="embed_documents",
                provider=EmbeddingProviderKind.OPENAI,
                model_id="text-embedding-3-small",
                request_count=1,
                token_count=500,
                latency_ms=120,
                outcome="ok",
                occurred_at=_NOW,
            )
        )

    assert store.tokens_since("repo_1", since=_NOW) == 1000


def test_usage_outside_the_window_is_not_counted(
    connection: sqlite3.Connection,
) -> None:
    """A monthly budget that counted last month's spend would refuse work that
    is within budget."""
    store = ProviderUsageStore(connection)
    store.record(
        ProviderUsage(
            usage_id="old",
            repository_id="repo_1",
            operation="embed_documents",
            provider=EmbeddingProviderKind.OPENAI,
            model_id="m",
            request_count=1,
            token_count=999,
            latency_ms=1,
            outcome="ok",
            occurred_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )

    assert store.tokens_since("repo_1", since=_NOW) == 0


def test_the_usage_table_has_no_column_that_could_hold_content(
    connection: sqlite3.Connection,
) -> None:
    """Section 17 and gate condition 6: telemetry records counts, tokens,
    latency, and outcome — never source, prompts, evidence, or answers. The
    cheapest way to keep that true is for there to be nowhere to put them."""
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(provider_usage)")
    }

    assert columns == {
        "usage_id",
        "repository_id",
        "operation",
        "provider",
        "model_id",
        "request_count",
        "token_count",
        "latency_ms",
        "outcome",
        "occurred_at",
    }


def test_the_embedding_table_stores_a_hash_and_never_the_text(
    connection: sqlite3.Connection,
) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(embeddings)")}

    assert columns == {
        "embedding_key",
        "namespace_id",
        "content_hash",
        "status",
        "created_at",
        "embedded_at",
        "failure_code",
    }


def test_a_namespace_id_that_escaped_the_root_cannot_be_stored(
    connection: sqlite3.Connection,
) -> None:
    """Defence in depth: identity rejects it, and so does the store, because a
    row written by any other path still becomes a directory name."""
    with pytest.raises(PathSafetyError):
        NamespaceStore(connection).add(
            EmbeddingNamespace(
                namespace_id="../escape",
                model_id="m",
                dimensions=1,
                normalization_version="v",
                status=NamespaceStatus.SHADOW,
                created_at=_NOW,
                activated_at=None,
            )
        )
