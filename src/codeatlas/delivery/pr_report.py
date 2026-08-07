"""A rendering of one change analysis shaped for a pull request.

:func:`codeatlas.delivery.render_markdown` is the audit format: complete, flat,
every evidence row present. That is right for an archive and wrong for a review.
A reviewer wants a verdict, the risks in order, and the option to expand the
rest.

This renderer adds no facts. It reorders and folds what the report already
carries, and it never drops a finding or a test gap.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from codeatlas.contracts import (
    ChangeAnalysisReport,
    ChangeEvidenceItem,
    Finding,
    GapReason,
    Severity,
)
from codeatlas.delivery.markdown_text import escape_cell, escape_inline, table

_SEVERITY_ORDER: Final[tuple[Severity, ...]] = (
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
)


MAX_CHARACTERS: Final[int] = 60_000
"""A conservative bound, deliberately not named after any platform's limit.

CodeAtlas does not know what its output is being pasted into. Leaving it
unbounded is not the safer choice: the destination would truncate it
arbitrarily, mid-sentence, with no notice — the same silent drop, relocated
somewhere CodeAtlas does not control.
"""


def render_pr_markdown(report: ChangeAnalysisReport) -> str:
    """Render one persisted analysis for pasting into a pull request."""
    # Never cut: the verdict, what to act on, and the caveats on all of it.
    essential = _headline(report) + _findings(report) + _gaps(report)
    notes = _notes(report)
    fixed = _length(essential) + _length(notes)

    kept: list[str] = []
    omitted: list[str] = []
    for name, section in _optional_sections(report):
        if fixed + _length(kept) + _length(section) <= MAX_CHARACTERS:
            kept += section
        else:
            omitted.append(name)

    lines = essential + kept + notes
    if omitted:
        lines += _omission_notice(omitted)
    return "\n".join(lines).rstrip() + "\n"


def _omission_notice(omitted: Sequence[str]) -> list[str]:
    """Say exactly what was left out and where to get it.

    An undeclared cut is the failure this bound exists to prevent, so this line
    is emitted even if it pushes the output past `MAX_CHARACTERS`: the accuracy
    of the notice outranks the bound it reports on.
    """
    names = ", ".join(escape_inline(name) for name in omitted)
    return [
        "",
        f"> Omitted to fit: {names}. Use the `markdown` or `json` report "
        "format for the complete analysis.",
        "",
    ]


def _length(lines: Sequence[str]) -> int:
    """Rendered length of a section, counting the newline each line will get."""
    return sum(len(line) + 1 for line in lines)


def _optional_sections(
    report: ChangeAnalysisReport,
) -> list[tuple[str, list[str]]]:
    """Supporting detail, folded, each paired with its display name.

    Collapsing costs nothing and hides nothing — the content is present in the
    document. An empty section is omitted rather than rendered empty: a
    disclosure triangle over nothing wastes a reader's click.

    Returned as (name, lines) pairs so the bound in :func:`render_pr_markdown`
    can name exactly what it left out.
    """
    sections: list[tuple[str, list[str]]] = []

    changed = _changed_rows(report)
    if changed:
        sections.append(
            (
                "What changed",
                _fold(
                    f"What changed ({len(changed)})",
                    table(("Symbol", "Kind", "Change", "File"), changed),
                ),
            )
        )

    if report.impact_edges:
        rows = [
            (
                escape_cell(edge.source),
                escape_cell(edge.kind.value),
                escape_cell(edge.target),
                escape_cell(edge.derivation.value),
            )
            for edge in report.impact_edges
        ]
        sections.append(
            (
                "What it reaches",
                _fold(
                    f"What it reaches ({len(rows)})",
                    table(("Changed", "Relation", "Reaches", "Derivation"), rows),
                ),
            )
        )

    if report.evidence:
        cited = [
            (
                escape_cell(item.file_path),
                escape_cell(f"{item.start_line}-{item.end_line}"),
                escape_cell(item.side.value),
                escape_cell(item.symbol or ""),
                escape_cell(item.derivation.value),
            )
            for item in report.evidence
        ]
        sections.append(
            (
                "Evidence",
                _fold(
                    f"Evidence ({len(cited)})",
                    table(
                        ("File", "Lines", "Side", "Symbol", "Derivation"), cited
                    ),
                ),
            )
        )

    return sections


def _changed_rows(report: ChangeAnalysisReport) -> list[tuple[str, ...]]:
    """Changed symbols, then files that produced no symbol of their own.

    A file with no changed symbol is still a real change — a deleted
    configuration file has nothing to attach to — but repeating a file that
    already has symbols would pad the table.
    """
    rows: list[tuple[str, ...]] = [
        (
            escape_cell(item.qualified_name),
            escape_cell(item.symbol_kind.value),
            escape_cell(item.change_kind.value),
            escape_cell(item.file_path),
        )
        for item in report.changed_symbols
    ]
    covered = {item.file_path for item in report.changed_symbols}
    rows += [
        (escape_cell(item.path), "", escape_cell(item.change_kind.value), "")
        for item in report.changed_files
        if item.path not in covered
    ]
    return rows


def _fold(summary: str, body: Sequence[str]) -> list[str]:
    return [
        "<details>",
        f"<summary>{escape_inline(summary)}</summary>",
        "",
        *body,
        "",
        "</details>",
        "",
    ]


def _notes(report: ChangeAnalysisReport) -> list[str]:
    """Warnings and limitations, never folded.

    They qualify everything above them, and a qualification behind a disclosure
    triangle is a qualification most readers never see.
    """
    if not report.warnings and not report.limitations:
        return []
    return [
        "### Warnings and limitations",
        "",
        *(f"- `{escape_inline(item)}`" for item in report.warnings),
        *(f"- {escape_inline(item)}" for item in report.limitations),
        "",
    ]


def _headline(report: ChangeAnalysisReport) -> list[str]:
    symbols = len(report.changed_symbols)
    files = len(report.changed_files)
    findings = len(report.findings)
    gaps = len(report.test_gaps)
    risk = escape_inline(report.overall_risk.value.upper())
    return [
        f"## CodeAtlas preflight — **{risk}** risk",
        "",
        f"{symbols} {_plural(symbols, 'symbol')} changed across "
        f"{files} {_plural(files, 'file')} · "
        f"{findings} {_plural(findings, 'finding')} · "
        f"{gaps} possible test {_plural(gaps, 'gap')}",
        "",
        f"Base `{escape_inline(report.base.ref)}` "
        f"({escape_inline(report.base.commit or 'no commit')}, "
        f"{escape_inline(report.base.freshness.value)}) → "
        f"target `{escape_inline(report.target.ref)}` "
        f"({escape_inline(report.target.commit or 'no commit')}, "
        f"{escape_inline(report.target.freshness.value)})",
        "",
    ]


def _findings(report: ChangeAnalysisReport) -> list[str]:
    if not report.findings:
        return [
            "### Findings",
            "",
            "No findings. That is not a claim that the change is safe — only "
            "that no rule matched it.",
            "",
        ]

    by_id = {item.evidence_id: item for item in report.evidence}
    lines = ["### Findings", ""]
    for severity in _SEVERITY_ORDER:
        for finding in [item for item in report.findings if item.severity is severity]:
            lines += _one_finding(finding, by_id)
    return lines


def _one_finding(
    finding: Finding, by_id: dict[str, ChangeEvidenceItem]
) -> list[str]:
    lines = [
        f"**{escape_inline(finding.severity.value.upper())} — "
        f"{escape_inline(finding.title)}** "
        f"(`{escape_inline(finding.code)}`)",
        "",
        escape_inline(finding.description),
        "",
        # Derivation and confidence are separate facts: a high-confidence
        # heuristic is still a heuristic, and a score never promotes it.
        f"`{escape_inline(finding.derivation.value)}` · "
        f"confidence {finding.confidence:.2f}",
        "",
    ]
    for evidence_id in finding.evidence_ids:
        item = by_id.get(evidence_id)
        if item is not None:
            lines += [_evidence_line(item), ""]
    if finding.remediation:
        lines += [f"Remediation: {escape_inline(finding.remediation)}", ""]
    for limitation in finding.limitations:
        lines += [f"Limitation: {escape_inline(limitation)}", ""]
    return lines


def _gaps(report: ChangeAnalysisReport) -> list[str]:
    """Possible test gaps, each with the reason it is still a gap.

    The disclaimer is mandatory. A missing `TESTS` edge does not prove absence
    of coverage, and only executing the suite could cross that line — which
    CodeAtlas does not do. The heading says "possible" for the same reason.
    """
    if not report.test_gaps:
        return []

    by_name = {item.qualified_name: item for item in report.test_gap_reasons}
    lines = [
        "### Possible test gaps",
        "",
        "A missing `TESTS` edge does not prove absence of coverage. CodeAtlas "
        "does not execute tests and cannot claim any symbol is untested.",
        "",
    ]
    lines += [_one_gap(name, by_name.get(name)) for name in report.test_gaps]
    lines.append("")
    return lines


def _one_gap(name: str, reason: GapReason | None) -> str:
    if reason is None:
        # A gap with no recorded reason is still a gap. Inventing one would be
        # the fabrication this product exists to refuse.
        return f"- `{escape_inline(name)}`"
    return (
        f"- `{escape_inline(name)}` — {escape_inline(reason.explanation)} "
        f"(`{escape_inline(reason.reason.value)}`)"
    )


def _evidence_line(item: ChangeEvidenceItem) -> str:
    """One citation as text.

    Never a forge URL: a permalink needs a host, owner, repository and commit
    that CodeAtlas does not have and would have to guess, and a wrong permalink
    is a citation pointing at the wrong code.
    """
    return (
        f"`{escape_inline(item.file_path)}:"
        f"{item.start_line}-{item.end_line}` "
        f"({escape_inline(item.side.value)}) · "
        f"`{escape_inline(item.derivation.value)}` · "
        f"confidence {item.confidence:.2f}"
    )


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else f"{noun}s"
