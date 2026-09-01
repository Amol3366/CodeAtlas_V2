"""Reproducible collision census -- ADR-0071's numbers, as a committed tool.

ADR-0071 measured 1202 collision groups over five real repositories, 221
separated by a signature and 981 left on the ordinal, with an ad-hoc probe that
was never committed. DR-03 through DR-05 each have to prove that a mechanism's
class of collision falls to zero, and a claim that cannot be re-run is not
evidence, so the instrument lives here.

**A collision is two symbols in one file sharing a qualified name and a kind.**
Those are the only two of ``symbol_id``'s four inputs that vary within a file.
Grouping on the emitted ``symbol_id`` would report zero forever, because
``ensure_unique_symbol_ids`` has already rewritten the later members by the time
``parse`` returns -- the tool would then agree with every fix, including a
broken one.

A group is *separated* when its members carry distinct **(signature,
discriminator)** pairs -- both are position-independent -- and left on the
*ordinal* when they do not. The discriminator half was added by ADR-0074; before
it, this tool measured signature separation alone and could not have seen that
mechanism work. Per-language tallies matter as much as the
total: only they can show Scala falling to zero while Java stands still.
"""

from __future__ import annotations

import argparse
import dataclasses
from collections import defaultdict
from pathlib import Path

from codeatlas.parsing.registry import ParseRequest, default_registry

_LANGUAGE_BY_SUFFIX = {
    ".java": "java",
    ".scala": "scala",
    ".go": "go",
    ".rs": "rust",
    ".py": "python",
}


@dataclasses.dataclass(frozen=True)
class CollisionReport:
    """Collision groups over a tree, in total and per language."""

    groups: int
    separated: int
    ordinal: int
    by_language: dict[str, tuple[int, int, int]]


def report_collisions(root: Path) -> CollisionReport:
    """Count collision groups under ``root``, by what separates their members."""
    registry = default_registry()
    tallies: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])

    for path in sorted(root.rglob("*")):
        language = _LANGUAGE_BY_SUFFIX.get(path.suffix)
        if language is None or not path.is_file():
            continue
        parser = registry.parser_for(language)
        if parser is None:
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        request = ParseRequest(
            repository_id="census",
            snapshot_id="census",
            file_id=str(path),
            relative_path=path.relative_to(root).as_posix(),
            language=language,
            content=content,
        )
        buckets: dict[tuple[str, str], list[tuple[str | None, str | None]]] = (
            defaultdict(list)
        )
        definitions = getattr(parser, "definitions_with_discriminators", None)
        if definitions is None:
            # The Python tier has no discriminator hook; signature only.
            for symbol in parser.parse(request).symbols:
                buckets[(symbol.qualified_name, symbol.kind.value)].append(
                    (symbol.signature, None)
                )
        else:
            for symbol, discriminator in definitions(request):
                buckets[(symbol.qualified_name, symbol.kind.value)].append(
                    (symbol.signature, discriminator)
                )
        for separators in buckets.values():
            if len(separators) == 1:
                continue
            tally = tallies[language]
            tally[0] += 1
            if len(set(separators)) == len(separators):
                tally[1] += 1
            else:
                tally[2] += 1

    by_language = {
        language: (tally[0], tally[1], tally[2])
        for language, tally in sorted(tallies.items())
    }
    return CollisionReport(
        groups=sum(tally[0] for tally in by_language.values()),
        separated=sum(tally[1] for tally in by_language.values()),
        ordinal=sum(tally[2] for tally in by_language.values()),
        by_language=by_language,
    )


@dataclasses.dataclass(frozen=True)
class ResidualGroup:
    """One collision group that `(signature, discriminator)` does not separate."""

    language: str
    qualified_name: str
    kind: str
    members: int
    # True when every member carries the same discriminator -- the ~718 class,
    # two declarations sharing one enclosing scope. False means the members
    # differ somewhere the pair does not currently read, which is a different
    # finding and must not be averaged into the same number.
    shared_discriminator: bool


def residual_groups(root: Path) -> list[ResidualGroup]:
    """Every group left on the ordinal, described rather than counted.

    `report_collisions` answers "how many"; the register is holding open "what
    are they". A count cannot distinguish one qualified name appearing twenty
    times from twenty names appearing twice, and those call for different
    conclusions -- one is a naming defect, the other might be an identity one.
    """
    registry = default_registry()
    groups: list[ResidualGroup] = []

    for path in sorted(root.rglob("*")):
        language = _LANGUAGE_BY_SUFFIX.get(path.suffix)
        if language is None or not path.is_file():
            continue
        parser = registry.parser_for(language)
        if parser is None:
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        request = ParseRequest(
            repository_id="census",
            snapshot_id="census",
            file_id=str(path),
            relative_path=path.relative_to(root).as_posix(),
            language=language,
            content=content,
        )
        buckets: dict[tuple[str, str], list[tuple[str | None, str | None]]] = (
            defaultdict(list)
        )
        definitions = getattr(parser, "definitions_with_discriminators", None)
        if definitions is None:
            for symbol in parser.parse(request).symbols:
                buckets[(symbol.qualified_name, symbol.kind.value)].append(
                    (symbol.signature, None)
                )
        else:
            for symbol, discriminator in definitions(request):
                buckets[(symbol.qualified_name, symbol.kind.value)].append(
                    (symbol.signature, discriminator)
                )
        for (name, kind), separators in buckets.items():
            if len(separators) == 1 or len(set(separators)) == len(separators):
                continue
            groups.append(
                ResidualGroup(
                    language=language,
                    qualified_name=name,
                    kind=kind,
                    members=len(separators),
                    shared_discriminator=len({d for _, d in separators}) == 1,
                )
            )
    return groups


def main() -> int:
    """Print a census for each path given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument(
        "--residual-detail",
        action="store_true",
        help="describe the groups left on the ordinal, not just count them",
    )
    arguments = parser.parse_args()

    for path in arguments.paths:
        report = report_collisions(path)
        print(f"{path}")
        print(
            f"  total: {report.groups} groups, "
            f"{report.separated} separated, {report.ordinal} ordinal"
        )
        for language, (groups, separated, ordinal) in report.by_language.items():
            print(f"    {language:8} {groups:6} {separated:6} {ordinal:6}")
        if arguments.residual_detail:
            _print_residual(path)
    return 0


def _print_residual(root: Path) -> None:
    """What the unseparated groups are, per language.

    The ten most frequent names are printed because the register's open
    question is what these groups *are*, and a count cannot answer it: one name
    with twenty members is a naming defect, twenty names with two members each
    might be an identity one.
    """
    residual = residual_groups(root)
    shared = sum(1 for group in residual if group.shared_discriminator)
    print(f"  residual: {len(residual)} groups, {shared} sharing a discriminator")

    by_language: dict[str, list[ResidualGroup]] = defaultdict(list)
    for group in residual:
        by_language[group.language].append(group)
    for language, groups in sorted(by_language.items()):
        same = sum(1 for group in groups if group.shared_discriminator)
        print(f"    {language:8} {len(groups):6} groups, {same:6} shared")
        frequent = sorted(groups, key=lambda g: (-g.members, g.qualified_name))[:10]
        for group in frequent:
            print(f"      {group.qualified_name:44} {group.kind:10} x{group.members}")


if __name__ == "__main__":
    raise SystemExit(main())
