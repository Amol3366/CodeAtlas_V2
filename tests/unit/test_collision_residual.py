"""The residual is classified, not fixed.

ADR-0074 took separation from 221 to 419 of 1202 collision groups over five
pinned repositories. **1202 - 419 = 783 remain on the ordinal**, and ~718 of
those are two declarations sharing a name, a kind *and* one enclosing scope --
so neither a signature nor a discriminator can tell them apart.

**No mechanism is proposed, on purpose.** The register says it may not be an
identity defect at all: if one qualified name renders two members a reader would
call distinct, the qualified name is what is wrong. Guessing at the mechanism
instead of measuring is what produced ADR-0072's five-fold error.

So this classifies. `report_collisions` already counts groups and knows which
separate; it cannot say what the unseparated ones *look like*, and that is the
question the register is actually holding open.
"""

from __future__ import annotations

from pathlib import Path

from scripts.report_symbol_collisions import residual_groups


def test_two_identical_declarations_report_one_residual_group(tmp_path: Path) -> None:
    """Same name, same kind, same signature: nothing separates them."""
    (tmp_path / "Probe.java").write_text(
        "class Probe {\n"
        "  void run() { int a = 1; }\n"
        "  void run() { int b = 2; }\n"
        "}\n",
        encoding="utf-8",
    )
    groups = residual_groups(tmp_path)
    assert [(g.qualified_name, g.members, g.shared_discriminator) for g in groups] == [
        ("Probe.run", 2, True)
    ]


def test_two_overloads_are_separated_and_therefore_not_residual(
    tmp_path: Path,
) -> None:
    """A signature separates these, so they must not appear in the residual.

    Without this the classifier could report every collision group and still
    look correct on the test above.
    """
    (tmp_path / "Probe.java").write_text(
        "class Probe {\n"
        "  void run(int a) {}\n"
        "  void run(String b) {}\n"
        "}\n",
        encoding="utf-8",
    )
    assert residual_groups(tmp_path) == []


def test_a_single_declaration_is_not_a_group_at_all(tmp_path: Path) -> None:
    """A collision needs two members; one declaration is not a residual of one."""
    (tmp_path / "Probe.java").write_text(
        "class Probe {\n  void run() {}\n}\n", encoding="utf-8"
    )
    assert residual_groups(tmp_path) == []


def test_the_language_is_reported_so_a_per_language_tally_is_possible(
    tmp_path: Path,
) -> None:
    """ADR-0074's numbers are per language, and only that showed Scala moving
    while Java stood still. A total alone would have hidden it."""
    (tmp_path / "Probe.java").write_text(
        "class Probe {\n  void run() {}\n  void run() {}\n}\n", encoding="utf-8"
    )
    assert {group.language for group in residual_groups(tmp_path)} == {"java"}
