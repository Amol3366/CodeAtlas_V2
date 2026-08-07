"""The pull-request rendering of one change analysis."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
    GapReason,
    GapReasonCode,
    ImpactEdge,
    OverallRisk,
    RelationKind,
    Severity,
    SnapshotFreshness,
    SymbolKind,
)
from codeatlas.delivery import render_markdown, render_pr_markdown
from codeatlas.delivery.markdown_text import escape_inline


def _state(ref: str) -> AnalysisStateRef:
    return AnalysisStateRef(
        ref=ref,
        commit="a1b2c3d",
        freshness=SnapshotFreshness.FRESH,
        snapshot_id=None,
    )


def _evidence(index: int = 1) -> ChangeEvidenceItem:
    return ChangeEvidenceItem(
        evidence_id=f"e{index}",
        side=AnalysisSide.TARGET,
        file_path=f"src/orders_{index}.py",
        symbol=None,
        start_line=1,
        end_line=2,
        content_hash="h",
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
    )


def _finding(severity: Severity, title: str) -> Finding:
    # `evidence_ids` has min_length=1 and every id must exist in the report's
    # evidence, so any test using a finding must carry `_evidence(1)` too.
    return Finding(
        code="PUBLIC_CONTRACT_CHANGED",
        severity=severity,
        title=title,
        description="The signature changed.",
        derivation=Derivation.STATIC_RESOLVED,
        confidence=0.9,
        evidence_ids=["e1"],
    )


def _report(**overrides: Any) -> ChangeAnalysisReport:
    fields: dict[str, Any] = {
        "analysis_id": "a1",
        "repository_id": "r1",
        "request_id": "q1",
        "kind": ChangeAnalysisKind.WORKING_TREE,
        "status": ChangeAnalysisStatus.COMPLETED,
        "overall_risk": OverallRisk.LOW,
        "base": _state("HEAD"),
        "target": _state("working-tree"),
        "created_at": datetime(2026, 8, 7, tzinfo=UTC),
    }
    fields.update(overrides)
    return ChangeAnalysisReport(**fields)


def _with_findings(*findings: Finding, **overrides: Any) -> ChangeAnalysisReport:
    return _report(findings=list(findings), evidence=[_evidence(1)], **overrides)


def test_the_risk_leads_the_report() -> None:
    # The verdict is the first thing a reviewer sees, per the PRD's
    # "ordered by risk. This is the product."
    markdown = render_pr_markdown(_report(overall_risk=OverallRisk.HIGH))

    first = markdown.splitlines()[0]
    assert first.startswith("## CodeAtlas preflight")
    assert "HIGH" in first


def test_both_refs_and_their_freshness_are_stated() -> None:
    markdown = render_pr_markdown(_report())

    assert "HEAD" in markdown
    assert "fresh" in markdown


def test_findings_are_ordered_most_severe_first() -> None:
    markdown = render_pr_markdown(
        _with_findings(
            _finding(Severity.LOW, "Low one"),
            _finding(Severity.CRITICAL, "Critical one"),
        )
    )

    assert markdown.index("Critical one") < markdown.index("Low one")


def test_a_finding_shows_derivation_and_confidence_separately() -> None:
    # A high confidence score never implies a stronger derivation.
    markdown = render_pr_markdown(_with_findings(_finding(Severity.HIGH, "T")))

    assert "static_resolved" in markdown
    assert "0.90" in markdown


def test_no_findings_is_not_a_safety_claim() -> None:
    markdown = render_pr_markdown(_report())

    assert "not a claim that the change is safe" in markdown


def test_the_gap_disclaimer_is_present_whenever_a_gap_is() -> None:
    markdown = render_pr_markdown(_report(test_gaps=["orders.Order"]))

    assert "does not prove absence of coverage" in markdown
    assert "does not execute tests" in markdown


def test_the_gap_heading_says_possible_not_untested() -> None:
    markdown = render_pr_markdown(_report(test_gaps=["orders.Order"]))

    assert "Possible test gaps" in markdown


def test_a_gap_carries_its_reason_code_and_explanation() -> None:
    markdown = render_pr_markdown(
        _report(
            test_gaps=["orders.Order"],
            test_gap_reasons=[
                GapReason(
                    qualified_name="orders.Order",
                    reason=GapReasonCode.FIXTURE_MEDIATED_ONLY,
                    explanation="A test reaches this only through a fixture.",
                    evidence_ids=[],
                )
            ],
        )
    )

    assert "FIXTURE_MEDIATED_ONLY" in markdown
    assert "only through a fixture" in markdown


def test_a_gap_with_no_reason_still_appears() -> None:
    markdown = render_pr_markdown(_report(test_gaps=["orders.Order"]))

    assert "orders.Order" in markdown


def test_a_hostile_symbol_name_is_escaped() -> None:
    markdown = render_pr_markdown(_report(test_gaps=["a|b`c"]))

    assert "a\\|b\\`c" in markdown


def test_no_forge_url_is_ever_constructed() -> None:
    # "No GitHub/GitLab or CI integration" is an explicit PRD non-goal, and a
    # guessed permalink is a citation pointing at the wrong code.
    markdown = render_pr_markdown(
        _with_findings(_finding(Severity.HIGH, "T"), test_gaps=["a"])
    )

    assert "http://" not in markdown
    assert "https://" not in markdown


def _symbol(name: str = "orders.Order.total") -> ChangedSymbol:
    return ChangedSymbol(
        qualified_name=name,
        symbol_kind=SymbolKind.METHOD,
        change_kind=ChangeKind.MODIFIED,
        file_path="src/orders.py",
        target_start_line=40,
        target_end_line=52,
        confidence=1.0,
        derivation=Derivation.DETERMINISTIC,
        public=True,
        signature_changed=True,
    )


def _file(path: str = "src/orders.py") -> ChangedFile:
    return ChangedFile(
        path=path,
        change_kind=FileChangeKind.MODIFIED,
        content_hash_changed=True,
    )


def _edge(
    kind: RelationKind = RelationKind.CALLS,
    target: str = "api.checkout",
    derivation: Derivation = Derivation.STATIC_RESOLVED,
) -> ImpactEdge:
    return ImpactEdge(
        source="orders.Order.total",
        kind=kind,
        target=target,
        derivation=derivation,
        confidence=0.9,
    )


def test_supporting_detail_is_collapsed_not_dropped() -> None:
    markdown = render_pr_markdown(
        _report(
            changed_symbols=[_symbol()],
            changed_files=[_file()],
            impact_edges=[_edge()],
        )
    )

    assert "<details>" in markdown
    assert "What changed" in markdown
    assert "What it reaches" in markdown


def test_every_impact_edge_shows_its_derivation() -> None:
    # ADR-0016: a fixture-mediated TESTS edge is a candidate, not coverage.
    # Rendering an edge without its derivation would undo that distinction in
    # the surface most likely to be quoted into a review.
    markdown = render_pr_markdown(
        _report(
            impact_edges=[
                _edge(),
                _edge(
                    kind=RelationKind.TESTS,
                    target="test_total",
                    derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
                ),
            ]
        )
    )

    assert "static_resolved" in markdown
    assert "low_confidence_heuristic" in markdown


def test_a_changed_file_with_no_symbol_is_still_listed() -> None:
    markdown = render_pr_markdown(_report(changed_files=[_file("pyproject.toml")]))

    assert "pyproject.toml" in markdown


def test_a_file_that_already_has_a_symbol_is_not_repeated() -> None:
    markdown = render_pr_markdown(
        _report(changed_symbols=[_symbol()], changed_files=[_file("src/orders.py")])
    )

    assert markdown.count("src/orders.py") == 1


def test_warnings_and_limitations_are_never_collapsed() -> None:
    # They qualify everything above them, and a qualification behind a
    # disclosure triangle is one most readers never see.
    markdown = render_pr_markdown(
        _report(warnings=["W_CODE"], limitations=["A stated limit."])
    )

    notes = markdown[markdown.index("W_CODE") :]
    assert "<details>" not in notes
    assert "A stated limit." in markdown


def test_an_empty_section_is_omitted_rather_than_shown_empty() -> None:
    markdown = render_pr_markdown(_report())

    assert "What it reaches" not in markdown


def test_both_renderers_escape_a_hostile_name_identically() -> None:
    """The two renderings differ in shape, never in how they neutralise text.

    If someone later gives one renderer its own escaping — or "fixes" one and
    not the other — this is what catches it. Escaping untrusted repository text
    is the one thing the two must never diverge on.
    """
    hostile = "a|b`c<d>e\f"
    report = _report(test_gaps=[hostile])

    audit = render_markdown(report)
    pull_request = render_pr_markdown(report)

    escaped = escape_inline(hostile)
    assert escaped in audit
    assert escaped in pull_request
