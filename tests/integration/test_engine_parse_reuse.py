"""An unchanged file is parsed once per analysis, not once per side.

Measured 2026-08-18 (ADR-0060): a commit-range preflight over this repository
takes 635 s, and **99.5% of it is parsing** -- `parse_base` 316 s plus
`parse_target` 316 s. The two numbers are near-identical because the two sides
share almost every file: only what actually changed differs.

Every field of the `ParseRequest` the engine builds comes from
`(relative_path, language, content)` -- `repository_id` and `snapshot_id` are
the same constant on both sides, and `file_id` is derived from the path. So for
an unchanged file the two sides construct a **byte-identical** request and parse
it twice, discarding one of two identical answers.

Reuse is therefore correct within a single `analyze()` call by construction,
with no invalidation question to rule on: same inputs, same process, same
parser instance.

**These are call-counting tests, not timing tests.** They assert how many times
the parser runs, which is deterministic, rather than how long it takes, which
would flake in a gate.
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.analysis.engine import ChangeAnalysisEngine
from codeatlas.analysis.states import DirectoryStateView
from codeatlas.parsing.python_parser import PythonParser
from codeatlas.parsing.registry import (
    ParseRequest,
    ParseResult,
    ParserRegistry,
)

UNCHANGED_A = "def alpha() -> str:\n    return 'a'\n"
UNCHANGED_B = "def beta() -> str:\n    return 'b'\n"
CHANGED_BASE = "def gamma() -> str:\n    return 'c'\n"
CHANGED_TARGET = "def gamma() -> str:\n    return 'changed'\n"


class _CountingParser:
    """Wraps the real parser so results stay valid while calls are counted."""

    def __init__(self) -> None:
        self._inner = PythonParser()
        self.name = self._inner.name
        self.version = self._inner.version
        self.supported_languages = self._inner.supported_languages
        self.calls: list[tuple[str, bytes]] = []

    def parse(self, request: ParseRequest) -> ParseResult:
        self.calls.append((request.relative_path, request.content))
        return self._inner.parse(request)


def _view(tmp_path: Path, name: str, files: dict[str, str]) -> DirectoryStateView:
    root = tmp_path / name
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return DirectoryStateView(root)


def _run(tmp_path: Path) -> _CountingParser:
    parser = _CountingParser()
    registry = ParserRegistry()
    registry.register(parser)

    base = _view(
        tmp_path,
        "base",
        {"a.py": UNCHANGED_A, "b.py": UNCHANGED_B, "c.py": CHANGED_BASE},
    )
    target = _view(
        tmp_path,
        "target",
        {"a.py": UNCHANGED_A, "b.py": UNCHANGED_B, "c.py": CHANGED_TARGET},
    )
    ChangeAnalysisEngine(registry=registry).analyze(base, target)
    return parser


def test_an_unchanged_file_is_parsed_once_for_both_sides(tmp_path: Path) -> None:
    """Three files, one changed: four distinct parses, not six."""
    parser = _run(tmp_path)

    distinct = set(parser.calls)
    assert len(distinct) == 4, distinct
    assert len(parser.calls) == 4, (
        f"the parser ran {len(parser.calls)} times for {len(distinct)} distinct"
        " inputs; unchanged files are still parsed once per side"
    )


def test_the_changed_file_is_parsed_on_both_sides(tmp_path: Path) -> None:
    """Reuse must not collapse a file whose content actually differs.

    The failure this guards against is the mirror of the one being fixed:
    keying reuse on the path alone would return the base parse for the target,
    which reports a changed file as unchanged -- a silent wrong answer rather
    than a slow one.
    """
    parser = _run(tmp_path)

    changed = [call for call in parser.calls if call[0] == "c.py"]
    assert len(changed) == 2, changed
    assert {content for _, content in changed} == {
        CHANGED_BASE.encode("utf-8"),
        CHANGED_TARGET.encode("utf-8"),
    }


def test_reuse_does_not_change_the_report(tmp_path: Path) -> None:
    """The same analysis through the real registry still finds the change."""
    base = _view(
        tmp_path,
        "real_base",
        {"a.py": UNCHANGED_A, "b.py": UNCHANGED_B, "c.py": CHANGED_BASE},
    )
    target = _view(
        tmp_path,
        "real_target",
        {"a.py": UNCHANGED_A, "b.py": UNCHANGED_B, "c.py": CHANGED_TARGET},
    )

    report = ChangeAnalysisEngine().analyze(base, target)

    changed_paths = {change.path for change in report.changed_files}
    assert changed_paths == {"c.py"}, changed_paths
    assert {change.qualified_name for change in report.changed_symbols} == {
        "gamma"
    }
