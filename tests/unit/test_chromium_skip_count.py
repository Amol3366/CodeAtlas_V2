"""The Chromium Playwright skip count is counted from the specs, not transcribed.

**This figure has understated itself three times**, and each phrasing was
accurate about the mechanism it knew while silently excluding the one it did
not:

* until 2026-08-07 it read "four conversation-route tests on
  `/conversations/{id}`" -- **route-specific**, and blind the moment the
  renderer died on another route;
* until 2026-09-03 it read "seven tests across five spec files" -- counted from
  the ``skipChromium*`` **helper call sites**, and blind to `settings.spec.ts`
  skipping Chromium a second time through an inline ``test.skip``;
* the true figure is **eight across five**, corroborated by full runs reporting
  8 skipped and by ``--repeat-each=10`` reporting 80.

The third correction is why this module exists and why it parses **both**
mechanisms. A guard that counted only helper calls would have reproduced the
2026-09-03 defect exactly, and passed while doing it.

**The helper names are read out of `chromium-crash.ts`, not listed here.** This
project's recurring defect is *a list that must be extended when something is
added, with nothing enforcing it* -- `SUPPORTED_FIXTURES`, the findings and
impact ``ROWS`` tables, the PyInstaller data list that shipped an artifact which
could not run at all. A third helper added tomorrow is counted by this guard
without anyone editing it, the way `build_package.ps1`'s adapter data is found
by glob. The spec files are globbed for the same reason.

**What this does NOT cover, stated rather than left to be assumed.** A guard
whose scope is unstated gets mistaken for a guarantee:

* It counts *declared* skips, not skips a run actually reported. The two agree
  today and are checked against each other by hand in the register row; nothing
  here executes Playwright, because a unit test that needs a browser is not a
  unit test.
* It recognises a skip whose condition is written ``browserName === "chromium"``
  or which calls a helper from `chromium-crash.ts`. A skip expressed some other
  way -- ``browserName !== "firefox"``, a fixture, a project-level filter --
  is invisible to it, and would understate the count in a **fourth** new way.
  That is the residual risk and it is not hypothetical, since the previous two
  misses were both of this shape.
* It says nothing about prose. A guard that fails on ordinary rewording is one
  people learn to delete.

**When one of these fails, the documents are usually what is wrong.** The specs
are the authority: they are the thing Playwright actually runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

E2E_DIRECTORY = Path("apps/web/e2e")
CRASH_HELPERS = E2E_DIRECTORY / "support" / "chromium-crash.ts"

# Documents that state the figure, and the section of each that is allowed to.
#
# `PLAN.md` is bounded to the Deferred Register deliberately. Its handoff log is
# append-only evidence and still contains "Firefox runs all seven suites" from
# 2026-08, which is a correct record of what was true when it was written and
# must never be edited to match a later count. An unbounded search would read
# that history as a live claim and fail forever, which is how a guard gets
# deleted.
DOCUMENTS: list[tuple[str, Path, tuple[str, str] | None]] = [
    ("README.md", Path("README.md"), None),
    (
        "the Deferred Register",
        Path("docs/plans/PLAN.md"),
        ("## Deferred Register", "### Phase 7 Task Board"),
    ),
    (
        "the working guide",
        Path("documentation/codeatlas-v2-working-guide.md"),
        None,
    ),
]

NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

# Matched against text with emphasis stripped and whitespace collapsed, which is
# what lets one pattern serve three documents that word it three ways:
#
#   README  "**Eight Playwright tests are skipped on Chromium** across five ..."
#   guide   "**Eight** Playwright tests are skipped on Chromium across **five**"
#   PLAN    "**Eight** Playwright tests skipped on Chromium, across **five**"
#
# Normalising first also removes the reason the README guard had to learn to
# write `\s+` rather than a literal space: a claim the prose wraps across a line
# reads identically here.
COUNT_PATTERN = re.compile(
    r"(\w+) Playwright tests (?:are )?skipped on Chromium,? across (\w+) spec files"
)
# Every *other* place a document says the same number. Each is checked against
# the specs, because a half-update leaves a document contradicting itself and
# whichever sentence a reader meets first decides what they believe.
#
# **This list is itself the residual risk, and writing this guard proved it.**
# The first version checked the two phrasings below the count -- and the README
# turned out to say the number a THIRD time, in its Tests row ("not the seven
# Chromium Playwright skips"), which neither the guard nor the hand sweep that
# preceded it looked for. That is a fourth instance of the same drift class the
# whole module exists for, found only because writing the guard meant reading
# the row.
#
# A list-free version was tried and rejected: scanning any sentence mentioning
# Chromium and a number matches this project's own prose about the defect
# ("understated itself three times", a quoted "its seven neighbours"), so it
# would fail on correct text. A guard that fails on ordinary rewording is one
# people learn to delete, so the explicit list is kept and its cost stated here.
RESTATEMENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Firefox runs all N", re.compile(r"Firefox runs all (\w+)")),
    ("N Chromium Playwright skips", re.compile(r"(\w+) Chromium Playwright skips")),
]

HELPER_CALL_TEMPLATE = r"\b(?:{names})\s*\("
INLINE_SKIP_PATTERN = re.compile(
    r"test\.skip\(\s*browserName\s*===\s*[\"']chromium[\"']"
)


def _number(token: str) -> int | None:
    """Read a count written as a word or as digits, or `None` if it is neither."""
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token.lower())


def _require_number(token: str, label: str) -> int:
    """`_number`, but a token that cannot be read is a loud failure.

    Returning `None` into a comparison would make an unreadable count compare
    unequal and report as a *drift*, sending the reader to correct a document
    that is right. The distinction matters enough to spend an assertion on:
    "the count moved" and "this guard cannot read the count" are different
    facts and need different messages.
    """
    value = _number(token)
    assert value is not None, (
        f"{label} writes the count as {token!r}, which this guard cannot read. "
        "Write it as digits or as a word, or extend NUMBER_WORDS."
    )
    return value


def _normalised(path: Path, section: tuple[str, str] | None) -> str:
    text = path.read_text(encoding="utf-8")
    if section is not None:
        start, end = section
        begin = text.index(start)
        text = text[begin : text.index(end, begin)]
    return re.sub(r"\s+", " ", text.replace("*", ""))


def _spec_files() -> list[Path]:
    return sorted(E2E_DIRECTORY.glob("*.spec.ts"))


def _helper_names() -> set[str]:
    """Exported functions in `chromium-crash.ts` that actually skip.

    Derived rather than listed, and filtered on the body calling `test.skip`
    so that a future non-skipping export from the same module cannot inflate
    the count by sharing its address.
    """
    source = CRASH_HELPERS.read_text(encoding="utf-8")
    names: set[str] = set()
    for match in re.finditer(r"export\s+function\s+(\w+)\s*\(", source):
        following = source.find("export function", match.end())
        body = source[match.end() : following if following != -1 else len(source)]
        if "test.skip(" in body:
            names.add(match.group(1))
    return names


def _skips_by_spec() -> dict[str, tuple[int, int]]:
    """Chromium skips per spec file, as `(helper calls, inline test.skip)`.

    An import names a helper without calling it, so the call pattern requires
    the opening parenthesis. The helper *definitions* live under `support/` and
    are excluded by globbing `*.spec.ts` rather than by a name check.
    """
    names = _helper_names()
    helper_call = re.compile(
        HELPER_CALL_TEMPLATE.format(names="|".join(sorted(map(re.escape, names))))
    )

    counted: dict[str, tuple[int, int]] = {}
    for spec in _spec_files():
        source = spec.read_text(encoding="utf-8")
        helpers = len(helper_call.findall(source)) if names else 0
        inline = len(INLINE_SKIP_PATTERN.findall(source))
        if helpers or inline:
            counted[spec.name] = (helpers, inline)
    return counted


def _totals() -> tuple[int, int]:
    counted = _skips_by_spec()
    return sum(h + i for h, i in counted.values()), len(counted)


def test_the_guard_finds_specs_and_helpers_to_count() -> None:
    """The inputs exist, so the assertions below cannot pass vacuously.

    Every count here is a length, and a length is `0` when a path is wrong or a
    directory moves. Without this the whole module would go quietly green on a
    renamed `e2e/` directory -- the failure mode the Deferred Register guard's
    own "more than 30 rows" assertion exists to stop.
    """
    specs = _spec_files()
    assert len(specs) >= 3, (
        f"expected several Playwright specs under {E2E_DIRECTORY}, found "
        f"{[p.name for p in specs]}; the suite moved, or this path is stale"
    )

    assert CRASH_HELPERS.exists(), f"{CRASH_HELPERS} is missing; this guard reads it"

    names = _helper_names()
    assert names, (
        f"no skipping helper found in {CRASH_HELPERS}. If the helpers were "
        "renamed or inlined, this guard now counts one mechanism instead of "
        "two -- which is the exact defect it was written for."
    )


def test_both_skip_mechanisms_are_still_present() -> None:
    """A deliberate tripwire: the count is only right if both are parsed.

    The 2026-09-03 miscount happened because the figure was derived from helper
    call sites while `settings.spec.ts` also skipped inline. This asserts the
    two mechanisms it parses are both real, so the coverage cannot silently
    become single-mechanism again.

    **If every inline skip is legitimately converted to a helper, this test
    should fail and then be deleted with that reasoning recorded** -- the way
    ADR-0033's granularity tripwire was written to fail once the corpus grew.
    It is not a correctness assertion; it is a statement about what the parser
    above still needs to handle. Do not satisfy it by adding a token skip.
    """
    counted = _skips_by_spec()
    helpers = sum(h for h, _ in counted.values())
    inline = sum(i for _, i in counted.values())

    assert helpers and inline, (
        f"expected both skip mechanisms; found {helpers} helper call(s) and "
        f"{inline} inline test.skip(). Per-spec: {counted}"
    )


@pytest.mark.parametrize(
    ("label", "path", "section"), DOCUMENTS, ids=lambda v: str(v)[:32]
)
def test_a_document_states_the_chromium_skip_count_the_specs_declare(
    label: str, path: Path, section: tuple[str, str] | None
) -> None:
    """The stated count, and the number of spec files, match the specs.

    Both halves matter. The count drifted three times; the spec-file count
    drifted with it twice, because whoever corrected one recomputed the other
    from the same wrong reading.
    """
    skips, spec_files = _totals()
    found = COUNT_PATTERN.findall(_normalised(path, section))

    assert found, (
        f"{label} no longer states the Chromium skip count in the expected "
        "form; restore the claim or update this guard"
    )

    stated = {
        (_require_number(count, label), _require_number(files, label))
        for count, files in found
    }
    assert stated == {(skips, spec_files)}, (
        f"{label} says {sorted(stated)} (tests, spec files); the specs declare "
        f"({skips}, {spec_files}). Per-spec (helper, inline): {_skips_by_spec()}. "
        "The specs are the authority; update the document."
    )


def test_every_restatement_of_the_count_agrees_with_the_specs() -> None:
    """Every *other* sentence stating the number agrees with the count.

    This is the half-update check, and it is not hypothetical. On 2026-09-03
    all three documents said "seven" in two places each, so correcting only the
    headline count would have left each document contradicting itself. The
    README said it in a **third** place that the first pass missed entirely.

    Deliberately not parametrised over documents: a phrasing legitimately
    appears in some documents and not others, so requiring every phrasing in
    every document would fail on correct text. What is required is that
    whatever restatements *do* exist agree -- and that, across all documents,
    at least one is found, so a renamed phrase cannot silently disable this.
    """
    skips, _ = _totals()
    seen: dict[str, set[int]] = {}

    for label, path, section in DOCUMENTS:
        text = _normalised(path, section)
        for phrasing, pattern in RESTATEMENT_PATTERNS:
            found = pattern.findall(text)
            if not found:
                continue
            where = f"{label} ({phrasing})"
            seen[where] = {_require_number(token, where) for token in found}

    assert seen, (
        "no document restates the Chromium skip count in any known phrasing. "
        f"Either the claims were removed, or they were reworded and "
        f"RESTATEMENT_PATTERNS needs the new form: {RESTATEMENT_PATTERNS}"
    )

    disagreeing = {where: sorted(v) for where, v in seen.items() if v != {skips}}
    assert not disagreeing, (
        f"the specs declare {skips} Chromium skips; these restatements "
        f"disagree: {disagreeing}. The specs are the authority."
    )
