"""Finding ordering and overall risk."""

from __future__ import annotations

from codeatlas.analysis.findings import FindingDraft
from codeatlas.analysis.risk import order_findings, overall_risk
from codeatlas.contracts import Derivation, OverallRisk, Severity


def _draft(
    code: str,
    severity: Severity,
    derivation: Derivation = Derivation.DETERMINISTIC,
    subject: str = "a",
) -> FindingDraft:
    return FindingDraft(
        code=code,
        severity=severity,
        title=code,
        description=code,
        derivation=derivation,
        confidence=1.0,
        subject=subject,
    )


def test_severity_leads_the_order() -> None:
    ordered = order_findings(
        [
            _draft("INFO_ONE", Severity.INFO),
            _draft("HIGH_ONE", Severity.HIGH),
            _draft("MEDIUM_ONE", Severity.MEDIUM),
        ]
    )

    assert [item.code for item in ordered] == ["HIGH_ONE", "MEDIUM_ONE", "INFO_ONE"]


def test_derivation_breaks_a_severity_tie() -> None:
    """Two equal severities are not equally load-bearing."""
    ordered = order_findings(
        [
            _draft("GUESS", Severity.HIGH, Derivation.LOW_CONFIDENCE_HEURISTIC),
            _draft("OBSERVED", Severity.HIGH, Derivation.DETERMINISTIC),
        ]
    )

    assert [item.code for item in ordered] == ["OBSERVED", "GUESS"]


def test_the_order_is_stable_across_runs() -> None:
    drafts = [
        _draft("SAME", Severity.HIGH, subject="z"),
        _draft("SAME", Severity.HIGH, subject="a"),
    ]

    assert order_findings(drafts) == order_findings(list(reversed(drafts)))


def test_overall_risk_is_the_highest_severity_present() -> None:
    risk = overall_risk(
        [_draft("A", Severity.LOW), _draft("B", Severity.HIGH)]
    )

    assert risk is OverallRisk.HIGH


def test_two_low_findings_do_not_add_up_to_a_medium_one() -> None:
    """A weighted score would invent precision the inputs do not have."""
    risk = overall_risk([_draft("A", Severity.LOW), _draft("B", Severity.LOW)])

    assert risk is OverallRisk.LOW


def test_no_findings_is_a_real_answer_rather_than_a_missing_one() -> None:
    assert overall_risk([]) is OverallRisk.NONE
