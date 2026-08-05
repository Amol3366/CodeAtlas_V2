"""Deterministic intent classification.

`AGENTS.md` Section 10.1 step 3: classify intent with deterministic rules
first. In Phase 5 there is no "second"; no model participates, so these rules
are the whole classifier.

The rules are ordered, and the order is the design. Phrasing that names a
*relationship* is checked before phrasing that merely contains a symbol,
because "who calls capture" contains "capture" and would otherwise resolve as
an exact lookup of a symbol the user was asking *about*, not *for*. The final
fallback is lexical search — a real channel, not an apology.

The rule set carries a version because a stored run records which policy
answered it. Changing these rules without changing the version would make an
old run appear to have been answered by rules it never saw.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from codeatlas.domain.errors import QueryTooLongError

RETRIEVAL_POLICY_VERSION: Final[str] = "5.3"

# Bounded input (`AGENTS.md` Section 10.3). Truncating instead would answer a
# question the user did not ask.
MAX_QUERY_CHARACTERS: Final[int] = 4000


class Intent(StrEnum):
    """What kind of question this is, and therefore which channel answers it."""

    GREETING = "greeting"
    PROJECT_OVERVIEW = "project_overview"
    EXACT_SYMBOL = "exact_symbol"
    CALLERS = "callers"
    CALLEES = "callees"
    DEPENDENCIES = "dependencies"
    TESTS = "tests"
    DOCUMENTS = "documents"
    TRACE = "trace"
    CHANGE = "change"
    TEXT = "text"


@dataclass(frozen=True)
class Classification:
    """One question, resolved to a channel and the thing it is about."""

    intent: Intent
    target: str
    policy_version: str = RETRIEVAL_POLICY_VERSION


# Each rule is (compiled pattern, intent). The pattern's `subject` group, when
# present, is the symbol the question is about; without one the whole question
# is the target.
#
# Ordering rationale, since it is not obvious from the list alone:
#   - change phrasing first: it names no symbol, so nothing else would match it;
#   - callee before caller would misread "who calls X", so caller comes first
#     and is anchored to its own verb form;
#   - every relationship rule precedes the bare-symbol rule.
_RULES: Final[tuple[tuple[re.Pattern[str], Intent], ...]] = (
    (
        re.compile(
            r"^(?:what\s+changed|what\s+has\s+changed|show\s+(?:me\s+)?"
            r"(?:the\s+)?(?:likely\s+)?impact|what\s+(?:might|may|could)\s+break"
            r"|what\s+breaks)\b",
            re.IGNORECASE,
        ),
        Intent.CHANGE,
    ),
    (
        re.compile(r"^(?:who|what)\s+calls\s+(?P<subject>\S+)\s*$", re.IGNORECASE),
        Intent.CALLERS,
    ),
    (
        re.compile(r"^callers?\s+of\s+(?P<subject>\S+)\s*$", re.IGNORECASE),
        Intent.CALLERS,
    ),
    (
        re.compile(r"^what\s+does\s+(?P<subject>\S+)\s+call\s*$", re.IGNORECASE),
        Intent.CALLEES,
    ),
    (
        re.compile(r"^callees?\s+of\s+(?P<subject>\S+)\s*$", re.IGNORECASE),
        Intent.CALLEES,
    ),
    (
        re.compile(r"^what\s+does\s+(?P<subject>\S+)\s+depend\s+on\s*$", re.IGNORECASE),
        Intent.DEPENDENCIES,
    ),
    (
        re.compile(r"^dependencies\s+(?:of|for)\s+(?P<subject>\S+)\s*$", re.IGNORECASE),
        Intent.DEPENDENCIES,
    ),
    (
        re.compile(
            r"^(?:which\s+)?tests?\s+(?:for|cover|covers)\s+(?P<subject>\S+)\s*$",
            re.IGNORECASE,
        ),
        Intent.TESTS,
    ),
    (
        re.compile(r"^what\s+tests\s+(?P<subject>\S+)\s*$", re.IGNORECASE),
        Intent.TESTS,
    ),
    (
        re.compile(
            r"^(?:docs?|documentation)\s+(?:for|about)\s+(?P<subject>\S+)\s*$",
            re.IGNORECASE,
        ),
        Intent.DOCUMENTS,
    ),
    (
        re.compile(r"^what\s+documents\s+(?P<subject>\S+)\s*$", re.IGNORECASE),
        Intent.DOCUMENTS,
    ),
    (
        re.compile(
            r"^trace\s+(?:the\s+)?(?:flow\s+(?:from|through)\s+)?"
            r"(?P<subject>\S+)\s*$",
            re.IGNORECASE,
        ),
        Intent.TRACE,
    ),
)

# A bare symbol or path: one token, no whitespace, made of the characters an
# identifier or repository-relative path uses. Anything looser would swallow
# ordinary prose.
_SYMBOL_SHAPED: Final[re.Pattern[str]] = re.compile(r"^[\w./\\:$-]+$")
_GREETING: Final[re.Pattern[str]] = re.compile(
    r"^(?:hi|hello|hey|hi\s+there|hello\s+there|hey\s+there|good\s+morning|"
    r"good\s+afternoon|good\s+evening)[\s,.!?]*$",
    re.IGNORECASE,
)
_PROJECT_OVERVIEW: Final[re.Pattern[str]] = re.compile(
    r"^(?:(?:tell|show)\s+me\s+about|summarize|describe|explain|"
    r"give\s+me\s+(?:(?:an\s+)?overview\s+of|(?:a\s+)?(?:full\s+)?"
    r"explanation\s+(?:about|of))|what\s+is|what\s+does)\b.*"
    r"\b(?:project|repo|repository|codebase)\b",
    re.IGNORECASE,
)


def classify(text: str) -> Classification:
    """Route one question to the channel that can answer it.

    Raises :class:`QueryTooLongError` above the input bound and ``ValueError``
    for an empty question — neither is answerable, and guessing at either would
    invent the question.
    """
    if len(text) > MAX_QUERY_CHARACTERS:
        raise QueryTooLongError(
            f"A question is limited to {MAX_QUERY_CHARACTERS} characters.",
            details={"max_characters": str(MAX_QUERY_CHARACTERS)},
        )

    normalized = " ".join(text.split())
    if not normalized:
        raise ValueError("a question cannot be empty")

    # A trailing question mark is punctuation, not meaning.
    stripped = normalized.rstrip("?").strip() or normalized

    if _GREETING.match(stripped):
        return Classification(intent=Intent.GREETING, target=stripped)

    if _PROJECT_OVERVIEW.match(stripped):
        return Classification(intent=Intent.PROJECT_OVERVIEW, target=normalized)

    for pattern, intent in _RULES:
        match = pattern.match(stripped)
        if match is None:
            continue
        groups = match.groupdict()
        subject = groups.get("subject")
        return Classification(
            intent=intent,
            target=subject if subject else stripped,
        )

    if _SYMBOL_SHAPED.match(stripped):
        return Classification(intent=Intent.EXACT_SYMBOL, target=stripped)

    return Classification(intent=Intent.TEXT, target=normalized)


__all__ = [
    "MAX_QUERY_CHARACTERS",
    "RETRIEVAL_POLICY_VERSION",
    "Classification",
    "Intent",
    "classify",
]
