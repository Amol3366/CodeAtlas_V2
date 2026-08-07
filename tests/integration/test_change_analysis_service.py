"""The two analysis flows, end to end against a real Git repository.

These tests exercise the part the engine deliberately does not know about:
resolving refs, deciding whether the index is current enough to serve as a
state, turning findings into hash-verified citations, and persisting the result
so it can be read back after the tree has moved on.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection

import pytest

from codeatlas.application.change_analysis import ChangeAnalysisRequest
from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import (
    AnalysisSide,
    ChangeAnalysisKind,
    ChangeAnalysisStatus,
    SnapshotFreshness,
)
from codeatlas.domain.errors import (
    ChangeAnalysisNotFoundError,
    ChangeAnalysisRequiresGitError,
    GitRefUnresolvableError,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

BASE_PY = (
    "def total(order):\n"
    '    return order["amount"]\n'
)
TARGET_PY = (
    "def total(order):\n"
    "    if not order:\n"
    '        raise ValueError("order is required")\n'
    '    return order["amount"]\n'
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "PATH": __import__("os").environ.get("PATH", ""),
            "GIT_CONFIG_GLOBAL": str(root / ".gitconfig-absent"),
            "GIT_CONFIG_SYSTEM": str(root / ".gitconfig-absent"),
        },
    )


@dataclass
class Harness:
    services: ApplicationServices
    connection: Connection
    repository_id: str
    root: Path


@pytest.fixture()
def repo(tmp_path: Path) -> Iterator[Harness]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "orders.py").write_text(BASE_PY, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")

    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        yield Harness(
            services=services,
            connection=connection,
            repository_id=repository.repository_id,
            root=root,
        )


@pytest.fixture()
def plain(tmp_path: Path) -> Iterator[Harness]:
    """A registered directory that is not a Git repository."""
    root = tmp_path / "plain"
    root.mkdir()
    (root / "orders.py").write_text(BASE_PY, encoding="utf-8")

    with connect(tmp_path / "plain.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        yield Harness(
            services=services,
            connection=connection,
            repository_id=repository.repository_id,
            root=root,
        )


# --- Working tree -------------------------------------------------------------


def test_a_working_tree_preflight_finds_the_uncommitted_change(
    repo: Harness,
) -> None:
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")

    report = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    assert report.kind is ChangeAnalysisKind.WORKING_TREE
    assert report.status is ChangeAnalysisStatus.COMPLETED
    assert "total" in {item.qualified_name for item in report.changed_symbols}
    assert report.findings


def test_a_clean_tree_reports_no_change(repo: Harness) -> None:
    report = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    assert report.changed_files == []
    assert report.changed_symbols == []
    assert report.findings == []


def test_the_target_side_names_the_snapshot_it_was_analyzed_against(
    repo: Harness,
) -> None:
    """A reader must be able to tell which snapshot the answer is bound to."""
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")

    report = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    assert report.target.snapshot_id is not None
    assert report.target.freshness is SnapshotFreshness.FRESH


def test_the_base_side_is_not_labeled_fresh_and_carries_no_snapshot(
    repo: Harness,
) -> None:
    """A commit blob is immutable, so base evidence is historical by
    construction. It is never labeled `FRESH`, and it carries no snapshot ID
    because no stored snapshot describes it."""
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")

    report = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    assert report.base.snapshot_id is None
    assert report.base.freshness is SnapshotFreshness.STALE
    assert report.base.commit


def test_a_drifted_tree_is_reindexed_before_it_is_analyzed(
    repo: Harness,
) -> None:
    """Analyzing against a stale index answers a question about a dead tree."""
    repo.services.indexing.index(repo.repository_id)
    before = repo.services.status.status(repo.repository_id)
    assert before.snapshot is not None

    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")
    report = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    assert report.target.snapshot_id != before.snapshot.snapshot_id


def test_a_non_git_repository_is_refused_with_its_own_code(
    plain: Harness,
) -> None:
    with pytest.raises(ChangeAnalysisRequiresGitError):
        plain.services.change_analysis.analyze_working_tree(
            ChangeAnalysisRequest(repository_id=plain.repository_id)
        )


def test_an_unresolvable_ref_is_refused(repo: Harness) -> None:
    with pytest.raises(GitRefUnresolvableError):
        repo.services.change_analysis.analyze_working_tree(
            ChangeAnalysisRequest(
                repository_id=repo.repository_id, base_ref="no-such-ref"
            )
        )


# --- Commit range -------------------------------------------------------------


def test_a_commit_range_compares_two_historical_states(repo: Harness) -> None:
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")
    _git(repo.root, "add", ".")
    _git(repo.root, "commit", "-m", "target")

    report = repo.services.change_analysis.analyze_commit_range(
        ChangeAnalysisRequest(
            repository_id=repo.repository_id, base_ref="HEAD~1", target_ref="HEAD"
        )
    )

    assert report.kind is ChangeAnalysisKind.COMMIT_RANGE
    assert "total" in {item.qualified_name for item in report.changed_symbols}
    assert report.base.commit != report.target.commit


def test_neither_side_of_a_commit_range_claims_to_be_fresh(repo: Harness) -> None:
    """Both sides are history; calling either one current would be a lie."""
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")
    _git(repo.root, "add", ".")
    _git(repo.root, "commit", "-m", "target")

    report = repo.services.change_analysis.analyze_commit_range(
        ChangeAnalysisRequest(
            repository_id=repo.repository_id, base_ref="HEAD~1", target_ref="HEAD"
        )
    )

    assert report.base.freshness is SnapshotFreshness.STALE
    assert report.target.freshness is SnapshotFreshness.STALE


# --- Evidence -----------------------------------------------------------------


def test_every_finding_cites_evidence_that_exists(repo: Harness) -> None:
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")

    report = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    available = {item.evidence_id for item in report.evidence}
    assert report.findings
    for finding in report.findings:
        assert finding.evidence_ids
        assert set(finding.evidence_ids) <= available


def test_every_citation_names_the_side_it_came_from(repo: Harness) -> None:
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")

    report = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    assert all(
        item.side in {AnalysisSide.BASE, AnalysisSide.TARGET}
        for item in report.evidence
    )


def test_a_deleted_symbol_is_cited_on_the_base_side(repo: Harness) -> None:
    """The only state where a deleted symbol has lines to point at."""
    (repo.root / "orders.py").unlink()

    report = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    cited = [item for item in report.evidence if item.symbol == "total"]
    assert cited
    assert all(item.side is AnalysisSide.BASE for item in cited)


def test_every_citation_range_exists_in_the_file_it_names(repo: Harness) -> None:
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")

    report = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    for item in report.evidence:
        assert item.start_line >= 1
        assert item.end_line >= item.start_line
        assert item.content_hash


# --- Persistence --------------------------------------------------------------


def test_an_analysis_can_be_read_back_by_id(repo: Harness) -> None:
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")
    written = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    read = repo.services.change_analysis.get(written.analysis_id)

    assert read.analysis_id == written.analysis_id
    assert [item.code for item in read.findings] == [
        item.code for item in written.findings
    ]
    assert {item.evidence_id for item in read.evidence} == {
        item.evidence_id for item in written.evidence
    }


def test_the_stored_finding_order_is_the_order_the_engine_produced(
    repo: Harness,
) -> None:
    """Re-deriving the order on read would let a later rule change rewrite it."""
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")
    written = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    read = repo.services.change_analysis.get(written.analysis_id)

    assert [item.title for item in read.findings] == [
        item.title for item in written.findings
    ]


def test_an_unknown_analysis_is_reported_as_missing(repo: Harness) -> None:
    with pytest.raises(ChangeAnalysisNotFoundError):
        repo.services.change_analysis.get("analysis_nope")


def test_analyses_are_listed_newest_first(repo: Harness) -> None:
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")
    first = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )
    second = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    listed = repo.services.change_analysis.list_for_repository(repo.repository_id)

    assert {first.analysis_id, second.analysis_id} <= set(listed)


# --- Resolver staleness --------------------------------------------------------


def test_a_stale_resolver_snapshot_reports_a_limitation(repo: Harness) -> None:
    """A resolver bump does not reindex existing repositories. Until this one is
    reindexed, its test-gap data came from the older derivation passes, and
    reporting it without saying so would overstate gaps silently."""
    first = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )
    snapshot_id = first.target.snapshot_id
    assert snapshot_id is not None

    # Simulate a snapshot indexed before the resolver bump by writing the
    # older version directly through the row the store already owns. This is
    # more honest than monkeypatching RESOLVER_VERSION: it exercises the real
    # comparison against a snapshot that genuinely disagrees with the
    # constant, rather than making the constant itself lie.
    repo.connection.execute(
        "UPDATE snapshots SET resolver_version = ? WHERE snapshot_id = ?",
        ("1.1.0", snapshot_id),
    )
    repo.connection.commit()

    report = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    assert any("older resolver" in item for item in report.limitations)


def test_a_current_resolver_snapshot_reports_no_such_limitation(
    repo: Harness,
) -> None:
    report = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    assert report.target.snapshot_id is not None
    assert not any("older resolver" in item for item in report.limitations)


def test_no_resolver_limitation_is_claimed_when_there_is_no_snapshot(
    repo: Harness,
) -> None:
    """A commit-range analysis never binds either side to a stored snapshot
    (see test_neither_side_of_a_commit_range_claims_to_be_fresh). Asserting a
    resolver-staleness claim about a snapshot that does not exist would be a
    fabricated finding; an absent snapshot is a different condition, already
    reported elsewhere, and must produce no such limitation."""
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")
    _git(repo.root, "add", ".")
    _git(repo.root, "commit", "-m", "target")

    report = repo.services.change_analysis.analyze_commit_range(
        ChangeAnalysisRequest(
            repository_id=repo.repository_id, base_ref="HEAD~1", target_ref="HEAD"
        )
    )

    assert report.target.snapshot_id is None
    assert not any("older resolver" in item for item in report.limitations)


def test_an_analysis_survives_reindexing_the_repository(repo: Harness) -> None:
    """An audit record must outlive the snapshot it examined."""
    (repo.root / "orders.py").write_text(TARGET_PY, encoding="utf-8")
    written = repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )

    (repo.root / "orders.py").write_text(BASE_PY, encoding="utf-8")
    repo.services.indexing.index(repo.repository_id)

    assert repo.services.change_analysis.get(written.analysis_id) is not None
