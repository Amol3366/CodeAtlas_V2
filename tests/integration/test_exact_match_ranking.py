"""An exact name match outranks a merely-lexical one (ADR-0026).

Ranking was pure BM25, which scores by term density, so a short parent block
out-scored the leaf a caller actually asked for: searching `features.audit`
returned `features` first. Whether the leaf or the parent won came down to how
many other lines the parent happened to contain, which is not a property anyone
should be relying on.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.retrieval.lexical import SearchRequest
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

# `features` is a two-line block and `service` a three-line one. Under BM25
# alone the short block wins and the long one loses, which is exactly the
# inconsistency this file pins down.
SETTINGS = "service:\n  name: sample\n  port: 8080\nfeatures:\n  audit: true\n"


@pytest.fixture()
def indexed(tmp_path: Path) -> Iterator[tuple[object, str]]:
    root = tmp_path / "cfg_repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "settings.yaml").write_text(SETTINGS, encoding="utf-8")
    (root / "README.md").write_text("# Sample\n", encoding="utf-8")

    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        services.indexing.index(repository.repository_id)
        yield services, repository.repository_id


def _symbols(services: object, repository_id: str, query: str) -> list[str]:
    response = services.search.search_text(  # type: ignore[attr-defined]
        SearchRequest(repository_id, query, "req-rank")
    )
    return [item.symbol for item in response.evidence if item.symbol]


def test_an_exact_key_outranks_its_own_parent(
    indexed: tuple[object, str],
) -> None:
    services, repository_id = indexed

    symbols = _symbols(services, repository_id, "features.audit")

    assert symbols[0] == "features.audit"
    assert "features" in symbols, "the parent is still a result, just not first"


def test_the_longer_block_ranks_the_same_way(
    indexed: tuple[object, str],
) -> None:
    """`service.port` already won under BM25; it must not regress.

    The defect was that the outcome depended on the parent's length. Both cases
    resolving to the leaf is the point -- one passing is not evidence of a rule.
    """
    services, repository_id = indexed

    symbols = _symbols(services, repository_id, "service.port")

    assert symbols[0] == "service.port"


def test_a_query_with_no_exact_match_keeps_its_relevance_order(
    indexed: tuple[object, str],
) -> None:
    """Promotion applies only to an exact name match.

    A search for ordinary words must still be ranked by relevance; if this
    started reordering general queries it would be a retrieval change wearing a
    bug fix's clothes.
    """
    services, repository_id = indexed

    symbols = _symbols(services, repository_id, "sample")

    assert symbols, "the query must still match something"
    assert "sample" not in symbols, "no symbol is named `sample`, so nothing is exact"
