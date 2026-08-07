# PR-ready Markdown Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second Markdown rendering shaped for a pull request — verdict first, findings and test gaps expanded, supporting detail collapsed, bounded with any cut declared — and give the existing audit renderer the test-gap reasons it never caught up on.

**Architecture:** The shared escaping moves to its own module first, so two renderers cannot drift on how they handle untrusted repository text. `render_markdown` stays the complete audit format and gains gap reasons. `render_pr_markdown` is new. `ReportFormat` gains `"pr"` across REST, CLI, and MCP. SARIF is deliberately untouched.

**Tech Stack:** Python 3.12, Pydantic 2, Typer, FastAPI, `mcp`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-07-pr-ready-markdown-export-design.md`

## Global Constraints

- `contract_version` stays `"1.1"`; `SCHEMA_VERSION` stays `14`; **no migration**.
- Python pinned `>=3.12,<3.13`. Add **no** dependency.
- Type hints throughout. MyPy must pass (`uv run mypy --no-incremental src`).
- Comments explain *why*, not *what*.
- Do **not** delete, skip, or weaken an existing test.
- **Never claim a symbol is tested or untested.** Output describes the relation graph only.
- All repository-derived text is untrusted and must be escaped before it reaches Markdown.
- **`render_sarif` must not change.** A test gap is explicitly not a finding.
- No network access, no forge URLs, no file writes — every renderer returns a string.
- Use `uv run` for all Python commands.

## Reference: what exists today

- `src/codeatlas/delivery/markdown_report.py` — `render_markdown`, 257 lines. Escaping helpers `_inline` (line 228), `_cell` (247), `_table` (202), `_CONTROL` (39), `MAX_CELL_LENGTH` (41).
- `_test_gaps(report)` at line 161 — emits the disclaimer and one bullet per name. **No reasons.**
- `src/codeatlas/delivery/__init__.py` — exports `render_markdown`, `render_sarif`.
- Consumers: REST `src/codeatlas/api/routers/change_analysis.py:87`; CLI `src/codeatlas/cli/main.py:1314`; MCP `src/codeatlas/mcp/tools.py:495`.
- Contract types: `Finding`, `ChangedSymbol`, `ChangedFile`, `ImpactEdge`, `GapReason`, `GapReasonCode`, `ChangeEvidenceItem`, `AnalysisStateRef` in `src/codeatlas/contracts.py`.
- `ChangeAnalysisReport.test_gap_reasons: list[GapReason]` exists and is populated.
- Delivery has **no unit test file today**. Its Markdown assertions live in `tests/contract/test_change_cross_adapter.py`.

---

### Task 1: Extract the Markdown escaping

Two renderers handling untrusted repository text must not each carry their own copy. Extract before writing the second one.

**Files:**
- Create: `src/codeatlas/delivery/markdown_text.py`
- Create: `tests/unit/test_markdown_text.py`
- Modify: `src/codeatlas/delivery/markdown_report.py` (delete the helpers, import them)

**Interfaces:**
- Consumes: nothing.
- Produces, all from `codeatlas.delivery.markdown_text`:
  - `escape_inline(value: str) -> str`
  - `escape_cell(value: str) -> str`
  - `table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]`
  - `MAX_CELL_LENGTH: Final[int]`

- [ ] **Step 1: Write the failing test**

```python
"""Escaping for untrusted repository text rendered as Markdown."""

from __future__ import annotations

from codeatlas.delivery.markdown_text import (
    MAX_CELL_LENGTH,
    escape_cell,
    escape_inline,
    table,
)


def test_a_backtick_cannot_close_a_code_span() -> None:
    # A symbol named with a backtick would otherwise end the span it sits in
    # and let the rest of the value render as markup.
    assert escape_inline("a`b") == "a\\`b"


def test_a_pipe_cannot_forge_a_table_column() -> None:
    assert escape_inline("a|b") == "a\\|b"


def test_angle_brackets_become_entities() -> None:
    assert escape_inline("<script>") == "&lt;script&gt;"


def test_a_newline_becomes_a_space() -> None:
    # A value spanning lines would break the row it belongs to.
    assert escape_inline("a\nb") == "a b"
    assert escape_inline("a\rb") == "a b"


