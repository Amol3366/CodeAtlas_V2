"""The validated FTS5 query builder.

FTS5 has its own query language: ``*`` is a prefix operator, ``NEAR`` and ``OR``
are operators, ``"`` delimits a phrase, and ``:`` selects a column. A user's
search text is none of those things — it is data. Passing it through unchanged
would let a stray quote raise a syntax error, let a stray ``*`` match the entire
index, and let a column filter reach a column the caller never intended to
expose.

So nothing is passed through. The raw text is reduced to literal terms, each
quoted, and joined with ``AND``. Anything that cannot survive that reduction is
a typed error rather than a query, because a search that quietly matches
everything is worse than one that refuses.
"""

from __future__ import annotations

import unicodedata

from codeatlas.domain.errors import SearchQueryError

MAX_SEARCH_QUERY_LENGTH = 256
MAX_SEARCH_TERMS = 16

# Characters allowed to stay inside a term. Identifiers and paths need them;
# everything else is a separator, including every FTS5 operator character.
_TERM_CHARACTERS = frozenset("_.-")


def build_match_expression(raw_query: str) -> str:
    """Turn untrusted user text into a safe FTS5 MATCH expression.

    Raises ``SearchQueryError`` when the input is empty, too long, or contains
    nothing that can be matched.
    """
    if len(raw_query) > MAX_SEARCH_QUERY_LENGTH:
        raise SearchQueryError("The search query is too long.")

    terms = _terms(raw_query)
    if not terms:
        raise SearchQueryError("The search query contains nothing to match.")

    return " AND ".join(f'"{_escape(term)}"' for term in terms[:MAX_SEARCH_TERMS])


def _terms(raw_query: str) -> list[str]:
    """Split normalized text into literal, matchable terms."""
    normalized = unicodedata.normalize("NFC", raw_query).casefold()
    collected: list[str] = []
    current: list[str] = []

    for character in normalized:
        if character.isalnum() or character in _TERM_CHARACTERS:
            current.append(character)
            continue
        _flush(current, collected)
        current = []
    _flush(current, collected)
    return collected


def _flush(current: list[str], collected: list[str]) -> None:
    """Keep a term only when it carries something matchable.

    A run of punctuation such as ``--`` is separator noise, not a search term,
    and would otherwise become a literal nobody is looking for.
    """
    if not current:
        return
    term = "".join(current).strip("".join(_TERM_CHARACTERS))
    if term and any(character.isalnum() for character in term):
        collected.append(term)


def _escape(term: str) -> str:
    """Double any quote so a term can never terminate its own literal.

    The tokenizer above already treats ``"`` as a separator, so this cannot
    trigger today. It stays because the guarantee belongs next to the quoting,
    not in the tokenizer's current behavior.
    """
    return term.replace('"', '""')
