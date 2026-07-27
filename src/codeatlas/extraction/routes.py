"""Route literals and document mentions: normalizing, tokenizing, matching.

A route literal is the one string a frontend, a backend, and a document can all
write down independently, so it is the only evidence available that they are
talking about the same thing. It is still just a string. Nothing here resolves a
framework's routing table, and an edge derived from this module is a heuristic
even when it is obviously right.

Normalization has to reconcile three spellings of the same path — ``/orders/{id}``
in a document, ``/orders/${id}`` in TypeScript, ``/orders/:id`` in a router — and
must not go further. Lowercasing or stripping segments would make ``/order`` and
``/orders`` collide, and a collision here becomes a confident, wrong edge.

The hint constants are re-exported from :mod:`codeatlas.domain.relations`, where
they belong: they are part of the reference vocabulary, and the domain may not
depend on extraction. Everything else here is mechanism, not vocabulary.
"""

from __future__ import annotations

import re
from typing import Final

from codeatlas.domain.relations import DERIVED_HINT, MENTION_HINT, ROUTE_HINT

__all__ = [
    "DERIVED_HINT",
    "MAX_MENTIONS_PER_SECTION",
    "MAX_ROUTE_LENGTH",
    "MENTION_HINT",
    "MIN_MENTION_LENGTH",
    "ROUTE_HINT",
    "mention_words",
    "name_tokens",
    "normalize_route",
    "route_tokens",
    "routes_in_text",
    "tokens_match",
]

MAX_ROUTE_LENGTH: Final[int] = 200
MAX_MENTIONS_PER_SECTION: Final[int] = 60
MIN_MENTION_LENGTH: Final[int] = 3

# `${...}`, `{...}`, and `:name` all mean "a value goes here".
_TEMPLATE_PARAMETER: Final[re.Pattern[str]] = re.compile(r"\$\{[^}]*\}|\{[^}]*\}")
_COLON_PARAMETER: Final[re.Pattern[str]] = re.compile(r"(?<=/):[A-Za-z_][\w-]*")
_CAMEL_BOUNDARY: Final[re.Pattern[str]] = re.compile(
    r".+?(?:(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|$)"
)
_WORD: Final[re.Pattern[str]] = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
# A path written in prose or code: a leading slash and no whitespace.
_ROUTE_IN_TEXT: Final[re.Pattern[str]] = re.compile(r"/[A-Za-z0-9_\-./{}$:]*")

# Words too common to carry evidence. Deliberately small: this list exists to
# stop grammar words from linking a document to code, not to model English.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "and",
        "are",
        "but",
        "can",
        "for",
        "from",
        "has",
        "have",
        "how",
        "its",
        "not",
        "our",
        "the",
        "that",
        "then",
        "this",
        "use",
        "used",
        "uses",
        "was",
        "were",
        "what",
        "when",
        "which",
        "will",
        "with",
        "you",
        "your",
    }
)


def normalize_route(value: str) -> str | None:
    """Reduce a path string to a comparable key, or ``None`` if it is not a path.

    Returning ``None`` is the common case and the important one: most strings in
    a repository are not routes, and treating one as a route is how a linker
    starts inventing edges.
    """
    text = value.strip()
    if not text.startswith("/") or len(text) > MAX_ROUTE_LENGTH:
        return None
    if any(character.isspace() for character in text):
        return None

    # A query string or fragment addresses a representation, not a handler.
    for separator in ("?", "#"):
        text = text.split(separator, 1)[0]

    text = _TEMPLATE_PARAMETER.sub("{}", text)
    text = _COLON_PARAMETER.sub("{}", text)

    if len(text) > 1:
        text = text.rstrip("/")
    return text or "/"


def route_tokens(route: str) -> tuple[str, ...]:
    """The words a route names, with placeholders dropped.

    ``/orders/{}/items`` is about orders and items. The placeholder is where a
    value goes and names nothing.
    """
    found: list[str] = []
    for segment in route.split("/"):
        if not segment or segment == "{}":
            continue
        for word in _WORD.findall(segment):
            lowered = word.lower()
            if lowered not in found:
                found.append(lowered)
    return tuple(found)


def name_tokens(name: str) -> tuple[str, ...]:
    """Split an identifier into lowercase words across ``_``, ``-``, and case."""
    found: list[str] = []
    for part in re.split(r"[^A-Za-z0-9]+", name):
        if not part:
            continue
        for piece in _CAMEL_BOUNDARY.findall(part):
            lowered = piece.lower()
            if lowered and lowered not in found:
                found.append(lowered)
    return tuple(found)


def tokens_match(route: tuple[str, ...], name: tuple[str, ...]) -> bool:
    """Whether a route and an identifier share a word, tolerating plurals.

    ``/orders`` and ``get_order`` are about the same thing; a prefix rule would
    also match ``ordinal``, so only whole words and their simple plurals count.
    """
    return any(
        _same_word(route_word, name_word) for route_word in route for name_word in name
    )


def _same_word(left: str, right: str) -> bool:
    if left == right:
        return True
    for shorter, longer in ((left, right), (right, left)):
        if longer in (f"{shorter}s", f"{shorter}es"):
            return True
    return False


def routes_in_text(text: str) -> tuple[str, ...]:
    """Normalized routes named anywhere in a block of prose or code."""
    found: list[str] = []
    for candidate in _ROUTE_IN_TEXT.findall(text):
        route = normalize_route(candidate)
        if route is not None and route != "/" and route not in found:
            found.append(route)
    return tuple(found)


def mention_words(text: str) -> tuple[str, ...]:
    """Bounded, deduplicated candidate identifiers named in a block of text.

    Bounded because a document section is untrusted input of unbounded length,
    and one reference per word would otherwise let a file decide how much work
    resolution does.
    """
    found: list[str] = []
    for word in _WORD.findall(text):
        lowered = word.lower()
        if len(lowered) < MIN_MENTION_LENGTH or lowered in _STOPWORDS:
            continue
        if lowered not in found:
            found.append(lowered)
        if len(found) >= MAX_MENTIONS_PER_SECTION:
            break
    return tuple(found)