def test_control_characters_are_removed() -> None:
    # These would move the cursor or blank a line in a terminal rendering it.
    assert escape_inline("a\x00\x1bb") == "ab"


def test_a_backslash_is_escaped_before_anything_else() -> None:
    # Escaping the backslash last would double-escape what earlier rules added.
    assert escape_inline("a\\b") == "a\\\\b"


def test_a_long_cell_is_truncated_rather_than_wrapped() -> None:
    # An unbounded value from repository content would push a table past any
    # width and make the whole report unreadable.
    result = escape_cell("x" * (MAX_CELL_LENGTH + 50))
    assert len(result) == MAX_CELL_LENGTH
    assert result.endswith("…")


def test_a_short_cell_is_unchanged_apart_from_escaping() -> None:
    assert escape_cell("a|b") == "a\\|b"


def test_a_table_has_a_header_a_separator_and_one_row_each() -> None:
    lines = table(("A", "B"), [("1", "2"), ("3", "4")])
    assert lines == ["| A | B |", "| --- | --- |", "| 1 | 2 |", "| 3 | 4 |"]


def test_a_table_with_no_rows_still_has_its_header() -> None:
    assert table(("A",), []) == ["| A |", "| --- |"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_markdown_text.py -v`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Create the module**

Move the implementations **verbatim** from `markdown_report.py`, renaming only the public names. Keep every existing comment — they explain why each rule exists.

```python
"""Markdown escaping for untrusted repository text.

Everything rendered by a delivery renderer came out of a repository, which
means all of it is untrusted. A symbol named ``| --- |`` must not become a
table row separator, and a document heading containing a backtick fence must
not end a code block early.

This lives in its own module because more than one renderer needs it. Two
copies would be two places to get it wrong, and only one of them would be
reviewed when someone next changed it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Final

# Control characters would let repository content move the cursor or blank a
# line in a terminal that renders the Markdown.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MAX_CELL_LENGTH: Final[int] = 160


def escape_inline(value: str) -> str:
    """Escape a value for inline Markdown.

    Backticks are the dangerous ones: repository text containing one can close
    a code span and let the rest render as markup. Pipes are escaped too so a
    value interpolated near a table cannot introduce a column.
    """
    text = _CONTROL.sub("", value)
    return (
        text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("|", "\\|")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def escape_cell(value: str) -> str:
    """Escape a value for a table cell and bound its length.

    A cell is truncated rather than wrapped: an unbounded value from repository
    content would push a table past any width and make the whole report
    unreadable.
    """
    text = escape_inline(value)
    if len(text) > MAX_CELL_LENGTH:
        return text[: MAX_CELL_LENGTH - 1] + "…"
    return text


def table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines
```

- [ ] **Step 4: Point `markdown_report.py` at it**

Delete `_CONTROL`, `MAX_CELL_LENGTH`, `_inline`, `_cell`, and `_table` from `markdown_report.py`. Add:

```python
from codeatlas.delivery.markdown_text import escape_cell, escape_inline, table
```

Then replace every call: `_inline(` → `escape_inline(`, `_cell(` → `escape_cell(`, `_table(` → `table(`. Remove the now-unused `re` import and the `Iterable` import if nothing else in the file uses them — check before deleting.

**This step changes no behaviour.** If a test fails, an identifier was missed.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_markdown_text.py tests/contract/test_change_cross_adapter.py -v`
Expected: PASS. The cross-adapter suite is the proof the move was behaviour-preserving.

- [ ] **Step 6: Typecheck and lint**

Run: `uv run mypy --no-incremental src` and `uv run ruff check src tests`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/codeatlas/delivery tests/unit/test_markdown_text.py
git commit -m "refactor: extract Markdown escaping into its own module"
```

---

### Task 2: The audit renderer gains test-gap reasons

`render_markdown` shows bare gap names. ADR-0016 gave every gap a `GapReason`, and no renderer shows it — so the data that most distinguishes the product is invisible outside the web screen.

**Files:**
- Modify: `src/codeatlas/delivery/markdown_report.py` (`_test_gaps`, line 161)
- Create: `tests/unit/test_markdown_report.py`

**Interfaces:**
- Consumes: `escape_inline` from Task 1.
- Produces: no new public name. `render_markdown`'s signature is unchanged.

- [ ] **Step 1: Write the failing test**

```python
"""The audit rendering of one change analysis."""

from __future__ import annotations

from codeatlas.contracts import (
    AnalysisSide,
    AnalysisStateRef,
    ChangeAnalysisKind,
    ChangeAnalysisReport,
    ChangeAnalysisStatus,
    ChangeEvidenceItem,
    Derivation,
    GapReason,
    GapReasonCode,
    OverallRisk,
    SnapshotFreshness,
)
from codeatlas.delivery import render_markdown


def _state(ref: str) -> AnalysisStateRef:
    return AnalysisStateRef(
        ref=ref,
        commit="a1b2c3d",
        freshness=SnapshotFreshness.FRESH,
        snapshot_id=None,
    )


def _report(**overrides: object) -> ChangeAnalysisReport:
    fields: dict[str, object] = {
        "analysis_id": "a1",
        "repository_id": "r1",
        "request_id": "q1",
        "kind": ChangeAnalysisKind.WORKING_TREE,
        "status": ChangeAnalysisStatus.COMPLETE,
        "overall_risk": OverallRisk.LOW,
        "base": _state("HEAD"),
        "target": _state("working-tree"),
    }
    fields.update(overrides)
    return ChangeAnalysisReport(**fields)  # type: ignore[arg-type]


def test_a_gap_carries_its_reason_and_explanation() -> None:
    markdown = render_markdown(
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

    assert "orders.Order" in markdown
    assert "FIXTURE_MEDIATED_ONLY" in markdown
    assert "only through a fixture" in markdown


def test_a_gap_with_no_reason_still_appears() -> None:
    # The name is a real finding of the analysis even when no reason
    # accompanied it. Dropping it would under-report the gap list.
    markdown = render_markdown(_report(test_gaps=["orders.Order"]))

    assert "orders.Order" in markdown


def test_the_disclaimer_is_present_whenever_a_gap_is() -> None:
    markdown = render_markdown(_report(test_gaps=["orders.Order"]))

    assert "does not prove absence of coverage" in markdown
    assert "does not execute tests" in markdown


def test_a_gap_reason_cites_its_evidence() -> None:
    markdown = render_markdown(
        _report(
            test_gaps=["orders.Order"],
            test_gap_reasons=[
                GapReason(
                    qualified_name="orders.Order",
                    reason=GapReasonCode.FIXTURE_MEDIATED_ONLY,
                    explanation="Reached through a fixture.",
                    evidence_ids=["e1"],
                )
            ],
            evidence=[
                ChangeEvidenceItem(
                    evidence_id="e1",
                    side=AnalysisSide.TARGET,
                    file_path="src/orders.py",
                    symbol=None,
                    start_line=1,
                    end_line=2,
                    content_hash="h",
                    derivation=Derivation.DETERMINISTIC,
                    confidence=1.0,
                )
            ],
        )
    )

    assert "src/orders.py" in markdown


def test_a_hostile_gap_name_is_escaped() -> None:
    markdown = render_markdown(_report(test_gaps=["a|b`c"]))

    assert "a\\|b\\`c" in markdown
```

Check the real enum member names in `src/codeatlas/contracts.py` before running — `AnalysisSide`, `ChangeAnalysisKind`, `ChangeAnalysisStatus`, `OverallRisk`, and `SnapshotFreshness` must be spelled as they are defined. Correct them if they differ and note it in your report.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_markdown_report.py -v`
Expected: the reason and explanation tests FAIL. The disclaimer, no-reason, and escaping tests pass already — they are regression guards, keep them.

- [ ] **Step 3: Implement**

Replace `_test_gaps` in `markdown_report.py`:

```python
def _test_gaps(report: ChangeAnalysisReport) -> list[str]:
    """Every gap, with the reason it is still a gap.

    The disclaimer is not a footnote to be trimmed. A missing `TESTS` edge does
    not prove absence of coverage, and only executing the suite could cross
    that line — which CodeAtlas does not do.
    """
    if not report.test_gaps:
        return []

    by_name = {item.qualified_name: item for item in report.test_gap_reasons}
    by_id = {item.evidence_id: item for item in report.evidence}

    lines = [
        "## Possible test gaps",
        "",
        "A missing `TESTS` edge does not prove absence of coverage. CodeAtlas "
        "does not execute tests and cannot claim any symbol is untested.",
        "",
    ]
    for name in report.test_gaps:
        lines.append(f"- `{escape_inline(name)}`")
        reason = by_name.get(name)
        if reason is None:
            # A gap with no recorded reason is still a gap. Reporting the name
            # alone is honest; inventing a reason would not be.
            continue
        lines.append(f"  - Reason: `{escape_inline(reason.reason.value)}`")
        lines.append(f"  - {escape_inline(reason.explanation)}")
        for evidence_id in reason.evidence_ids:
            item = by_id.get(evidence_id)
            if item is not None:
                lines.append(f"  - Evidence: {_location(item)}")
    lines.append("")
    return lines
```

`_location` already exists at the bottom of the file and renders one evidence item as `` `path` lines N-M (side) ``.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_markdown_report.py tests/contract/test_change_cross_adapter.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codeatlas/delivery/markdown_report.py tests/unit/test_markdown_report.py
git commit -m "feat: render test-gap reasons in the audit Markdown report"
```

---

### Task 3: The PR renderer — verdict, findings, gaps

The part a reviewer must act on. Everything here is expanded; Task 4 adds the collapsed remainder.

**Files:**
- Create: `src/codeatlas/delivery/pr_report.py`
- Create: `tests/unit/test_pr_report.py`
- Modify: `src/codeatlas/delivery/__init__.py`

**Interfaces:**
- Consumes: `escape_inline`, `escape_cell`, `table` from Task 1.
- Produces: `render_pr_markdown(report: ChangeAnalysisReport) -> str`, exported from `codeatlas.delivery`.

- [ ] **Step 1: Write the failing test**

Reuse the `_state` / `_report` helpers from Task 2's test module by copying them into this file — a test module that imports fixtures from another test module couples two suites that should fail independently.

```python
def test_the_risk_leads_the_report() -> None:
    markdown = render_pr_markdown(_report(overall_risk=OverallRisk.HIGH))

    # The verdict is the first thing a reviewer sees, per the PRD's
    # "ordered by risk. This is the product."
    assert markdown.splitlines()[0].startswith("## CodeAtlas preflight")
    assert "HIGH" in markdown.splitlines()[0]


def test_both_refs_and_their_freshness_are_stated() -> None:
    markdown = render_pr_markdown(_report())

    assert "HEAD" in markdown
    assert "fresh" in markdown


def test_findings_are_ordered_most_severe_first() -> None:
    markdown = render_pr_markdown(
        _report(
            findings=[
                _finding(Severity.LOW, "Low one"),
                _finding(Severity.CRITICAL, "Critical one"),
            ]
        )
    )

    assert markdown.index("Critical one") < markdown.index("Low one")


def test_a_finding_shows_derivation_and_confidence_separately() -> None:
    # A high confidence score never implies a stronger derivation.
    markdown = render_pr_markdown(_report(findings=[_finding(Severity.HIGH, "T")]))

    assert "static_resolved" in markdown
    assert "0.90" in markdown


def test_no_findings_is_not_a_safety_claim() -> None:
    markdown = render_pr_markdown(_report())

    assert "not a claim that the change is safe" in markdown


def test_the_gap_disclaimer_is_present_whenever_a_gap_is() -> None:
    markdown = render_pr_markdown(_report(test_gaps=["orders.Order"]))

    assert "does not prove absence of coverage" in markdown
    assert "does not execute tests" in markdown


def test_the_gap_heading_says_possible_and_never_untested() -> None:
    markdown = render_pr_markdown(_report(test_gaps=["orders.Order"]))

    assert "Possible test gaps" in markdown
    assert "untested" not in markdown.lower().replace(
        "cannot claim any symbol is untested", ""
    )


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


def test_a_hostile_symbol_name_is_escaped() -> None:
    markdown = render_pr_markdown(_report(test_gaps=["a|b`c"]))

    assert "a\\|b\\`c" in markdown


def test_no_forge_url_is_ever_constructed() -> None:
    # "No GitHub/GitLab or CI integration" is an explicit PRD non-goal, and a
    # guessed permalink is a citation pointing at the wrong code.
    markdown = render_pr_markdown(
        _report(findings=[_finding(Severity.HIGH, "T")], test_gaps=["a"])
    )

    assert "http://" not in markdown
    assert "https://" not in markdown
```

Add a `_finding(severity, title)` helper in the same module building a `Finding` with `code="PUBLIC_CONTRACT_CHANGED"`, `derivation=Derivation.STATIC_RESOLVED`, `confidence=0.9`, `evidence_ids=[]`.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_pr_report.py -v`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Implement**

```python
"""A rendering of one change analysis shaped for a pull request.

`render_markdown` is the audit format: complete, flat, every evidence row
present. That is right for an archive and wrong for a review. A reviewer wants
a verdict, the risks in order, and the option to expand the rest.

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
from codeatlas.delivery.markdown_text import escape_inline

_SEVERITY_ORDER: Final[tuple[Severity, ...]] = (
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
)


def render_pr_markdown(report: ChangeAnalysisReport) -> str:
    """Render one persisted analysis for pasting into a pull request."""
    lines = _headline(report) + _findings(report) + _gaps(report)
    return "\n".join(lines).rstrip() + "\n"


def _headline(report: ChangeAnalysisReport) -> list[str]:
    symbols = len(report.changed_symbols)
    files = len(report.changed_files)
    findings = len(report.findings)
    gaps = len(report.test_gaps)
    return [
        f"## CodeAtlas preflight — **{escape_inline(report.overall_risk.value.upper())}** risk",
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
        for finding in [f for f in report.findings if f.severity is severity]:
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
    for name in report.test_gaps:
        lines.append(_one_gap(name, by_name.get(name)))
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
```

Export it from `src/codeatlas/delivery/__init__.py`:

```python
from codeatlas.delivery.pr_report import render_pr_markdown

__all__ = ["render_markdown", "render_pr_markdown", "render_sarif"]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_pr_report.py -v`
Expected: PASS.

- [ ] **Step 5: Mutation-check the disclaimer**

Temporarily delete the disclaimer line from `_gaps`. Confirm `test_the_gap_disclaimer_is_present_whenever_a_gap_is` FAILS. Restore it and confirm it passes. Record both halves in your report.

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/delivery tests/unit/test_pr_report.py
git commit -m "feat: PR Markdown rendering of verdict, findings, and test gaps"
```

---

### Task 4: The PR renderer — collapsed supporting sections

**Files:**
- Modify: `src/codeatlas/delivery/pr_report.py`
- Modify: `tests/unit/test_pr_report.py`

**Interfaces:**
- Consumes: Task 3's `render_pr_markdown`.
- Produces: `render_pr_markdown` output additionally containing three `<details>` sections and a notes section. No new public name.

- [ ] **Step 1: Write the failing test**

```python
def test_supporting_detail_is_collapsed_not_dropped() -> None:
    markdown = render_pr_markdown(
        _report(changed_symbols=[_symbol()], impact_edges=[_edge()])
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
```

Add `_symbol()`, `_edge(...)`, and `_file(path)` helpers building the corresponding contract models.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_pr_report.py -v`
Expected: the new tests FAIL; Task 3's continue to pass.

- [ ] **Step 3: Implement**

Add to `pr_report.py`, and extend `render_pr_markdown` to append `_details(report) + _notes(report)`:

```python
def _details(report: ChangeAnalysisReport) -> list[str]:
    """Supporting detail, folded.

    Collapsing costs nothing and hides nothing — the content is present in the
    document. An empty section is omitted rather than rendered empty: a
    disclosure triangle over nothing wastes a reader's click.
    """
    lines: list[str] = []

    if report.changed_symbols or report.changed_files:
        rows = [
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
        lines += _fold(
            f"What changed ({len(rows)})",
            table(("Symbol", "Kind", "Change", "File"), rows),
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
        lines += _fold(
            f"What it reaches ({len(rows)})",
            table(("Changed", "Relation", "Reaches", "Derivation"), rows),
        )

    if report.evidence:
        rows = [
            (
                escape_cell(item.file_path),
                escape_cell(f"{item.start_line}-{item.end_line}"),
                escape_cell(item.side.value),
                escape_cell(item.symbol or ""),
                escape_cell(item.derivation.value),
            )
            for item in report.evidence
        ]
        lines += _fold(
            f"Evidence ({len(rows)})",
            table(("File", "Lines", "Side", "Symbol", "Derivation"), rows),
        )

    return lines


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
```

Import `escape_cell` and `table` from `markdown_text` alongside `escape_inline`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_pr_report.py -v`
Expected: PASS.

- [ ] **Step 5: Mutation-check the derivation column**

Temporarily drop the derivation cell from the impact rows. Confirm `test_every_impact_edge_shows_its_derivation` FAILS. Restore and confirm it passes.

- [ ] **Step 6: Add the escaping-parity test**

This is the test that fails if the two renderers ever stop sharing
`markdown_text`. Add it to `tests/unit/test_pr_report.py`:

```python
def test_both_renderers_escape_a_hostile_name_identically() -> None:
    """The two renderings differ in shape, never in how they neutralise text.

    If someone later gives one renderer its own escaping — or "fixes" one and
    not the other — this is what catches it. Escaping untrusted repository
    text is the one thing the two must never diverge on.
    """
    hostile = "a|b`c<d>e\\f"
    report = _report(test_gaps=[hostile])

    audit = render_markdown(report)
    pull_request = render_pr_markdown(report)

    escaped = escape_inline(hostile)
    assert escaped in audit
    assert escaped in pull_request
```

Import `render_markdown` and `escape_inline` alongside the existing imports.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/unit/test_pr_report.py tests/unit/test_markdown_report.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/codeatlas/delivery/pr_report.py tests/unit/test_pr_report.py
git commit -m "feat: collapsed supporting sections in the PR report"
```

---

### Task 5: Bounding

**Files:**
- Modify: `src/codeatlas/delivery/pr_report.py`
- Modify: `tests/unit/test_pr_report.py`

**Interfaces:**
- Consumes: Task 4's section builders.
- Produces: `MAX_CHARACTERS: Final[int] = 60_000` on `pr_report`. `render_pr_markdown`'s signature is unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_a_large_report_stays_within_the_bound() -> None:
    markdown = render_pr_markdown(_report(evidence=[_evidence(i) for i in range(4000)]))

    assert len(markdown) <= MAX_CHARACTERS


def test_an_omission_is_declared() -> None:
    # A report that quietly drops content is worse than one that does not fit.
    markdown = render_pr_markdown(_report(evidence=[_evidence(i) for i in range(4000)]))

    assert "omitted" in markdown.lower()
    assert "markdown" in markdown.lower()


def test_findings_and_gaps_survive_truncation() -> None:
    # They are rendered first precisely so the budget is spent on supporting
    # detail instead.
    markdown = render_pr_markdown(
        _report(
            findings=[_finding(Severity.CRITICAL, "Critical one")],
            test_gaps=["orders.Order"],
            evidence=[_evidence(i) for i in range(4000)],
        )
    )

    assert "Critical one" in markdown
    assert "orders.Order" in markdown
    assert "does not prove absence of coverage" in markdown


def test_a_small_report_is_not_truncated() -> None:
    markdown = render_pr_markdown(_report(impact_edges=[_edge()]))

    assert "omitted" not in markdown.lower()
    assert "What it reaches" in markdown
```

Add an `_evidence(index)` helper producing a distinct `ChangeEvidenceItem` per index.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_pr_report.py -v`
Expected: the bound and omission tests FAIL — output is currently unbounded.

- [ ] **Step 3: Implement**

Restructure `render_pr_markdown` so the sections that may be cut are added one at a time while the budget allows:

```python
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

    kept: list[str] = []
    omitted: list[str] = []
    fixed = _length(essential) + _length(notes)

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
        f"> Omitted to fit: {names}. "
        "Use the `markdown` or `json` report format for the complete analysis.",
        "",
    ]


def _length(lines: Sequence[str]) -> int:
    return sum(len(line) + 1 for line in lines)
```

`_optional_sections(report)` returns `list[tuple[str, list[str]]]` — the three folded blocks from Task 4, each paired with its display name, omitting any that would be empty. Refactor `_details` into it rather than duplicating the row-building.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_pr_report.py -v`
Expected: PASS.

- [ ] **Step 5: Mutation-check the omission notice**

Temporarily return `[]` from `_omission_notice`. Confirm `test_an_omission_is_declared` FAILS. Restore and confirm it passes. A silent cut is the exact defect this task exists to prevent, so the guard must be real.

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/delivery/pr_report.py tests/unit/test_pr_report.py
git commit -m "feat: bound the PR report and declare any omission"
```

---

### Task 6: Wire `pr` through REST, CLI, and MCP

**Files:**
- Modify: `src/codeatlas/api/routers/change_analysis.py:22` and `:87`
- Modify: `src/codeatlas/cli/main.py:1240`, `:1292`, `:1312`
- Modify: `src/codeatlas/mcp/tools.py:110` and `:495`
- Modify: `tests/contract/test_change_cross_adapter.py`

**Interfaces:**
- Consumes: `render_pr_markdown` from `codeatlas.delivery`.
- Produces: `"pr"` accepted by all three adapters.

- [ ] **Step 1: Write the failing test**

Add to `tests/contract/test_change_cross_adapter.py`, following its existing fixture and invocation conventions:

The file already has tests that reach an analysis through all three adapters — find the one covering `markdown` or `sarif` and mirror its structure exactly, changing only the format value and the assertions. Do not invent a new fixture or a new way of reaching an adapter.

The three call shapes it already uses:

- REST — the FastAPI test client: `GET /v1/change-analysis/{analysis_id}/report?report_format=pr`, then read `response.text`.
- CLI — the Typer runner over `analysis <analysis_id> --format pr`, then read the captured stdout.
- MCP — the registry built by `build_registry`, invoking the change-report tool with `{"analysis_id": ..., "report_format": "pr"}`, then read `result["content"]`.

The assertions are the contract:

```python
    # "Four ways in, one brain": a format present in one adapter and not the
    # others contradicts the claim the PRD makes.
    assert "## CodeAtlas preflight" in rest_text
    assert "## CodeAtlas preflight" in cli_text
    assert "## CodeAtlas preflight" in mcp_text

    # Every format reads the same persisted rows, so the same analysis must
    # render identically regardless of which door it came through.
    assert rest_text.strip() == mcp_text.strip()
    assert rest_text.strip() == cli_text.strip()
```

If the CLI runner appends a trailing newline that the others do not, `.strip()` absorbs it — that is a transport artefact, not a rendering difference. If the texts differ in any other way, stop and report it: that is a real divergence between adapters and this test exists to catch exactly that.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/contract/test_change_cross_adapter.py -v`
Expected: FAIL — `"pr"` is rejected by each adapter's validation.

- [ ] **Step 3: REST**

`src/codeatlas/api/routers/change_analysis.py`:

```python
ReportFormat = Literal["json", "markdown", "pr", "sarif"]
```

and in `get_report`, before the `sarif` branch:

```python
    if report_format == "pr":
        return PlainTextResponse(
            render_pr_markdown(report), media_type="text/markdown; charset=utf-8"
        )
```

Import `render_pr_markdown` alongside the existing delivery imports.

- [ ] **Step 4: MCP**

`src/codeatlas/mcp/tools.py`:

```python
    report_format: Literal["json", "markdown", "pr", "sarif"] = "json"
```

and in `_get_change_report`:

```python
    if payload.report_format == "pr":
        return {"format": "pr", "content": render_pr_markdown(report)}
```

An agent reads this schema to learn what it may ask for, so the `Literal` is the part that matters, not only the branch.

- [ ] **Step 5: CLI**

`src/codeatlas/cli/main.py` — add the branch in `_print_report`:

```python
    elif report_format == "pr":
        typer.echo(render_pr_markdown(report))
```

and update **both** help strings, at `:1240` and `:1292`:

```python
        str, typer.Option("--format", help="json, markdown, pr, or sarif.")
```

Help that enumerates options is a promise about them; leaving one stale makes the two commands disagree.

**Leave `_print_report`'s `else` fallback alone.** It silently prints JSON for an unknown format. That is a real wart and is recorded as a follow-up in Task 7 — changing it is a CLI behaviour change that could break a script relying on the leniency, and it is not what this slice is for.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/contract/test_change_cross_adapter.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/codeatlas/api src/codeatlas/cli src/codeatlas/mcp tests/contract
git commit -m "feat: expose the pr report format through REST, CLI, and MCP"
```

---

### Task 7: Quality gate and documentation

**Files:**
- Modify: `docs/operations/change-analysis.md`
- Modify: `documentation/memory.md`
- Modify: `docs/plans/PLAN.md`

- [ ] **Step 1: Run the full quality gate**

```bash
uv run ruff check src tests scripts
uv run mypy --no-incremental src
uv run pytest -q
```

Record each command, its exit code, and its output. Fix failures; do not skip or weaken a test to get green.

- [ ] **Step 2: Confirm SARIF is untouched**

```bash
git diff main...HEAD -- src/codeatlas/delivery/sarif_report.py
```

Expected: empty. A test gap is explicitly not a finding, and emitting gaps as SARIF results would assert what ADR-0016 refuses. If this diff is non-empty, stop and report it.

- [ ] **Step 3: Confirm the contract did not move**

```bash
git diff main...HEAD -- src/codeatlas/storage/sqlite/migrations
grep -n 'CONTRACT_VERSION' src/codeatlas/contracts.py
```

Expected: no migration change; `contract_version` still `"1.1"`.

- [ ] **Step 4: Document the format**

`docs/operations/change-analysis.md` gains a section covering: what `pr` renders and in what order; that findings and gaps are never truncated while supporting detail may be, with any omission declared; that it contains no forge URLs and posts nothing; and when to prefer `markdown` (a complete archival record) or `json` (anything scripted).

- [ ] **Step 5: Update the living docs**

- `documentation/memory.md` — append to Completed. Record that the audit renderer had never shown `GapReason` data, so it was invisible to every CLI, REST, and MCP consumer until now. Add the follow-up: `_print_report` (`src/codeatlas/cli/main.py:1312`) falls through to JSON for an unknown `--format`, so `--format prr` prints JSON and reports success; REST and MCP reject unknown values at the boundary and do not share the wart.
- `docs/plans/PLAN.md` — **append** a handoff entry. Never rewrite an earlier one.

- [ ] **Step 6: Commit**

```bash
git add docs documentation
git commit -m "docs: document the pr report format"
```

---

## Notes for the implementer

**Test helper names are illustrative.** `_report`, `_state`, `_finding`, `_symbol`, `_edge`, `_file`, and `_evidence` describe what each helper must build. The assertions are the contract.

**Check enum member names before running.** This plan spells contract enums as `Severity.CRITICAL`, `Derivation.STATIC_RESOLVED`, `GapReasonCode.FIXTURE_MEDIATED_ONLY`, `AnalysisSide.TARGET`, `RelationKind.TESTS`, `SnapshotFreshness.FRESH`, `OverallRisk.LOW`, `ChangeAnalysisKind.WORKING_TREE`, `ChangeAnalysisStatus.COMPLETE`. Verify each against `src/codeatlas/contracts.py` and correct any that differ, noting the correction in your report.

**Line numbers drift.** Every `path:line` reference was accurate at `f0439b2`. If a line does not contain what this plan says, locate the construct by name.

**The four invariants that must not be compromised:**
1. Both renderers escape untrusted text through `markdown_text` — never a local copy (Task 1).
2. Every impact edge renders its derivation (Task 4, mutation-checked).
3. The gap disclaimer renders whenever any gap renders (Task 3, mutation-checked).
4. Any omission is declared, and findings and gaps are never what gets cut (Task 5, mutation-checked).
