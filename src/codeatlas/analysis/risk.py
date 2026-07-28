"""Ordering findings, and naming the risk of a change as a whole.

Ordering is deterministic and has no model in it. Severity leads, because that
is what a reviewer triages on; derivation breaks ties, so a deterministic
finding outranks a heuristic of equal severity rather than the order depending
on which rule happened to run first.

The overall risk is the highest severity present and nothing cleverer. A
weighted score would invent precision the inputs do not have, and would let two
low findings add up to a medium one — which is not a fact about the change, only
about the arithmetic.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from codeatlas.analysis.findings import FindingDraft, severity_rank
from codeatlas.contracts import Derivation, OverallRisk, Severity

# Strongest first. Two findings of equal severity are not equally load-bearing:
# one observed in syntax outranks one inferred from a name.
_DERIVATION_RANK: Final[dict[Derivation, int]] = {
    Derivation.DETERMINISTIC: 0,
    Derivation.STATIC_RESOLVED: 1,
    Derivation.HIGH_CONFIDENCE_HEURISTIC: 2,
    Derivation.LOW_CONFIDENCE_HEURISTIC: 3,
    Derivation.SEMANTIC_CANDIDATE: 4,
    Derivation.MODEL_GENERATED: 5,
    Derivation.UNSUPPORTED: 6,
}

_RISK_BY_SEVERITY: Final[dict[Severity, OverallRisk]] = {
    Severity.CRITICAL: OverallRisk.CRITICAL,
    Severity.HIGH: OverallRisk.HIGH,
    Severity.MEDIUM: OverallRisk.MEDIUM,
    Severity.LOW: OverallRisk.LOW,
    Severity.INFO: OverallRisk.INFO,
}


def order_findings(drafts: Sequence[FindingDraft]) -> tuple[FindingDraft, ...]:
    """Rank findings most serious first, deterministically.

    The full key includes the code and the subject so two runs over the same
    change produce byte-identical reports. A report that reorders between runs
    cannot be diffed, and a reviewer cannot tell a new finding from a moved one.
    """
    return tuple(
        sorted(
            drafts,
            key=lambda draft: (
                severity_rank(draft.severity),
                _DERIVATION_RANK[draft.derivation],
                draft.code,
                draft.subject,
            ),
        )
    )


def overall_risk(drafts: Sequence[FindingDraft]) -> OverallRisk:
    """The highest severity present, or ``NONE`` when nothing was found.

    ``NONE`` is a real answer rather than a missing field: an analysis that ran
    and found nothing is different from one that did not run.
    """
    if not drafts:
        return OverallRisk.NONE
    highest = min(drafts, key=lambda draft: severity_rank(draft.severity))
    return _RISK_BY_SEVERITY[highest.severity]
