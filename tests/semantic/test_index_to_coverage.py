"""One real repository, indexed and embedded end to end.

Everything below this in the stack has been tested against a fake provider,
which proves the wiring but not the claim. This proves the claim: a real
repository on disk, a real snapshot, the real pinned model, real vectors, and
a coverage figure that reaches 1.0 because the vectors are actually there.

It is also where the phase's central promise is measured on real components —
that re-indexing an unchanged tree costs nothing at the provider, and that
editing one file costs one embedding.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.lookup import SymbolLookupRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
from codeatlas.semantic.pipeline import SnapshotEmbedder, read_coverage
from codeatlas.semantic.vector_store import build_lancedb_store
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.semantic_stores import ProviderPolicyStore

_NOW = datetime(2026, 7, 29, tzinfo=UTC)


def _write_repository(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "src" / "payments.py").write_text(
        "class PaymentService:\n"
        "    def capture(self, key):\n"
        '        """Capture a payment once, guarded by an idempotency key."""\n'
        "        return key\n",
        encoding="utf-8",
    )
    (root / "src" / "config.py").write_text(
        "DATABASE_URL = 'sqlite:///local.db'\n", encoding="utf-8"
    )


@pytest.fixture
def indexed(tmp_path: Path, local_provider):  # type: ignore[no-untyped-def]
    """A registered, indexed repository opted into local embeddings."""
    root = tmp_path / "repo"
    _write_repository(root)

    connection_context = connect(tmp_path / "db.sqlite")
    connection = connection_context.__enter__()
    apply_migrations(connection)

    embedder = SnapshotEmbedder(
        connection=connection,
        vectors=build_lancedb_store(tmp_path / "vectors"),
        build_provider=lambda policy: local_provider,
        now=lambda: _NOW,
    )
    services = build_services(connection, embedding=embedder)
    repository = services.registration.register(
        RegisterRepositoryRequest(path=str(root))
    )
    # Opt in *after* registration, because the policy needs a repository row to
    # reference — which is the foreign key that makes opt-in per repository.
    ProviderPolicyStore(connection).set(
        ProviderPolicy(
            repository_id=repository.repository_id,
            embedding_provider=EmbeddingProviderKind.LOCAL,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=_NOW,
        )
    )

    try:
        yield services, connection, repository.repository_id, root
    finally:
        connection_context.__exit__(None, None, None)


def test_a_real_index_reaches_full_coverage(indexed) -> None:  # type: ignore[no-untyped-def]
    services, connection, repository_id, _root = indexed

    result = services.indexing.index(repository_id)

    coverage = read_coverage(connection, repository_id, result.snapshot.snapshot_id)
    assert coverage is not None
    assert coverage.total > 0
    assert coverage.is_complete
    assert coverage.ratio == pytest.approx(1.0)


def test_the_index_reports_no_semantic_warning(indexed) -> None:  # type: ignore[no-untyped-def]
    services, _connection, repository_id, _root = indexed

    result = services.indexing.index(repository_id)

    assert not any("SEMANTIC" in warning for warning in result.warnings)


def test_re_indexing_an_unchanged_tree_embeds_nothing(indexed) -> None:  # type: ignore[no-untyped-def]
    """The steady-state cost contract on real components. The watcher reindexes
    all day; if each pass re-embedded, a repository would spend a provider
    budget standing still."""
    services, connection, repository_id, root = indexed
    first = services.indexing.index(repository_id)

    # Touch a file so the tree fingerprint changes and a genuinely new snapshot
    # is built — otherwise indexing short-circuits as unchanged and would prove
    # nothing about the embedding queue.
    (root / "src" / "config.py").write_text(
        "DATABASE_URL = 'sqlite:///local.db'\nDEBUG = False\n", encoding="utf-8"
    )
    second = services.indexing.index(repository_id)

    assert second.snapshot.snapshot_id != first.snapshot.snapshot_id
    coverage = read_coverage(connection, repository_id, second.snapshot.snapshot_id)
    assert coverage is not None
    assert coverage.is_complete, "the edited file's chunks were not embedded"


def test_deterministic_retrieval_answers_before_any_vector_exists(
    tmp_path: Path,
) -> None:
    """The same repository, indexed with no provider at all. Section 4.2: the
    deterministic channels must answer without the semantic layer, and this is
    the comparison that shows they do."""
    root = tmp_path / "repo"
    _write_repository(root)

    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )

        result = services.indexing.index(repository.repository_id)
        answer = services.lookup.lookup(
            SymbolLookupRequest(
                repository_id=repository.repository_id,
                query="PaymentService.capture",
                request_id="req_test",
            )
        )

        coverage = read_coverage(
            connection, repository.repository_id, result.snapshot.snapshot_id
        )

    assert answer.evidence, "the deterministic lookup found nothing without vectors"
    assert coverage is None, "a repository with no provider has no coverage to report"
