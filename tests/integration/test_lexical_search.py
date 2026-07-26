"""Lexical and exact search through the application service.

The fixture indexes for real, so these tests exercise the same path a user
does: register, index, search.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import Derivation, QueryResponse
from codeatlas.domain.errors import (
    RepositoryNotFoundError,
    SearchQueryError,
    SnapshotNotReadyError,
)
from codeatlas.retrieval.lexical import MAX_SEARCH_RESULTS, SearchRequest
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


@dataclass
class Indexed:
    services: ApplicationServices
    connection: sqlite3.Connection
    repository_id: str
    root: Path


@pytest.fixture()
def indexed(tmp_path: Path, sample_repo: Path) -> Iterator[Indexed]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        services.indexing.index(repository.repository_id)
        harness = Indexed(
            services=services,
            connection=connection,
            repository_id=repository.repository_id,
            root=sample_repo,
        )
        yield harness


def test_content_search_finds_a_term_inside_a_function_body(
    indexed: Indexed,
) -> None:
    response = indexed.services.search.search_text(
        SearchRequest(indexed.repository_id, "claim", "req-1")
    )

    assert response.evidence
    assert any(
        item.file_path == "src/payments/service.py" for item in response.evidence
    )


def test_lexical_hits_are_labeled_as_heuristic(indexed: Indexed) -> None:
    response = indexed.services.search.search_text(
        SearchRequest(indexed.repository_id, "idempotencystore", "req-2")
    )

    assert response.evidence
    assert all(
        item.derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC
        for item in response.evidence
    )
    assert all(
        claim.derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC
        for claim in response.answer.claims
    )


def test_file_search_finds_a_path_fragment(indexed: Indexed) -> None:
    response = indexed.services.search.search_files(
        SearchRequest(indexed.repository_id, "idempotency", "req-3")
    )

    assert [item.file_path for item in response.evidence] == [
        "src/payments/idempotency.py"
    ]


def test_exact_symbol_match_is_never_displaced_by_a_lexical_hit(
    indexed: Indexed,
) -> None:
    response = indexed.services.search.search_symbols(
        SearchRequest(indexed.repository_id, "capture", "req-4")
    )

    assert response.evidence[0].symbol == "PaymentService.capture"
    assert response.answer.claims[0].derivation is Derivation.STATIC_RESOLVED
    assert all(
        item.derivation is Derivation.DETERMINISTIC for item in response.evidence
    )


def test_symbol_search_falls_back_to_lexical_when_exact_finds_nothing(
    indexed: Indexed,
) -> None:
    response = indexed.services.search.search_symbols(
        SearchRequest(indexed.repository_id, "paymentservice.cap", "req-5")
    )

    assert response.answer.claims == [] or all(
        claim.derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC
        for claim in response.answer.claims
    )


def test_no_match_abstains_rather_than_failing(indexed: Indexed) -> None:
    response = indexed.services.search.search_text(
        SearchRequest(indexed.repository_id, "zzzznotpresent", "req-6")
    )

    assert response.evidence == []
    assert response.answer.claims == []
    assert "NO_LEXICAL_MATCH" in response.warnings


def test_an_unusable_query_is_rejected(indexed: Indexed) -> None:
    with pytest.raises(SearchQueryError):
        indexed.services.search.search_text(
            SearchRequest(indexed.repository_id, "***", "req-7")
        )


def test_an_unknown_repository_is_rejected(indexed: Indexed) -> None:
    with pytest.raises(RepositoryNotFoundError):
        indexed.services.search.search_text(
            SearchRequest("repo_missing", "capture", "req-8")
        )


def test_a_repository_without_a_snapshot_is_rejected(
    tmp_path: Path, sample_repo: Path
) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        with pytest.raises(SnapshotNotReadyError):
            services.search.search_text(
                SearchRequest(repository.repository_id, "capture", "req-9")
            )


def test_the_limit_is_enforced(indexed: Indexed) -> None:
    response = indexed.services.search.search_text(
        SearchRequest(indexed.repository_id, "payments", "req-10", limit=1)
    )
    assert len(response.evidence) <= 1


def test_the_limit_is_clamped_to_the_maximum(indexed: Indexed) -> None:
    response = indexed.services.search.search_text(
        SearchRequest(indexed.repository_id, "payments", "req-11", limit=10_000)
    )
    assert len(response.evidence) <= MAX_SEARCH_RESULTS


def test_a_drifted_file_yields_no_evidence_and_a_warning(indexed: Indexed) -> None:
    (indexed.root / "src" / "payments" / "service.py").write_text(
        "# rewritten after indexing\n", encoding="utf-8"
    )

    response = indexed.services.search.search_text(
        SearchRequest(indexed.repository_id, "claim", "req-12")
    )

    assert all(
        item.file_path != "src/payments/service.py" for item in response.evidence
    )
    assert "EVIDENCE_STALE_FILE_CONTENT" in response.warnings


def test_results_never_come_from_a_superseded_snapshot(indexed: Indexed) -> None:
    before = indexed.services.search.search_text(
        SearchRequest(indexed.repository_id, "idempotencystore", "req-13")
    )
    assert before.evidence

    (indexed.root / "src" / "payments" / "service.py").write_text(
        "class PaymentService:\n    pass\n", encoding="utf-8"
    )
    indexed.services.indexing.index(indexed.repository_id)

    after = indexed.services.search.search_text(
        SearchRequest(indexed.repository_id, "idempotencystore", "req-14")
    )

    assert all(
        item.file_path != "src/payments/service.py" for item in after.evidence
    )
    active = indexed.services.indexing.get_active_snapshot(indexed.repository_id)
    assert active is not None
    assert after.snapshot.snapshot_id == active.snapshot_id


def test_every_response_is_bound_to_the_active_snapshot(indexed: Indexed) -> None:
    active = indexed.services.indexing.get_active_snapshot(indexed.repository_id)
    assert active is not None

    for response in (
        indexed.services.search.search_text(
            SearchRequest(indexed.repository_id, "claim", "req-15")
        ),
        indexed.services.search.search_files(
            SearchRequest(indexed.repository_id, "payments", "req-16")
        ),
        indexed.services.search.search_symbols(
            SearchRequest(indexed.repository_id, "capture", "req-17")
        ),
    ):
        assert isinstance(response, QueryResponse)
        assert response.snapshot.snapshot_id == active.snapshot_id
        assert all(
            item.snapshot_id == active.snapshot_id for item in response.evidence
        )
