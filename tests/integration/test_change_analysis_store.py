"""Persistence for change analyses: round-trip, cascade, and survival."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection

import pytest

from codeatlas.contracts import (
    AnalysisSide,
    AnalysisStateRef,
    ChangeAnalysisKind,
    ChangeAnalysisReport,
    ChangeAnalysisStatus,
    ChangedFile,
    ChangedSymbol,
    ChangeEvidenceItem,
    ChangeKind,
    Derivation,
    FileChangeKind,
    Finding,
    ImpactEdge,
    OverallRisk,
    RelationKind,
    Severity,
    SnapshotFreshness,
    SymbolKind,
)
from codeatlas.domain.repository import Repository
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import ChangeAnalysisStore, RepositoryStore

REPOSITORY_ID = "repo_1"


def _report(analysis_id: str = "analysis_1") -> ChangeAnalysisReport:
    evidence = ChangeEvidenceItem(
        evidence_id="ev_1",
        side=AnalysisSide.TARGET,
        file_path="src/orders.py",
        symbol="total",
        start_line=1,
        end_line=4,
        content_hash="abc123",
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
    )
    return ChangeAnalysisReport(
        analysis_id=analysis_id,
        request_id="req_1",
        repository_id=REPOSITORY_ID,
        kind=ChangeAnalysisKind.WORKING_TREE,
        status=ChangeAnalysisStatus.COMPLETED,
        overall_risk=OverallRisk.HIGH,
        base=AnalysisStateRef(
            ref="HEAD",
            commit="a" * 40,
            snapshot_id=None,
            freshness=SnapshotFreshness.STALE,
        ),
        target=AnalysisStateRef(
            ref="working-tree",
            commit="b" * 40,
            snapshot_id="snapshot_1",
            freshness=SnapshotFreshness.FRESH,
        ),
        changed_files=[
            ChangedFile(
                path="src/orders.py",
                change_kind=FileChangeKind.MODIFIED,
                content_hash_changed=True,
            )
        ],
        changed_symbols=[
            ChangedSymbol(
                qualified_name="total",
                symbol_kind=SymbolKind.FUNCTION,
                change_kind=ChangeKind.MODIFIED,
                file_path="src/orders.py",
                base_file_path="src/orders.py",
                base_start_line=1,
                base_end_line=2,
                target_start_line=1,
                target_end_line=4,
                signature_changed=False,
                public=True,
                derivation=Derivation.DETERMINISTIC,
                confidence=1.0,
            )
        ],
        impact_edges=[
            ImpactEdge(
                source="total",
                target="render",
                kind=RelationKind.CALLS,
                derivation=Derivation.STATIC_RESOLVED,
                confidence=0.95,
            )
        ],
        findings=[
            Finding(
                code="PUBLIC_BEHAVIOR_CHANGED",
                severity=Severity.MEDIUM,
                title="The behavior of total changed",
                description="Statements in the body differ.",
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                confidence=0.7,
                evidence_ids=["ev_1"],
                limitations=["Statement classification is syntactic."],
            )
        ],
        evidence=[evidence],
        test_gaps=["total"],
        warnings=["GRAPH_TRUNCATED_DEPTH"],
        limitations=["Impact expansion stopped at the depth bound."],
        timing_ms={"file_diff": 1.5},
        created_at=datetime(2026, 7, 27, tzinfo=UTC),
        completed_at=datetime(2026, 7, 27, tzinfo=UTC),
    )


@pytest.fixture()
def connection(tmp_path: Path) -> Iterator[Connection]:
    with connect(tmp_path / "db.sqlite") as handle:
        apply_migrations(handle)
        RepositoryStore(handle).add(
            Repository(
                repository_id=REPOSITORY_ID,
                display_name="repo",
                canonical_root=str(tmp_path / "repo"),
                created_at=datetime(2026, 7, 26, tzinfo=UTC),
            )
        )
        yield handle


def test_a_report_round_trips_with_every_field_intact(
    connection: Connection,
) -> None:
    store = ChangeAnalysisStore(connection)
    written = _report()

    store.save(written)
    read = store.get(written.analysis_id)

    assert read is not None
    assert read.overall_risk is written.overall_risk
    assert read.changed_symbols == written.changed_symbols
    assert read.findings == written.findings
    assert read.evidence == written.evidence
    assert read.impact_edges == written.impact_edges
    assert read.test_gaps == written.test_gaps
    assert read.warnings == written.warnings
    assert read.timing_ms == written.timing_ms


def test_an_unknown_analysis_reads_as_none(connection: Connection) -> None:
    assert ChangeAnalysisStore(connection).get("analysis_nope") is None


def test_saving_twice_replaces_rather_than_duplicates(
    connection: Connection,
) -> None:
    store = ChangeAnalysisStore(connection)
    store.save(_report())
    store.save(_report())

    read = store.get("analysis_1")

    assert read is not None
    assert len(read.findings) == 1
    assert len(read.evidence) == 1


def test_finding_order_survives_the_round_trip(connection: Connection) -> None:
    """`rank` is stored so a later ordering change cannot rewrite an old report."""
    store = ChangeAnalysisStore(connection)
    report = _report()
    report = report.model_copy(
        update={
            "findings": [
                report.findings[0],
                report.findings[0].model_copy(update={"code": "SECOND"}),
            ]
        }
    )

    store.save(report)
    read = store.get(report.analysis_id)

    assert read is not None
    assert [item.code for item in read.findings] == [
        "PUBLIC_BEHAVIOR_CHANGED",
        "SECOND",
    ]


def test_deleting_the_repository_cascades_to_its_analyses(
    connection: Connection,
) -> None:
    """Derived content about a repository the user removed must not linger."""
    store = ChangeAnalysisStore(connection)
    store.save(_report())

    connection.execute(
        "DELETE FROM repositories WHERE repository_id = ?", (REPOSITORY_ID,)
    )

    assert store.get("analysis_1") is None
    assert (
        connection.execute("SELECT COUNT(*) AS n FROM change_findings").fetchone()["n"]
        == 0
    )
    assert (
        connection.execute("SELECT COUNT(*) AS n FROM change_evidence").fetchone()["n"]
        == 0
    )


def test_analyses_are_listed_newest_first(connection: Connection) -> None:
    store = ChangeAnalysisStore(connection)
    older = _report("analysis_older").model_copy(
        update={"created_at": datetime(2026, 7, 26, tzinfo=UTC)}
    )
    newer = _report("analysis_newer")
    store.save(older)
    store.save(newer)

    listed = store.list_for_repository(REPOSITORY_ID)

    assert listed == ("analysis_newer", "analysis_older")


def test_an_analysis_is_not_bound_to_a_snapshot_row(
    connection: Connection,
) -> None:
    """An audit record outlives the snapshot it examined.

    The target snapshot ID is kept for provenance, but no foreign key ties the
    analysis to a `snapshots` row — the audit trail must not be deleted exactly
    when the tree moves on.
    """
    store = ChangeAnalysisStore(connection)
    store.save(_report())

    read = store.get("analysis_1")

    assert read is not None
    assert read.target.snapshot_id == "snapshot_1"
    rows = connection.execute(
        "SELECT COUNT(*) AS n FROM snapshots WHERE snapshot_id = 'snapshot_1'"
    ).fetchone()
    assert rows["n"] == 0
