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


def main() -> int:
    """Print a census for each path given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
