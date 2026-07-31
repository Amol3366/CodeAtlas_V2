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


# Function words carry no retrieval signal but are matchable tokens, so ANDing
# them is what makes a typed sentence match nothing. Deliberately short: this is
# not a linguistic stopword list, it is the set of words whose presence in a
# question says nothing about which chunk answers it. A word that might name
# something in a repository — "set", "type", "object" — is not here.
_FUNCTION_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "then", "than",
    "that", "this", "these", "those", "there", "here",
    "is", "are", "was", "were", "be", "been", "being", "am",
    "do", "does", "did", "doing", "done",
    "have", "has", "had", "having",
    "will", "would", "shall", "should", "can", "could", "may", "might", "must",
    "i", "we", "you", "he", "she", "it", "they", "them", "us", "me",
    "my", "our", "your", "its", "their", "his", "her",
    "of", "in", "on", "at", "to", "from", "by", "for",
    "with", "without", "about", "into", "over", "under",
    "as", "so", "such", "no", "not", "nor", "only", "own", "same",
    "too", "very", "just",
    "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
    "ever", "never", "always", "sometimes", "still", "yet",
})

# Below this length a token is almost always noise once function words are
# gone. Kept low so identifiers like `id` survive when they are the only term.
_MIN_RELAXED_TERM_LENGTH = 3


def build_relaxed_match_expression(raw_query: str) -> str | None:
    """A broader reading of the same text, for when the strict one matched nothing.

    Function words are dropped and the remainder is joined with ``OR``, so a
    typed sentence can match the chunk that answers it rather than requiring
    one chunk to contain every word of the question.

    Returns ``None`` when nothing substantive survives. That is the important
    case: a question made only of function words has no broader reading, and
    answering it with an OR over the leftovers would hand back a tour of the
    repository. Refusing beats matching everything — the same rule the strict
    builder follows.
    """
    if len(raw_query) > MAX_SEARCH_QUERY_LENGTH:
        raise SearchQueryError("The search query is too long.")

    terms = [
        term
        for term in _terms(raw_query)
        if term not in _FUNCTION_WORDS and len(term) >= _MIN_RELAXED_TERM_LENGTH
    ]
    if not terms:
        return None
    return " OR ".join(f'"{_escape(term)}"' for term in terms[:MAX_SEARCH_TERMS])


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
