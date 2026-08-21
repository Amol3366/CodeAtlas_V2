"""`AGENTS.md` §5's language profile is derived from the running registry.

**Three contract sections drifted against an ADR sitting in this repository,
and all three were found by accident while editing a fourth.** ADR-0065
registered Java, Go, Rust and Scala on 2026-08-19; §5 still said "Python,
TypeScript, and JavaScript" two days later, §6.1 did not mention the
query-backed engine at all, and §19.2 required fixtures for two languages that
were no longer the whole set.

That is the same shape as every other unguarded list this project has been bitten
by -- `SUPPORTED_FIXTURES` and the two `ROWS` tables are guarded and each forced
a decision; the PyInstaller data list was not, and shipped an artifact that could
not run at all; `README.md` was not, and drifted twice in two days.

**Only §5 is guardable, and that is worth saying plainly.** §6.1 and §19.2 are
prose about mechanism rather than lists of names, so no assertion can derive
them; a guard whose scope is unstated gets mistaken for a guarantee. This module
covers the language list and nothing else.

The assertions run in both directions on purpose:

* every language §5 calls supported resolves through the registry;
* every language §5 calls out does **not**;
* every source language the registry knows appears in §5 -- **this is the one
  that catches an ADR-0065-shaped change**, where code gains a language and the
  contract does not hear about it;
* the stated count matches.

A one-directional check would have passed happily on 2026-08-19, because
everything §5 named was still true. What was wrong was what it *omitted*.
"""

from __future__ import annotations

import re
from pathlib import Path

from codeatlas.parsing.registry import default_registry

AGENTS = Path("AGENTS.md")

# Display name in the contract -> the identifier `classify()` produces and the
# registry is keyed by. Not derivable: this is a prose-to-code mapping, and
# "C#" is never going to be spelled `csharp` in a sentence.
IDENTIFIER_BY_DISPLAY_NAME: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "TypeScript": ("typescript",),
    "JavaScript": ("javascript",),
    "Java": ("java",),
    "Go": ("go",),
    "Rust": ("rust",),
    "Scala": ("scala",),
    "C#": ("csharp",),
    "Kotlin": ("kotlin",),
    "Ruby": ("ruby",),
    "PHP": ("php",),
    "Swift": ("swift",),
    "C/C++": ("c", "cpp"),
}

# Registry entries that are not *source* languages. §5 covers these in its own
# separate clause ("Markdown and common configuration/schema formats"), so they
# are deliberately outside the seven-language count.
DOCUMENT_AND_CONFIG_FORMATS = frozenset({"json", "markdown", "toml", "yaml"})

NUMBER_WORDS = {
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
}


def _agents() -> str:
    return AGENTS.read_text(encoding="utf-8")


def _named(pattern: str) -> list[str]:
    """Pull the display names out of one §5 bullet."""
    match = re.search(pattern, _agents())
    assert match, (
        f"§5 no longer states its language tiers in the expected form: {pattern}"
    )
    # "Python, TypeScript and JavaScript" -> the three names.
    names = re.split(r",| and ", match.group(1))
    return [name.strip() for name in names if name.strip()]


def _supported_display_names() -> list[str]:
    return _named(r"- \*\*([^*]+)\*\* — the full engine") + _named(
        r"- \*\*([^*]+)\*\* — query-backed"
    )


def _source_languages() -> set[str]:
    return set(default_registry().languages) - DOCUMENT_AND_CONFIG_FORMATS


def test_every_language_the_contract_supports_resolves_to_a_parser() -> None:
    """§5's supported list is true of the code."""
    registry = default_registry()
    for display in _supported_display_names():
        identifiers = IDENTIFIER_BY_DISPLAY_NAME[display]
        for identifier in identifiers:
            assert registry.parser_for(identifier) is not None, (
                f"§5 lists {display!r} as supported, but the registry has no "
                f"parser for {identifier!r}."
            )


def test_every_language_the_contract_excludes_has_no_parser() -> None:
    """§5's exclusion list is true of the code.

    This is the half that catches a language being quietly shipped: §25 requires
    an approved ADR for new language support, so a parser existing for something
    §5 says is out means the contract was bypassed, not merely un-updated.
    """
    registry = default_registry()
    excluded = _named(r"- ([^—]+?) remain \*\*out\*\*")
    assert excluded, "§5 no longer states an exclusion list"

    for display in excluded:
        for identifier in IDENTIFIER_BY_DISPLAY_NAME[display]:
            assert registry.parser_for(identifier) is None, (
                f"§5 says {display!r} is out of scope, but a parser is "
                f"registered for {identifier!r}. That needs a §25 approval and "
                "an ADR, or the parser should not be registered."
            )


def test_no_source_language_is_missing_from_the_contract() -> None:
    """The registry gained four languages once and §5 did not hear about it.

    This assertion is the reason this module exists. The two above would both
    have passed on 2026-08-19 while §5 was two days stale, because everything it
    *named* was still correct -- the defect was the omission.
    """
    named = {
        identifier
        for display in _supported_display_names()
        for identifier in IDENTIFIER_BY_DISPLAY_NAME[display]
    }
    missing = _source_languages() - named
    assert not missing, (
        f"the registry parses {sorted(missing)}, which §5 does not list. "
        "Either the contract needs updating (with the §25 approval that "
        "authorised the language), or a new document/config format needs adding "
        "to DOCUMENT_AND_CONFIG_FORMATS in this file."
    )


def test_the_contract_language_count_matches_the_registry() -> None:
    """"seven languages" is counted, not transcribed."""
    stated = re.search(r"source in \*\*(\w+) languages, in two tiers\*\*", _agents())
    assert stated, "§5 no longer states a language count in the expected form"

    word = stated.group(1).lower()
    assert word in NUMBER_WORDS, f"§5 states an unrecognised count word {word!r}"
    assert NUMBER_WORDS[word] == len(_source_languages()), (
        f"§5 says {word} source languages; the registry has "
        f"{len(_source_languages())}: {sorted(_source_languages())}."
    )
