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
from typing import Final

from codeatlas.contracts import QueryResponse
from codeatlas.conversations.intent import Intent

# Matches the storage bound on message content: an answer is a summary, not a
# place to paste a repository.
MAX_ANSWER_BYTES: Final[int] = 64 * 1024

_CONTROL: Final[re.Pattern[str]] = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
)

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
    Intent.TEXT: "lexical search over the active snapshot",
}


def render_answer(response: QueryResponse, *, intent: Intent) -> str:
    """Render one verified response as the assistant's Markdown message."""
    lines: list[str] = [_prose(response.answer.summary), ""]

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

    if response.evidence:
        lines.append("**Evidence**")
        for ordinal, item in enumerate(response.evidence, start=1):
            location = f"{item.file_path}:{item.start_line}-{item.end_line}"
            symbol = f" — `{_code(item.symbol)}`" if item.symbol else ""
            lines.append(
                f"{ordinal}. `{_code(location)}`{symbol} "
                f"({item.derivation.value}, confidence {item.confidence:.2f})"
            )
        lines.append("")

    if response.warnings:
        lines.append("**Warnings**")
        lines.extend(f"- `{_code(item)}`" for item in response.warnings)
        lines.append("")

    if response.limitations:
        lines.append("**Limitations**")
        lines.extend(f"- {_prose(item)}" for item in response.limitations)
        lines.append("")

    return _bounded("\n".join(lines).rstrip() + "\n")


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


def _bounded(text: str) -> str:
    """Truncate at the storage bound, saying so rather than silently cutting."""
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_ANSWER_BYTES:
        return text
    notice = "\n\n_This answer was truncated at the message size limit._\n"
    room = MAX_ANSWER_BYTES - len(notice.encode("utf-8"))
    clipped = encoded[:room].decode("utf-8", errors="ignore")
    return clipped + notice


__all__ = ["MAX_ANSWER_BYTES", "render_answer"]
