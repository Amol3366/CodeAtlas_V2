"""Relation persistence, batch traversal reads, and cascade against real SQLite."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.contracts import Derivation, RelationKind, SymbolKind
from codeatlas.domain.relations import RelationRecord, ResolutionState
from codeatlas.domain.repository import FileClassification, FileRecord, Repository
from codeatlas.domain.snapshot import Snapshot, SnapshotState
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import (
    FileStore,
    RelationStore,
    RepositoryStore,
    SnapshotStore,
    SymbolStore,
)

CREATED_AT = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with connect(tmp_path / "db.sqlite") as open_connection:
        apply_migrations(open_connection)
        RepositoryStore(open_connection).add(
            Repository(
                repository_id="repo_1",
                display_name="demo",
                canonical_root="C:/repos/demo",
                created_at=CREATED_AT,
            )
        )
        snapshots = SnapshotStore(open_connection)
        files = FileStore(open_connection)
        symbols = SymbolStore(open_connection)
        for snapshot_id in ("snap_1", "snap_2"):
            snapshots.add_staging(_snapshot(snapshot_id))
            files.add_many(snapshot_id, [_file("file_1")])
            symbols.add_many(
                snapshot_id,
                [
                    _symbol("sym_caller", "Service.run"),
                    _symbol("sym_callee", "Store.claim"),
                ],
            )
        yield open_connection


def _snapshot(snapshot_id: str) -> Snapshot:
    return Snapshot(
        snapshot_id=snapshot_id,
        repository_id="repo_1",
        state=SnapshotState.RESOLVING,
        git_head=None,
        git_branch=None,
        git_dirty=False,
        working_tree_fingerprint=f"fingerprint-{snapshot_id}",
        file_count=1,
        parsed_file_count=1,
        skipped_file_count=0,
        parse_error_count=0,
        parser_bundle_version="1.1.0",
        index_version="1.0.0",
        created_at=CREATED_AT,
        activated_at=None,
    )


def _file(file_id: str, relative_path: str = "src/a.py") -> FileRecord:
    return FileRecord(
        file_id=file_id,
        relative_path=relative_path,
        display_path=relative_path,
        content_hash="hash",
        size_bytes=100,
        line_count=40,
        language="python",
        classification=FileClassification.SOURCE_CODE,
    )


def _symbol(symbol_id: str, qualified_name: str) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=symbol_id,
        symbol_version_id=f"symv_{symbol_id}",
        file_id="file_1",
        kind=SymbolKind.METHOD,
        name=qualified_name.rsplit(".", 1)[-1],
        qualified_name=qualified_name,
        module_path="src.a",
        signature=None,
        start_line=1,
        end_line=4,
        start_byte=0,
        end_byte=10,
        content_hash="hash",
        visibility="public",
    )


def _relation(
    relation_id: str = "rel_1",
    *,
    source_symbol_id: str = "sym_caller",
    target_symbol_id: str | None = "sym_callee",
    kind: RelationKind = RelationKind.CALLS,
    target_hint: str = "claim",
    resolution: ResolutionState = ResolutionState.RESOLVED,
    derivation: Derivation = Derivation.STATIC_RESOLVED,
    confidence: float = 0.95,
    start_line: int = 12,
    end_line: int = 12,
    candidate_count: int = 1,
) -> RelationRecord:
    return RelationRecord(
        relation_id=relation_id,
        source_symbol_id=source_symbol_id,
        target_symbol_id=target_symbol_id,
        file_id="file_1",
        kind=kind,
        target_hint=target_hint,
        resolution=resolution,
        derivation=derivation,
        confidence=confidence,
        start_line=start_line,
        end_line=end_line,
        candidate_count=candidate_count,
    )


def _ids(relations: Sequence[RelationRecord]) -> set[str]:
    return {relation.relation_id for relation in relations}


def test_a_relation_round_trips_with_every_field_intact(
    connection: sqlite3.Connection,
) -> None:
    store = RelationStore(connection)
    original = _relation()

    store.add_many("snap_1", [original])

    (stored,) = store.list_for_snapshot("snap_1")
    assert stored == original


def test_an_unresolved_relation_keeps_its_hint_without_a_target(
    connection: sqlite3.Connection,
) -> None:
    """An import of `react` is a real fact even though no symbol answers it."""
    store = RelationStore(connection)
    store.add_many(
        "snap_1",
        [
            _relation(
                target_symbol_id=None,
                kind=RelationKind.IMPORTS,
                target_hint="react",
                resolution=ResolutionState.EXTERNAL,
                derivation=Derivation.DETERMINISTIC,
                candidate_count=0,
            )
        ],
    )

    (stored,) = store.list_for_snapshot("snap_1")
    assert stored.target_symbol_id is None
    assert stored.target_hint == "react"
    assert stored.resolution is ResolutionState.EXTERNAL


def test_an_ambiguous_relation_records_its_candidate_count(
    connection: sqlite3.Connection,
) -> None:
    store = RelationStore(connection)
    store.add_many(
        "snap_1",
        [
            _relation(
                target_symbol_id=None,
                kind=RelationKind.MAY_CALL,
                resolution=ResolutionState.AMBIGUOUS,
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                candidate_count=3,
            )
        ],
    )

    (stored,) = store.list_for_snapshot("snap_1")
    assert stored.candidate_count == 3
    assert stored.derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC


def test_relations_are_scoped_to_their_snapshot(
    connection: sqlite3.Connection,
) -> None:
    store = RelationStore(connection)
    store.add_many("snap_1", [_relation("rel_1")])
    store.add_many("snap_2", [_relation("rel_2")])

    assert _ids(store.list_for_snapshot("snap_1")) == {"rel_1"}
    assert _ids(store.list_for_snapshot("snap_2")) == {"rel_2"}


def test_list_for_file_returns_only_that_file(
    connection: sqlite3.Connection,
) -> None:
    store = RelationStore(connection)
    FileStore(connection).add_many("snap_1", [_file("file_2", "src/b.py")])
    other = RelationRecord(
        relation_id="rel_2",
        source_symbol_id="sym_caller",
        target_symbol_id="sym_callee",
        file_id="file_2",
        kind=RelationKind.CALLS,
        target_hint="claim",
        resolution=ResolutionState.RESOLVED,
        derivation=Derivation.STATIC_RESOLVED,
        confidence=0.95,
        start_line=1,
        end_line=1,
        candidate_count=1,
    )
    store.add_many("snap_1", [_relation("rel_1"), other])

    assert _ids(store.list_for_file("snap_1", "file_1")) == {"rel_1"}


def test_outgoing_expands_a_whole_frontier_in_one_call(
    connection: sqlite3.Connection,
) -> None:
    """Traversal must not issue one query per node; that is the N+1 pattern."""
    store = RelationStore(connection)
    store.add_many(
        "snap_1",
        [
            _relation("rel_1", source_symbol_id="sym_caller"),
            _relation("rel_2", source_symbol_id="sym_callee"),
        ],
    )

    found = store.outgoing("snap_1", ["sym_caller", "sym_callee"])

    assert _ids(found) == {"rel_1", "rel_2"}


def test_outgoing_filters_by_kind(connection: sqlite3.Connection) -> None:
    store = RelationStore(connection)
    store.add_many(
        "snap_1",
        [
            _relation("rel_1", kind=RelationKind.CALLS),
            _relation("rel_2", kind=RelationKind.IMPORTS),
        ],
    )

    found = store.outgoing("snap_1", ["sym_caller"], kinds=[RelationKind.IMPORTS])

    assert _ids(found) == {"rel_2"}


def test_incoming_finds_callers_of_a_target(
    connection: sqlite3.Connection,
) -> None:
    store = RelationStore(connection)
    store.add_many("snap_1", [_relation("rel_1")])

    found = store.incoming("snap_1", ["sym_callee"])

    assert _ids(found) == {"rel_1"}
    assert store.outgoing("snap_1", ["sym_callee"]) == ()


def test_incoming_filters_by_kind(connection: sqlite3.Connection) -> None:
    store = RelationStore(connection)
    store.add_many(
        "snap_1",
        [
            _relation("rel_1", kind=RelationKind.CALLS),
            _relation("rel_2", kind=RelationKind.INHERITS),
        ],
    )

    found = store.incoming("snap_1", ["sym_callee"], kinds=[RelationKind.INHERITS])

    assert _ids(found) == {"rel_2"}


def test_an_empty_frontier_queries_nothing(
    connection: sqlite3.Connection,
) -> None:
    store = RelationStore(connection)
    store.add_many("snap_1", [_relation()])

    assert store.outgoing("snap_1", []) == ()
    assert store.incoming("snap_1", []) == ()


def test_traversal_reads_are_deterministically_ordered(
    connection: sqlite3.Connection,
) -> None:
    store = RelationStore(connection)
    store.add_many(
        "snap_1",
        [
            _relation("rel_b", start_line=20, end_line=20),
            _relation("rel_a", start_line=5, end_line=5),
        ],
    )

    first = [item.relation_id for item in store.outgoing("snap_1", ["sym_caller"])]
    second = [item.relation_id for item in store.outgoing("snap_1", ["sym_caller"])]

    assert first == second == ["rel_a", "rel_b"]


def test_deleting_a_snapshot_cascades_to_its_relations(
    connection: sqlite3.Connection,
) -> None:
    store = RelationStore(connection)
    store.add_many("snap_1", [_relation()])

    connection.execute("DELETE FROM snapshots WHERE snapshot_id = ?", ("snap_1",))

    assert store.count_for_snapshot("snap_1") == 0


def test_delete_for_snapshot_leaves_other_snapshots_intact(
    connection: sqlite3.Connection,
) -> None:
    store = RelationStore(connection)
    store.add_many("snap_1", [_relation("rel_1")])
    store.add_many("snap_2", [_relation("rel_2")])

    store.delete_for_snapshot("snap_1")

    assert store.count_for_snapshot("snap_1") == 0
    assert store.count_for_snapshot("snap_2") == 1


def test_dangling_endpoints_finds_a_relation_whose_target_is_absent(
    connection: sqlite3.Connection,
) -> None:
    """The check that makes a cross-file edge to a deleted symbol unactivatable."""
    store = RelationStore(connection)
    store.add_many(
        "snap_1",
        [
            _relation("rel_ok"),
            _relation("rel_broken", target_symbol_id="sym_deleted"),
        ],
    )

    assert store.dangling_endpoints("snap_1") == ("rel_broken",)


def test_dangling_endpoints_finds_a_relation_whose_source_is_absent(
    connection: sqlite3.Connection,
) -> None:
    store = RelationStore(connection)
    store.add_many(
        "snap_1", [_relation("rel_broken", source_symbol_id="sym_deleted")]
    )

    assert store.dangling_endpoints("snap_1") == ("rel_broken",)


def test_an_unresolved_target_is_not_dangling(
    connection: sqlite3.Connection,
) -> None:
    """NULL means "no repository symbol answers this", which is a valid state."""
    store = RelationStore(connection)
    store.add_many(
        "snap_1",
        [
            _relation(
                target_symbol_id=None,
                resolution=ResolutionState.EXTERNAL,
                candidate_count=0,
            )
        ],
    )

    assert store.dangling_endpoints("snap_1") == ()


def _captured_plan(
    connection: sqlite3.Connection,
    run: Callable[[], object],
) -> str:
    """Return the query plan for the SELECT the store itself issued.

    The statement is captured by tracing rather than re-typed into the test, so
    the assertion cannot quietly drift away from the query that actually runs.
    SQLite hands the trace callback the statement with its parameters already
    expanded, so it re-executes under EXPLAIN with no bindings.
    """
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    try:
        run()
    finally:
        connection.set_trace_callback(None)

    selects = [item for item in statements if item.lstrip().startswith("SELECT")]
    assert len(selects) == 1, f"expected one SELECT, traced {selects}"
    rows = connection.execute(f"EXPLAIN QUERY PLAN {selects[0]}").fetchall()
    return " ".join(str(row[3]) for row in rows)


def test_outgoing_traversal_uses_the_source_index(
    connection: sqlite3.Connection,
) -> None:
    """Asserted against the query planner, not by reading the schema."""
    store = RelationStore(connection)
    store.add_many("snap_1", [_relation()])

    plan = _captured_plan(
        connection,
        lambda: store.outgoing(
            "snap_1", ["sym_caller", "sym_callee"], kinds=[RelationKind.CALLS]
        ),
    )

    assert "USING INDEX relations_by_source" in plan
    assert "SCAN relations" not in plan


def test_incoming_traversal_uses_the_target_index(
    connection: sqlite3.Connection,
) -> None:
    store = RelationStore(connection)
    store.add_many("snap_1", [_relation()])

    plan = _captured_plan(
        connection,
        lambda: store.incoming(
            "snap_1", ["sym_callee"], kinds=[RelationKind.CALLS]
        ),
    )

    assert "USING INDEX relations_by_target" in plan
    assert "SCAN relations" not in plan


def test_an_unfiltered_frontier_still_uses_an_index(
    connection: sqlite3.Connection,
) -> None:
    """Kind filtering is optional; dropping it must not fall back to a scan."""
    store = RelationStore(connection)
    store.add_many("snap_1", [_relation()])

    plan = _captured_plan(
        connection,
        lambda: store.outgoing("snap_1", ["sym_caller"]),
    )

    assert "USING INDEX relations_by_source" in plan
    assert "SCAN relations" not in plan
