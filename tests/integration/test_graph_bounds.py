"""Traversal against a real indexed snapshot and a real SQLite relation store."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import RelationKind
from codeatlas.domain.errors import InvalidRequestError
from codeatlas.retrieval.graph import BoundedGraphTraversal, TraversalLimits
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import FileStore, RelationStore, SymbolStore

CHAIN = {
    "src/a.py": "def alpha():\n    return beta()\n",
    "src/b.py": "def beta():\n    return gamma()\n",
    "src/c.py": "def gamma():\n    return 1\n",
}


@pytest.fixture()
def indexed(tmp_path: Path) -> Iterator[tuple[sqlite3.Connection, str]]:
    root = tmp_path / "chain"
    (root / "src").mkdir(parents=True)
    for relative_path, source in CHAIN.items():
        (root / relative_path).write_text(source, encoding="utf-8")

    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        result = services.indexing.index(repository.repository_id)
        yield connection, result.snapshot.snapshot_id


def _traversal(
    connection: sqlite3.Connection, snapshot_id: str
) -> BoundedGraphTraversal:
    paths = {
        record.file_id: record.relative_path
        for record in FileStore(connection).list_for_snapshot(snapshot_id)
    }
    return BoundedGraphTraversal(RelationStore(connection), paths_by_file=paths)


def _symbol_id(
    connection: sqlite3.Connection, snapshot_id: str, qualified_name: str
) -> str:
    for symbol in SymbolStore(connection).list_for_snapshot(snapshot_id):
        if symbol.qualified_name == qualified_name:
            return symbol.symbol_id
    raise AssertionError(f"no symbol named {qualified_name}")


def test_traversal_follows_a_real_cross_file_call_chain(
    indexed: tuple[sqlite3.Connection, str],
) -> None:
    connection, snapshot_id = indexed
    alpha = _symbol_id(connection, snapshot_id, "alpha")

    result = _traversal(connection, snapshot_id).expand(
        snapshot_id,
        [alpha],
        "outgoing",
        kinds=[RelationKind.CALLS],
        limits=TraversalLimits(max_depth=3),
    )

    reached = {edge.target_hint for edge in result.edges}
    assert {"beta", "gamma"} <= reached


def test_depth_one_stops_at_the_first_hop(
    indexed: tuple[sqlite3.Connection, str],
) -> None:
    connection, snapshot_id = indexed
    alpha = _symbol_id(connection, snapshot_id, "alpha")

    result = _traversal(connection, snapshot_id).expand(
        snapshot_id,
        [alpha],
        "outgoing",
        kinds=[RelationKind.CALLS],
        limits=TraversalLimits(max_depth=1),
    )

    assert {edge.target_hint for edge in result.edges} == {"beta"}
    assert "depth" in result.truncated_by


def test_incoming_finds_the_caller_of_a_real_symbol(
    indexed: tuple[sqlite3.Connection, str],
) -> None:
    connection, snapshot_id = indexed
    gamma = _symbol_id(connection, snapshot_id, "gamma")

    result = _traversal(connection, snapshot_id).expand(
        snapshot_id,
        [gamma],
        "incoming",
        kinds=[RelationKind.CALLS],
        limits=TraversalLimits(max_depth=1),
    )

    assert [edge.target_hint for edge in result.edges] == ["gamma"]


def test_a_symbol_with_no_relations_returns_an_empty_result(
    indexed: tuple[sqlite3.Connection, str],
) -> None:
    connection, snapshot_id = indexed
    gamma = _symbol_id(connection, snapshot_id, "gamma")

    result = _traversal(connection, snapshot_id).expand(
        snapshot_id, [gamma], "outgoing", kinds=[RelationKind.CALLS]
    )

    assert result.edges == ()
    assert result.truncated_by == ()


def test_an_over_large_limit_is_refused_against_the_real_store(
    indexed: tuple[sqlite3.Connection, str],
) -> None:
    connection, snapshot_id = indexed

    with pytest.raises(InvalidRequestError):
        _traversal(connection, snapshot_id).expand(
            snapshot_id, ["sym_x"], "outgoing", limits=TraversalLimits(max_depth=50)
        )


def test_repeated_traversal_of_one_snapshot_is_identical(
    indexed: tuple[sqlite3.Connection, str],
) -> None:
    connection, snapshot_id = indexed
    alpha = _symbol_id(connection, snapshot_id, "alpha")
    traversal = _traversal(connection, snapshot_id)

    first = traversal.expand(snapshot_id, [alpha], "outgoing")
    second = traversal.expand(snapshot_id, [alpha], "outgoing")

    assert first == second
