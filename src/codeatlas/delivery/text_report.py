"""A rendering of one change analysis for a terminal.

The Markdown and PR renderings are documents. This one is a verdict: a reader
at a prompt wants to know whether to worry and about what, not to scroll a
table of every evidence row.

No colour is used, at all. `documentation/design.md` requires that colour is
never the only signal, and the simplest way to satisfy that here is not to
depend on it — which also keeps the output identical when piped, redirected, or
captured by CI, with no `isatty` branching to get wrong.
"""

from __future__ import annotations

import re
from typing import Final

from codeatlas.contracts import (
    SEVERITY_ORDER,
    ChangeAnalysisReport,
    ChangeEvidenceItem,
    Derivation,
    Finding,
)

# Repository text reaching a terminal could move the cursor or blank a line.
# The Markdown renderers strip the same range; a terminal is where it matters
# most, because there is no markup layer between this text and the device.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_INDENT: Final[str] = "  "
_DETAIL: Final[str] = " " * 10


def render_text(report: ChangeAnalysisReport) -> str:
    """Render one analysis as plain text for a terminal."""
    lines = (
        _verdict(report)
        + _findings(report)
        + _gaps(report)
        + _impact(report)
        + _notes(report)
    )
    return "\n".join(lines).rstrip() + "\n"


def _notes(report: ChangeAnalysisReport) -> list[str]:
    """Warnings and limitations, which this renderer used to drop entirely.

    Survivable while every excluded file produced a loud failure somewhere
    else. ADR-0045 turned an oversized tracked file into a *silent* skip, and
    this is the surface where that silence would have landed: `impact` prints a
    verdict by default, so a reader would have seen a clean result and never
    learned a file was left out.

    Last on purpose. The verdict is what a reader at a prompt came for; the
    caveats qualify it and belong after it, not in front of it.
    """
    if not report.warnings and not report.limitations:
        return []
    lines = ["", "Warnings and limitations"]
    lines += [f"{_INDENT}{_clean(item)}" for item in report.warnings]
    lines += [f"{_INDENT}{_clean(item)}" for item in report.limitations]
    return lines


def _clean(value: str) -> str:
    """Strip anything that would act on the terminal rather than print to it."""
    return _CONTROL.sub("", value)


def _verdict(report: ChangeAnalysisReport) -> list[str]:
    symbols = len(report.changed_symbols)
    files = len(report.changed_files)
    findings = len(report.findings)
    gaps = len(report.test_gaps)
    return [
        f"{_clean(report.overall_risk.value.upper())} risk · "
        f"{symbols} {_plural(symbols, 'symbol')} across "
        f"{files} {_plural(files, 'file')} · "
        f"{findings} {_plural(findings, 'finding')} · "
        f"{gaps} possible test {_plural(gaps, 'gap')}",
        f"base {_clean(report.base.ref)} "
        f"({_clean(report.base.commit or 'no commit')}, "
        f"{_clean(report.base.freshness.value)}) → "
        f"target {_clean(report.target.ref)} "
        f"({_clean(report.target.freshness.value)})",
        "",
    ]


def _findings(report: ChangeAnalysisReport) -> list[str]:
    if not report.findings:
        return [
            "FINDINGS",
            f"{_INDENT}None. That is not a claim that the change is safe — only",
            f"{_INDENT}that no rule matched it.",
            "",
        ]

    by_id = {item.evidence_id: item for item in report.evidence}
    lines = ["FINDINGS"]
    for severity in SEVERITY_ORDER:
        for finding in [item for item in report.findings if item.severity is severity]:
            lines += _one_finding(finding, by_id)
    return lines


def _one_finding(
    finding: Finding, by_id: dict[str, ChangeEvidenceItem]
) -> list[str]:
    label = _clean(finding.severity.value.upper()).ljust(8)
    lines = [
        f"{_INDENT}{label}{_clean(finding.title)}  {_clean(finding.code)}",
    ]
    if finding.subject:
        # Two findings can share a code and a title; only the subject and its
        # file tell them apart (ADR-0054). The CLI verdict is the surface that
        # silently dropped limitations until ADR-0045, so it is updated here
        # rather than assumed to follow.
        lines.append(
            f"{_INDENT}{_DETAIL}{_clean(finding.subject)}"
            + (f" in {_clean(finding.file_path)}" if finding.file_path else "")
        )
    lines += [
        f"{_INDENT}{_DETAIL}{_clean(finding.description)}",
        # Derivation and confidence are separate facts: a high-confidence
        # heuristic is still a heuristic, and a score never promotes it.
        f"{_INDENT}{_DETAIL}{_clean(finding.derivation.value)} · "
        f"{finding.confidence:.2f}",
    ]
    for evidence_id in finding.evidence_ids:
        item = by_id.get(evidence_id)
        if item is not None:
            lines.append(
                f"{_INDENT}{_DETAIL}{_clean(item.file_path)}:"
                f"{item.start_line}-{item.end_line} "
                f"({_clean(item.side.value)})"
            )
    lines.append("")
    return lines


def _gaps(report: ChangeAnalysisReport) -> list[str]:
    """Possible test gaps and why each is still one.

    The disclaimer is mandatory. A missing `TESTS` edge does not prove absence
    of coverage, and only executing the suite could cross that line — which
    CodeAtlas does not do. The heading says "possible" for the same reason.
    """
    if not report.test_gaps:
        return []

    by_name = {item.qualified_name: item for item in report.test_gap_reasons}
    lines = [
        "POSSIBLE TEST GAPS",
        f"{_INDENT}A missing TESTS edge does not prove absence of coverage.",
        f"{_INDENT}CodeAtlas does not execute tests.",
        "",
    ]
    for name in report.test_gaps:
        reason = by_name.get(name)
        if reason is None:
            # A gap with no recorded reason is still a gap. Inventing one would
            # be the fabrication this product exists to refuse.
            lines.append(f"{_INDENT}{_clean(name)}")
        else:
            lines.append(
                f"{_INDENT}{_clean(name)}  {_clean(reason.explanation)}  "
                f"{_clean(reason.reason.value)}"
            )
    lines.append("")
    return lines


def _impact(report: ChangeAnalysisReport) -> list[str]:
    """A count, not a list.

    The full edge table is what `--format markdown` is for. The weak count is
    called out because a `low_confidence_heuristic` edge is a candidate rather
    than coverage (ADR-0016), and a summary that hid the distinction would undo
    the thing that slice was built to create.
    """
    if not report.impact_edges:
        return []
    weak = sum(
        1
        for edge in report.impact_edges
        if edge.derivation is Derivation.LOW_CONFIDENCE_HEURISTIC
    )
    total = len(report.impact_edges)
    line = f"IMPACT{_INDENT}{total} {_plural(total, 'edge')}"
    if weak:
        line += f", {weak} low_confidence_heuristic"
    return [line, ""]


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else f"{noun}s"
