"""The Deferred Register never says an item is both open and closed.

**The register is this project's single authoritative statement of what is
open**, and on 2026-08-21 an audit found **five of its rows stale in one day** --
three of them describing a world that had not existed for days:

* `changed_symbol_precision` claimed a regression guard had been lost; the guard
  had been in `test_change_adapter.py` since Phase 4.
* `-SkipWeb -Perf` claimed "nothing watching it"; `check_phase7.ps1` had refused
  the combination since `ba64b0e`, with nine tests guarding it.
* "Cold-indexing takes 343 s" survived ADR-0064 taking it to **32.64 s** -- and
  the register's *own* ADR-0064 row said so, two screens away.
* The ambiguity-message row's trigger was "someone fixes the message"; `4926e71`
  fixed it.
* **q032 appeared twice** -- once struck through as closed by ADR-0055, once
  still open, with identical wording.

Only the last is mechanically catchable, and this is that check. **The other
four are prose staleness and no assertion can derive them**, which is said here
plainly rather than left for a reader to assume this module covers more than it
does. A guard whose scope is unstated gets mistaken for a guarantee.

**The rule: one item, one disposition.** A row struck through with `~~` is
closed; a row without is open. The same item appearing both ways is the register
contradicting itself, and whichever copy a reader finds first decides what they
believe.

`~~original entry~~` rows are exempt and that exemption is deliberate, not a
convenience. The register's convention is to keep a superseded row's text
beneath its correction under that placeholder heading, so the same words
legitimately appear many times. All such rows are closed; the check still
applies to them as a group through the both-open branch.
"""

from __future__ import annotations

import re
from pathlib import Path

PLAN = Path("docs/plans/PLAN.md")
SECTION_START = "## Deferred Register"
SECTION_END = "### Phase 7 Task Board"

# Rows whose subject cell is a placeholder for "the text this row replaced".
# Not a duplicate: the register deliberately preserves superseded wording.
PLACEHOLDERS = {"original entry"}


def _register_cells() -> list[list[str]]:
    """Every register row as its (item, disposition, trigger) cells."""
    text = PLAN.read_text(encoding="utf-8")
    start = text.index(SECTION_START)
    end = text.index(SECTION_END)
    rows: list[list[str]] = []
    for line in text[start:end].split("\n"):
        if not line.startswith("| ") or line.count("|") < 3:
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) < 3 or cells[0].startswith("---") or cells[0] == "Item":
            continue
        rows.append(cells)
    return rows


def _register_rows() -> list[str]:
    return [cells[0] for cells in _register_cells()]


def _identity(item: str) -> str:
    """The row's subject with markup and closure marks removed."""
    stripped = re.sub(r"~~|\*\*|\*|`", "", item)
    return re.sub(r"\s+", " ", stripped).strip().lower()


def _is_closed(item: str) -> bool:
    return item.strip().startswith("~~")


def test_the_register_has_rows_to_check() -> None:
    """Guard the guard.

    Every assertion below passes vacuously against an empty list, and this
    module locates its section by two literal headings. A reformat that moved
    or renamed either would silently disable the real check.
    """
    rows = _register_rows()
    assert len(rows) > 30, (
        f"only {len(rows)} register rows parsed; the section markers "
        f"{SECTION_START!r}/{SECTION_END!r} have probably moved"
    )


def test_no_item_is_both_open_and_closed() -> None:
    """One item, one disposition.

    q032 was listed twice with identical wording -- struck through as closed by
    ADR-0055, and still open below it. Whichever a reader reached first decided
    whether they thought it was settled.
    """
    dispositions: dict[str, list[bool]] = {}
    for item in _register_rows():
        key = _identity(item)
        if key in PLACEHOLDERS:
            continue
        dispositions.setdefault(key, []).append(_is_closed(item))

    contradictory = {
        key: flags
        for key, flags in dispositions.items()
        if len(flags) > 1 and len(set(flags)) > 1
    }
    assert not contradictory, (
        "these items appear in the Deferred Register both open and closed: "
        + "; ".join(sorted(contradictory))
        + ". Delete the stale copy -- the register is the authority on what is "
        "open, and it cannot say both."
    )


def test_no_item_is_listed_open_twice() -> None:
    """Two open rows for one item split its evidence across both.

    Not observed yet. Included because the duplicate that *was* observed came
    from a row surviving its own closure, and the same edit that produces one
    shape produces the other.
    """
    open_counts: dict[str, int] = {}
    for item in _register_rows():
        key = _identity(item)
        if key in PLACEHOLDERS or _is_closed(item):
            continue
        open_counts[key] = open_counts.get(key, 0) + 1

    repeated = {key: n for key, n in open_counts.items() if n > 1}
    assert not repeated, (
        "these items are listed open more than once: "
        + "; ".join(f"{key} ({n}x)" for key, n in sorted(repeated.items()))
    )


def test_no_row_is_open_in_one_column_and_closed_in_another() -> None:
    """A disposition and its trigger cannot disagree about whether it is done.

    The two guards above read only the Item cell and infer closure from a
    strikethrough, so they were blind to the shape that actually occurred: a
    row whose Disposition still reads OPEN while its Trigger cell already
    records **CLOSED**, with the date and the ADR that closed it.

    Fifteen rows were in that state at the 2026-09-03 closeout -- closed by
    DR-01b, DR-02, DR-06, RW-04, ADR-0073, ADR-0075, ADR-0076 and ADR-0077,
    and never re-dispositioned. A reader going top-down sees OPEN and stops;
    the register's own preamble warns that "a row whose disposition and
    neighbour disagree should be read as unaudited", which is an instruction
    to a human that nothing enforced.

    Closing a row means editing the Disposition cell, not only appending the
    evidence to the Trigger cell.
    """
    contradictory = []
    for cells in _register_cells():
        disposition, trigger = cells[1], cells[2]
        if not disposition.lstrip("*").upper().startswith("OPEN"):
            continue
        if re.search(r"\bCLOSED\b", trigger):
            contradictory.append(_identity(cells[0])[:70])

    assert not contradictory, (
        f"{len(contradictory)} register row(s) say OPEN in the Disposition "
        "column while the Trigger column records a closure: "
        + "; ".join(sorted(contradictory))
        + ". Promote the closure into the Disposition cell -- a reader going "
        "top-down never reaches the third column."
    )
