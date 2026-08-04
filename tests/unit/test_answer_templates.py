"""Deterministic answer rendering (P5-03, ADR-0006 decision 3).

No LLM is admitted in Phase 5, so an assistant message is a template filled
with values the deterministic pipeline produced. The tests below are mostly
about one property: repository text is *data*. It appears inside code spans,
never as Markdown structure and never as an instruction the reader or a later
model could act on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from codeatlas.contracts import (
    Answer,
    Claim,
    Derivation,
    Evidence,
    EvidenceValidation,
    QueryResponse,
    SnapshotFreshness,
    SnapshotReference,
)
from codeatlas.conversations.intent import Intent
from codeatlas.conversations.templates import render_answer

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _evidence(
    evidence_id: str = "e1",
    symbol: str | None = "capture",
    excerpt: str = "def capture(self, key): ...",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        repository_id="repo_1",
        snapshot_id="snap_1",
        file_path="src/payments/service.py",
        symbol=symbol,
        start_line=7,
        end_line=8,
        excerpt=excerpt,
        content_hash="abc123",
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
        validation=EvidenceValidation.VALID,
    )


def _response(
    *,
    summary: str = "capture is defined in src/payments/service.py lines 7-8.",
    claims: list[Claim] | None = None,
    evidence: list[Evidence] | None = None,
    warnings: list[str] | None = None,
    limitations: list[str] | None = None,
) -> QueryResponse:
    return QueryResponse(
        request_id="req_1",
        repository_id="repo_1",
        snapshot=SnapshotReference(
            snapshot_id="snap_1",
            git_head=None,
            working_tree_fingerprint="fp",
            freshness=SnapshotFreshness.FRESH,
            semantic_coverage=0.0,
        ),
        answer=Answer(
            summary=summary,
            claims=claims
            if claims is not None
            else [
                Claim(
                    claim_id="c1",
                    text="capture is defined at src/payments/service.py:7-8.",
                    derivation=Derivation.DETERMINISTIC,
                    confidence=1.0,
                    evidence_ids=["e1"],
                )
            ],
        ),
        evidence=evidence if evidence is not None else [_evidence()],
        warnings=warnings or [],
        limitations=limitations or [],
    )


def test_the_summary_leads_the_answer() -> None:
    rendered = render_answer(_response(), intent=Intent.EXACT_SYMBOL)

    assert rendered.splitlines()[0].startswith(
        "capture is defined in src/payments/service.py"
    )


def test_every_claim_is_rendered_with_its_citation() -> None:
    rendered = render_answer(_response(), intent=Intent.EXACT_SYMBOL)

    assert "src/payments/service.py:7-8" in rendered
    assert "[1]" in rendered


def test_a_file_path_renders_inside_a_code_span() -> None:
    """Repository text is data. A path outside a code span could be read as
    Markdown structure, and a link target is one character away from that.

    Asserted against the project overview, which is where the template still
    renders evidence locations itself. The exact-symbol answer no longer lists
    them: its citations are rendered as buttons by the web client, and the path
    travels on the button rather than in the prose.
    """
    rendered = render_answer(_response(), intent=Intent.PROJECT_OVERVIEW)

    assert "`src/payments/service.py:7-8`" in rendered


def test_a_hostile_symbol_name_cannot_break_out_of_its_code_span() -> None:
    """A repository is untrusted input all the way to the rendered answer.

    Markup *inside* a code span is inert, so the property to assert is not that
    `**bold**` is absent — it is that the value cannot **close** the span it
    sits in. Every backtick the repository supplied must be gone, leaving the
    line with balanced spans.
    """
    hostile = "capture` **bold** [x](http://evil) `"
    rendered = render_answer(
        _response(evidence=[_evidence(symbol=hostile)]),
        intent=Intent.PROJECT_OVERVIEW,
    )

    line = next(item for item in rendered.splitlines() if "**bold**" in item)
    # Two spans on this line — the location and the symbol — so four backticks
    # exactly. Any backtick from the repository would make it odd.
    assert line.count("`") == 4
    assert line.count("`") % 2 == 0


def test_control_characters_are_stripped_from_repository_values() -> None:
    rendered = render_answer(
        _response(evidence=[_evidence(symbol="capture\r\x1b[2Jcleared")]),
        intent=Intent.EXACT_SYMBOL,
    )

    assert "\x1b" not in rendered
    assert "\r" not in rendered


def test_warnings_and_limitations_are_shown_not_hidden() -> None:
    rendered = render_answer(
        _response(
            warnings=["GRAPH_TRUNCATED_DEPTH"],
            limitations=["Traversal stopped at depth 3."],
        ),
        intent=Intent.CALLERS,
    )

    assert "GRAPH_TRUNCATED_DEPTH" in rendered
    assert "Traversal stopped at depth 3." in rendered


def test_known_warning_codes_render_as_reader_facing_notes() -> None:
    rendered = render_answer(
        _response(
            warnings=["EVIDENCE_EXCERPT_TRUNCATED", "LEXICAL_QUERY_RELAXED"],
        ),
        intent=Intent.TEXT,
    )

    assert "Some cited excerpts were shortened" in rendered
    assert "CodeAtlas broadened the search terms" in rendered
    assert "EVIDENCE_EXCERPT_TRUNCATED" not in rendered
    assert "LEXICAL_QUERY_RELAXED" not in rendered


def test_an_abstention_names_what_was_tried() -> None:
    """An abstention is only useful with the reason attached (Section 4.1)."""
    rendered = render_answer(
        _response(
            summary="No symbol named 'missing' exists in the active snapshot.",
            claims=[],
            evidence=[],
        ),
        intent=Intent.EXACT_SYMBOL,
    )

    assert "No symbol named" in rendered
    assert "exact symbol" in rendered.lower()
    # An abstention must not present an empty evidence list as a finding.
    assert "[1]" not in rendered


def test_a_greeting_renders_without_abstention_language() -> None:
    rendered = render_answer(
        _response(
            summary="Hi. Ask me about the active repository.",
            claims=[],
            evidence=[],
        ),
        intent=Intent.GREETING,
    )

    assert rendered == "Hi. Ask me about the active repository.\n"
    assert "not answering rather than guessing" not in rendered


def test_a_project_overview_groups_evidence_into_an_answer() -> None:
    rendered = render_answer(
        _response(
            summary="Found 4 locations matching 'tell me about the project' by text.",
            claims=[],
            evidence=[
                _evidence("e1", symbol="Overview"),
                _evidence(
                    "e2",
                    symbol="backend.src.prelegal.main",
                    excerpt="from fastapi import FastAPI",
                ).model_copy(update={"file_path": "backend/src/prelegal/main.py"}),
                _evidence(
                    "e3",
                    symbol="PreviewForCurrentDoc",
                    excerpt="export function PreviewForCurrentDoc",
                ).model_copy(update={"file_path": "frontend/src/app/page.tsx"}),
                _evidence("e4", symbol="Running").model_copy(
                    update={"file_path": "docs/run.md"}
                ),
            ],
            limitations=["Project overview limitation."],
        ),
        intent=Intent.PROJECT_OVERVIEW,
    )

    assert "Here is the project-level view" in rendered
    assert "Project documentation is concentrated" in rendered
    assert "Backend or Python evidence appears" in rendered
    assert "Frontend evidence appears" in rendered
    assert "Found 4 locations matching" not in rendered
    assert "contains text matching" not in rendered


def test_rendering_is_deterministic() -> None:
    response = _response()
    assert render_answer(response, intent=Intent.EXACT_SYMBOL) == render_answer(
        response, intent=Intent.EXACT_SYMBOL
    )


def test_the_rendered_answer_is_bounded() -> None:
    """A message column is not a place to paste a repository."""
    many = [
        Claim(
            claim_id=f"c{index}",
            text=f"claim {index}",
            derivation=Derivation.DETERMINISTIC,
            confidence=1.0,
            evidence_ids=["e1"],
        )
        for index in range(500)
    ]
    rendered = render_answer(_response(claims=many), intent=Intent.EXACT_SYMBOL)

    assert len(rendered.encode("utf-8")) <= 64 * 1024


def test_an_excerpt_is_never_interpolated_into_the_message() -> None:
    """The excerpt is raw repository source. It belongs in the evidence drawer
    (P5-09), fetched and re-verified there — not pasted into prose where its
    Markdown would render."""
    rendered = render_answer(
        _response(
            evidence=[
                _evidence(excerpt="# Heading\n\n**bold** <script>alert(1)</script>")
            ]
        ),
        intent=Intent.EXACT_SYMBOL,
    )

    assert "<script>" not in rendered
    assert "**bold**" not in rendered
    assert "# Heading" not in rendered


# --- generated prose -----------------------------------------------------


def test_a_generated_summary_keeps_its_markdown_structure() -> None:
    """The readable structure is the point of generating prose at all.

    Escaping it the way a template summary is escaped turned a formatted
    explanation into one run-on line of literal backslashes, which reads worse
    than the deterministic list it replaced.
    """
    rendered = render_answer(
        _response(
            summary="**Backend**\n\n* FastAPI serves the API.\n* Next.js renders."
        ),
        intent=Intent.TEXT,
        generated=True,
    )

    assert "**Backend**" in rendered
    assert r"\*\*" not in rendered
    assert "* FastAPI serves the API." in rendered


def test_a_template_summary_is_still_escaped() -> None:
    """Unchanged for everything CodeAtlas writes itself.

    A template summary interpolates repository values, and a file genuinely
    named `**evil**.py` must not render as bold.
    """
    rendered = render_answer(
        _response(summary="Found **evil**.py in the tree."),
        intent=Intent.TEXT,
    )

    assert r"\*\*evil\*\*" in rendered


def test_control_characters_are_stripped_from_generated_prose() -> None:
    rendered = render_answer(
        _response(summary="Clean\x07text\x00here"),
        intent=Intent.TEXT,
        generated=True,
    )

    assert "\x07" not in rendered
    assert "\x00" not in rendered
    assert "Cleantexthere" in rendered


def test_generated_prose_still_carries_its_citations() -> None:
    """Prose replaces the summary. The claims below it are untouched."""
    rendered = render_answer(
        _response(summary="A clear explanation."),
        intent=Intent.TEXT,
        generated=True,
    )

    assert "A clear explanation." in rendered
    assert "[1]" in rendered


def test_the_answer_does_not_repeat_its_evidence_as_a_list() -> None:
    """The citation markers are the evidence surface now.

    The list duplicated what every claim already carried, in a less useful
    form, and it sat between the answer and the controls that act on it.
    """
    rendered = render_answer(_response(), intent=Intent.EXACT_SYMBOL)

    assert "**Evidence**" not in rendered


def test_claims_keep_their_citation_markers() -> None:
    """Removing the list must not remove the citations themselves."""
    rendered = render_answer(_response(), intent=Intent.EXACT_SYMBOL)

    assert "[1]" in rendered


def test_key_evidence_entries_carry_a_citation_marker() -> None:
    """The overview keeps its curated shortlist, but it is not inert text.

    Each entry leads with the same `[n]` marker the claims use, so the web
    client renders it as a button through one mechanism rather than two.
    """
    rendered = render_answer(_response(), intent=Intent.PROJECT_OVERVIEW)

    key_evidence = rendered.split("**Key Evidence**")[1]

    assert "[1]" in key_evidence.splitlines()[1]
