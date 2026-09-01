"""A case naming an ambiguous symbol is pinned by its evidence, not its name.

`exact_symbol_resolution`, `mean_reciprocal_rank` and `abstention_correctness`
all read a symbol's **name**. None of them can separate two symbols that share
one, so on a fixture defining the same qualified name twice they are blind to
which one the engine returned.

q035 is the proof. Declaring its `query_subject` restored
`exact_symbol_resolution` to 1.0000, and the wrong-side mutation -- pointing the
subject at the *other* side's `process` -- then scored **identically** (ADR-0050).
What made the case discriminate was correcting its evidence to the reference
site: the two sides' reference sites are in different files while their names
are not.

**The audit this guard replaces found no remaining exposure**, and found the
row's model too broad. The corpus defines exactly one qualified name in more than
one file -- `process`, in `git_changes` -- and all three cases naming it (q033,
q034, q035) pin their evidence to one file.

**They cannot do otherwise, and that is the correction.** `git-base` declares
only `base/service.py` and `git-target` only `target/processor.py`, so the two
`process` symbols are in *different snapshots* and the dataset validator
(ADR-0047 ruling 4) already refuses evidence outside a case's declared members.
The row says "any fixture holding same-named symbols has this blind spot"; what
it actually needs is same-named symbols **within one snapshot**, and no fixture
has that.

So the corpus-wide assertion below **cannot currently fail**, and a mutation
against the real corpus is refused by the loader before reaching it. That is the
ADR-0055 shape -- a mutation that cannot apply is indistinguishable from a test
that cannot catch it -- so the predicate is exercised directly against synthetic
input as well, which is where its teeth are proven.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from codeatlas.evaluation.dataset import load_dataset
from codeatlas.parsing.registry import ParseRequest, default_registry

DATASET_ROOT = Path("tests/evaluation/cases")

_LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".ts": "typescript",
    ".js": "javascript",
    ".java": "java",
    ".scala": "scala",
    ".go": "go",
    ".rs": "rust",
    ".md": "markdown",
}


def _names_by_file(root: Path) -> dict[str, set[str]]:
    """Every qualified name a fixture defines, mapped to the files defining it.

    Parsed directly rather than indexed: the question is what the *fixture*
    contains, and going through storage would make this depend on snapshot
    lifecycle for no gain.
    """
    registry = default_registry()
    per_name: dict[str, set[str]] = defaultdict(set)
    for path in sorted(root.rglob("*")):
        language = _LANGUAGE_BY_SUFFIX.get(path.suffix)
        if language is None or not path.is_file():
            continue
        parser = registry.parser_for(language)
        if parser is None:
            continue
        relative = path.relative_to(root).as_posix()
        parsed = parser.parse(
            ParseRequest(
                repository_id="audit",
                snapshot_id="audit",
                file_id=relative,
                relative_path=relative,
                language=language,
                content=path.read_bytes(),
            )
        )
        for symbol in parsed.symbols:
            per_name[symbol.qualified_name].add(relative)
    return per_name


def _ambiguous_names() -> dict[str, set[str]]:
    """Fixture id -> the qualified names it defines in more than one file."""
    dataset = load_dataset(DATASET_ROOT)
    ambiguous: dict[str, set[str]] = {}
    for fixture in dataset.fixtures:
        root = dataset.fixtures_root / fixture.root
        if not root.exists():
            continue
        repeated = {
            name
            for name, paths in _names_by_file(root).items()
            if len(paths) > 1
        }
        if repeated:
            ambiguous[fixture.id] = repeated
    return ambiguous


def test_the_corpus_still_contains_an_ambiguous_name() -> None:
    """Guard the guard.

    The assertion below passes vacuously on a corpus with no same-named symbols
    anywhere, and a fixture rename or a parser change could produce exactly
    that. `git_changes` keeps two sides that both define `process`, which is
    what gives the real check something to check.
    """
    ambiguous = _ambiguous_names()
    assert "process" in ambiguous.get("git_changes", set()), (
        "git_changes no longer defines `process` on both sides; this module's "
        "real assertion has nothing left to exercise"
    )


class _EvidenceLike(Protocol):
    @property
    def file_path(self) -> str: ...


class _CaseLike(Protocol):
    """The three fields this predicate reads.

    A structural type so the real `QueryCase` and the synthetic stand-in below
    are both acceptable without the test importing a Pydantic model it would
    then have to construct in full.
    """

    @property
    def id(self) -> str: ...

    @property
    def repository_fixture(self) -> str: ...

    @property
    def expected_symbols(self) -> Sequence[str]: ...

    @property
    def expected_evidence(self) -> Sequence[_EvidenceLike]: ...


def unpinned_ambiguous_cases(
    cases: Iterable[_CaseLike],
    ambiguous: Mapping[str, AbstractSet[str]],
) -> list[str]:
    """Cases naming an ambiguous symbol whose evidence names no single file.

    Split out from the corpus assertion so it can be exercised against
    synthetic input. The real corpus cannot produce a failure today, and a
    predicate only ever run against inputs that satisfy it has demonstrated
    nothing.
    """
    unpinned: list[str] = []
    for case in cases:
        repeated = ambiguous.get(case.repository_fixture, frozenset())
        if not any(symbol in repeated for symbol in case.expected_symbols):
            continue
        files = {item.file_path for item in case.expected_evidence}
        if len(files) != 1:
            unpinned.append(case.id)
    return unpinned


def test_a_case_naming_an_ambiguous_symbol_pins_its_evidence_to_one_file() -> None:
    """The only defence a name-based metric cannot provide for itself.

    Derived from the corpus rather than listing q033/q034/q035, so a new case
    on any future ambiguous name is covered without editing this test.
    """
    dataset = load_dataset(DATASET_ROOT)
    unpinned = unpinned_ambiguous_cases(dataset.query_cases, _ambiguous_names())

    assert not unpinned, (
        "these cases name a symbol their fixture defines more than once, but "
        f"their evidence does not pin one file: {', '.join(sorted(unpinned))}. "
        "Every name-based metric is blind to which one was returned, so the "
        "case can score 1.0 for the wrong symbol (ADR-0050)."
    )


# --- the predicate, proven against input the real corpus cannot produce -------


@dataclass(frozen=True)
class _Evidence:
    file_path: str


@dataclass(frozen=True)
class _Case:
    id: str
    repository_fixture: str
    expected_symbols: list[str]
    expected_evidence: list[_Evidence] = field(default_factory=list)


_AMBIGUOUS = {"fx": {"process"}}


def test_the_predicate_flags_a_case_whose_evidence_names_two_files() -> None:
    """The shape the corpus cannot express: one snapshot, two same-named symbols."""
    case = _Case(
        id="qA",
        repository_fixture="fx",
        expected_symbols=["process"],
        expected_evidence=[_Evidence("a/x.py"), _Evidence("b/x.py")],
    )
    assert unpinned_ambiguous_cases([case], _AMBIGUOUS) == ["qA"]


def test_the_predicate_flags_a_case_with_no_evidence_at_all() -> None:
    """No evidence is not a pin. q035 scored 1.0 for the wrong symbol this way."""
    case = _Case(id="qB", repository_fixture="fx", expected_symbols=["process"])
    assert unpinned_ambiguous_cases([case], _AMBIGUOUS) == ["qB"]


def test_the_predicate_accepts_a_pinned_case() -> None:
    case = _Case(
        id="qC",
        repository_fixture="fx",
        expected_symbols=["process"],
        expected_evidence=[_Evidence("a/x.py"), _Evidence("a/x.py")],
    )
    assert unpinned_ambiguous_cases([case], _AMBIGUOUS) == []


def test_the_predicate_ignores_a_case_naming_no_ambiguous_symbol() -> None:
    """An unambiguous name needs no pin; flagging it would be noise."""
    case = _Case(id="qD", repository_fixture="fx", expected_symbols=["render"])
    assert unpinned_ambiguous_cases([case], _AMBIGUOUS) == []
