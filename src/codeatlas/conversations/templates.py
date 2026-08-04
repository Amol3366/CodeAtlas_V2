"""Deterministic rendering of a verified answer.

No LLM participates in Phase 5, so an assistant message is a template filled
with values the deterministic pipeline produced. That makes rendering a
security surface rather than a presentation detail: every interpolated value
comes from the repository, and the repository is untrusted input all the way to
the message column.

The rule is simple and absolute — **repository text appears inside a code span,
escaped, and nowhere else.** A path, symbol, or excerpt outside one could close
a span, introduce Markdown structure, or read as an instruction. Prose around
those values is written here, in this file, by us.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from typing import Final

from codeatlas.contracts import Evidence, QueryResponse
from codeatlas.conversations.intent import Intent

# Matches the storage bound on message content: an answer is a summary, not a
# place to paste a repository.
MAX_ANSWER_BYTES: Final[int] = 64 * 1024

_CONTROL: Final[re.Pattern[str]] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# What each intent tried, named in the reader's words. An abstention that does
# not say what was attempted is not useful (`AGENTS.md` Section 4.1).
_CHANNEL_NAMES: Final[dict[Intent, str]] = {
    Intent.EXACT_SYMBOL: "exact symbol and path resolution",
    Intent.CALLERS: "the call graph (callers)",
    Intent.CALLEES: "the call graph (callees)",
    Intent.DEPENDENCIES: "stored dependency relations",
    Intent.TESTS: "stored test relations",
    Intent.DOCUMENTS: "stored document relations",
    Intent.TRACE: "bounded relation-path traversal",
    Intent.CHANGE: "change analysis",
    Intent.PROJECT_OVERVIEW: "project overview retrieval over the active snapshot",
    Intent.TEXT: "lexical search over the active snapshot",
}
PROJECT_OVERVIEW_EVIDENCE_LIMIT: Final[int] = 10

_WARNING_MESSAGES: Final[dict[str, str]] = {
    "EVIDENCE_EXCERPT_TRUNCATED": (
        "Some cited excerpts were shortened to fit display limits; the "
        "citations still point to the full indexed file ranges."
    ),
    "LEXICAL_QUERY_RELAXED": (
        "The exact text query matched nothing, so CodeAtlas broadened the "
        "search terms before returning evidence."
    ),
}


def render_answer(
    response: QueryResponse, *, intent: Intent, generated: bool = False
) -> str:
    """Render one verified response as the assistant's Markdown message.

    ``generated`` says a model wrote the summary. It changes only how the
    summary is neutralized — see `_model_prose` — and nothing else. Claims,
    citations, warnings, and limitations render identically either way, because
    generation never produced them.
    """
    summary = (
        _model_prose(response.answer.summary)
        if generated
        else _prose(response.answer.summary)
    )

    if intent is Intent.GREETING:
        return _bounded(f"{summary}\n")
    if intent is Intent.PROJECT_OVERVIEW and response.evidence and not generated:
        # The deterministic overview is a template built from evidence. A
        # generated summary has already answered the same question in prose, so
        # replacing it with the template would discard what the model wrote.
        return _render_project_overview(response)

    lines: list[str] = [summary, ""]

    citations = {
        item.evidence_id: ordinal
        for ordinal, item in enumerate(response.evidence, start=1)
    }

    if response.answer.claims:
        for claim in response.answer.claims:
            marks = "".join(
                f"[{citations[evidence_id]}]"
                for evidence_id in claim.evidence_ids
                if evidence_id in citations
            )
            lines.append(f"- {_prose(claim.text)} {marks}".rstrip())
        lines.append("")
    else:
        # An abstention. Naming the channel is the whole value of saying "no".
        lines.append(
            f"CodeAtlas found nothing through {_CHANNEL_NAMES[intent]}, so it "
            "is not answering rather than guessing."
        )
        lines.append("")

    # The evidence list used to be repeated here and is gone deliberately. The
    # `[n]` markers on each claim above are rendered as buttons by the web
    # client, so the list duplicated every citation in a less useful form and
    # pushed the answer's controls below a wall of lines. Path, line range, and
    # derivation now travel on the button itself.
    #
    # Answers persisted before this change keep their own text, including their
    # list. A stored answer is the record of what CodeAtlas said and is never
    # rewritten.

    if response.warnings:
        lines.append("**Warnings**")
        lines.extend(_warning_line(item) for item in response.warnings)
        lines.append("")

    if response.limitations:
        lines.append("**Limitations**")
        lines.extend(f"- {_prose(item)}" for item in response.limitations)
        lines.append("")

    return _bounded("\n".join(lines).rstrip() + "\n")


def _render_project_overview(response: QueryResponse) -> str:
    citations = {
        item.evidence_id: ordinal
        for ordinal, item in enumerate(response.evidence, start=1)
    }
    docs = _first_unique(
        response.evidence,
        lambda item: _is_project_document(item),
        limit=2,
    )
    python_or_backend = _first_unique(
        response.evidence,
        lambda item: _is_python_or_backend(item),
        limit=2,
    )
    frontend = _first_unique(
        response.evidence,
        lambda item: _is_frontend(item),
        limit=2,
    )
    workflow = _first_unique(
        response.evidence,
        lambda item: _is_workflow_document(item),
        limit=2,
    )
    feature_clues = _first_unique(
        response.evidence,
        lambda item: item.symbol is not None and _is_feature_symbol(item.symbol),
        limit=3,
    )

    lines = [
        "Here is the project-level view from the active snapshot.",
        "",
    ]
    if docs:
        detail = _format_symbols(docs)
        suffix = f"; indexed sections include {detail}" if detail else ""
        lines.append(
            f"- Project documentation is concentrated in {_format_paths(docs)}"
            f"{suffix}. {_marks(docs, citations)}"
        )
    if python_or_backend:
        detail = _format_symbols(python_or_backend)
        suffix = f", including {detail}" if detail else ""
        lines.append(
            "- Backend or Python evidence appears in "
            f"{_format_paths(python_or_backend)}{suffix}. "
            f"{_marks(python_or_backend, citations)}"
        )
    if frontend:
        detail = _format_symbols(frontend)
        suffix = f", including {detail}" if detail else ""
        lines.append(
            "- Frontend evidence appears in "
            f"{_format_paths(frontend)}{suffix}. {_marks(frontend, citations)}"
        )
    if workflow:
        lines.append(
            "- Run, setup, or development workflow notes are documented in "
            f"{_format_paths(workflow)}. {_marks(workflow, citations)}"
        )
    if feature_clues:
        lines.append(
            "- The strongest named feature/design clues are "
            f"{_format_symbols(feature_clues)}. {_marks(feature_clues, citations)}"
        )

    if len(lines) == 2:
        top = response.evidence[: min(3, len(response.evidence))]
        lines.append(
            f"- The closest indexed evidence is in {_format_paths(top)}. "
            f"{_marks(top, citations)}"
        )
    lines.append("")

    key_evidence = _overview_evidence(
        docs, python_or_backend, frontend, workflow, feature_clues, response.evidence
    )
    if key_evidence:
        lines.append("**Key Evidence**")
        for item in key_evidence:
            ordinal = citations[item.evidence_id]
            location = f"{item.file_path}:{item.start_line}-{item.end_line}"
            symbol = (
                f" — `{_code(item.symbol)}`"
                if item.symbol and _is_display_symbol(item.symbol)
                else ""
            )
            lines.append(
                f"{ordinal}. `{_code(location)}`{symbol} "
                f"({item.derivation.value}, confidence {item.confidence:.2f})"
            )
        lines.append("")

    if response.warnings:
        lines.append("**Warnings**")
        lines.extend(_warning_line(item) for item in response.warnings)
        lines.append("")

    if response.limitations:
        lines.append("**Limitations**")
        lines.extend(f"- {_prose(item)}" for item in response.limitations)
        lines.append("")

    return _bounded("\n".join(lines).rstrip() + "\n")


def _first_unique(
    evidence: Sequence[Evidence],
    predicate: Callable[[Evidence], bool],
    *,
    limit: int,
) -> list[Evidence]:
    selected: list[Evidence] = []
    seen_paths: set[str] = set()
    for item in evidence:
        if not predicate(item) or item.file_path in seen_paths:
            continue
        selected.append(item)
        seen_paths.add(item.file_path)
        if len(selected) >= limit:
            break
    return selected


def _overview_evidence(
    docs: Sequence[Evidence],
    python_or_backend: Sequence[Evidence],
    frontend: Sequence[Evidence],
    workflow: Sequence[Evidence],
    feature_clues: Sequence[Evidence],
    fallback: Sequence[Evidence],
) -> list[Evidence]:
    selected: list[Evidence] = []
    seen: set[str] = set()
    for group in (docs, python_or_backend, frontend, workflow, feature_clues, fallback):
        for item in group:
            if item.evidence_id in seen:
                continue
            selected.append(item)
            seen.add(item.evidence_id)
            if len(selected) >= PROJECT_OVERVIEW_EVIDENCE_LIMIT:
                return selected
    return selected


def _is_project_document(item: Evidence) -> bool:
    path = item.file_path.lower()
    symbol = (item.symbol or "").lower()
    return (
        path in {"readme.md", "agents.md", "claude.md"}
        or path.startswith("docs/")
        or (
            path.endswith(".md")
            and any(
                word in symbol for word in ("project", "overview", "design", "status")
            )
        )
    )


def _is_python_or_backend(item: Evidence) -> bool:
    path = item.file_path.lower()
    return (
        path.startswith("backend/")
        or path.endswith(".py")
        or path.endswith("pyproject.toml")
    )


def _is_frontend(item: Evidence) -> bool:
    path = item.file_path.lower()
    return (
        path.startswith("frontend/")
        or path.startswith("apps/web/")
        or path.endswith((".tsx", ".jsx"))
    )


def _is_workflow_document(item: Evidence) -> bool:
    path = item.file_path.lower()
    symbol = (item.symbol or "").lower()
    return path.startswith("docs/") or any(
        word in path or word in symbol
        for word in ("run", "setup", "command", "lint", "test")
    )


def _is_feature_symbol(symbol: str) -> bool:
    lowered = symbol.lower()
    if "_" in symbol and lowered == symbol:
        return False
    return any(
        word in lowered
        for word in (
            "ai",
            "chat",
            "document",
            "flow",
            "nda",
            "preview",
            "template",
            "technical",
        )
    )


def _format_paths(items: Iterable[Evidence]) -> str:
    return _join_code(item.file_path for item in items)


def _format_symbols(items: Iterable[Evidence]) -> str:
    symbols: list[str] = []
    seen: set[str] = set()
    for item in items:
        if (
            item.symbol is None
            or item.symbol in seen
            or not _is_display_symbol(item.symbol)
        ):
            continue
        symbols.append(item.symbol)
        seen.add(item.symbol)
    return _join_code(symbols)


def _is_display_symbol(symbol: str) -> bool:
    lowered = symbol.lower()
    if lowered in {"project"}:
        return False
    if "_" in symbol and lowered == symbol:
        return False
    return not ("." in symbol and lowered == symbol)


def _join_code(values: Iterable[str]) -> str:
    rendered = [f"`{_code(value)}`" for value in values]
    if not rendered:
        return ""
    if len(rendered) == 1:
        return rendered[0]
    return f"{', '.join(rendered[:-1])}, and {rendered[-1]}"


def _marks(items: Sequence[Evidence], citations: dict[str, int]) -> str:
    marks = [
        f"[{citations[item.evidence_id]}]"
        for item in items
        if item.evidence_id in citations
    ]
    return "".join(marks)


def _warning_line(code: str) -> str:
    message = _WARNING_MESSAGES.get(code)
    if message is None:
        return f"- `{_code(code)}`"
    return f"- {_prose(message)}"


def _code(value: str) -> str:
    """Escape a repository value for the inside of a code span.

    A backtick is the dangerous character: one closes the span and lets the
    rest render as markup. Control characters are stripped so repository text
    cannot move a terminal cursor or hide what follows it.
    """
    text = _CONTROL.sub("", value).replace("\r", " ").replace("\n", " ")
    return text.replace("`", "'")


def _prose(value: str) -> str:
    """Escape a value that appears outside a code span.

    Summaries and claim text are produced by CodeAtlas, not by the repository —
    but they *contain* repository names, so the Markdown-significant characters
    are neutralized rather than trusted.
    """
    text = _CONTROL.sub("", value).replace("\r", " ").replace("\n", " ")
    for character in ("\\", "`", "*", "_", "[", "]", "<", ">"):
        text = text.replace(character, f"\\{character}")
    return text


def _model_prose(value: str) -> str:
    """Neutralize a model-written summary without destroying its formatting.

    `_prose` escapes every Markdown character and folds newlines into spaces,
    which is right for a template: those summaries *interpolate* repository
    values, and a file genuinely named `**evil**.py` must not render as bold.

    A generated summary is different in kind. The whole string is prose the
    model composed, and its paragraphs, lists, and emphasis are the readable
    structure the feature exists to produce. Escaping them turns the answer
    into one run-on line of literal backslashes — worse to read than the plain
    text it replaced.

    What is still removed: control characters, which have no place in prose and
    can corrupt a terminal. What is *not* removed is Markdown structure, and
    the safety of that rests on two things that are true rather than hoped for.
    The browser renders this through a strict allowlist sanitizer that never
    parses raw HTML and permits no executable link protocol, so `<script>`
    arrives as literal text. And the evidence the model saw was redacted before
    it was sent, so the prose is derived from content that had its secrets
    removed.

    A model can still be induced to emit misleading *prose* by a hostile
    repository. That is a limitation of generation itself, which is why the
    claims and citations below the summary are never model-written and remain
    the authoritative part of the answer.
    """
    return _CONTROL.sub("", value).replace("\r\n", "\n").replace("\r", "\n")


def _bounded(text: str) -> str:
    """Truncate at the storage bound, saying so rather than silently cutting."""
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_ANSWER_BYTES:
        return text
    notice = "\n\n_This answer was truncated at the message size limit._\n"
    room = MAX_ANSWER_BYTES - len(notice.encode("utf-8"))
    clipped = encoded[:room].decode("utf-8", errors="ignore")
    return clipped + notice


__all__ = [
    "MAX_ANSWER_BYTES",
    "PROJECT_OVERVIEW_EVIDENCE_LIMIT",
    "render_answer",
]
