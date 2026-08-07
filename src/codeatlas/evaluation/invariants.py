"""The ADR-0016 invariant corpus.

The Phase 4 evaluation corpus measures how accurate change assurance is --- a
number that legitimately moves. This corpus asserts one boolean that must not:
a weak `TESTS` edge explains a gap rather than closing it. Keeping them apart
is why the Phase 4 baseline is untouched by this feature.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from codeatlas.analysis.engine import ChangeAnalysisEngine
from codeatlas.analysis.states import DirectoryStateView
from codeatlas.contracts import ContractModel, GapReasonCode


class InvariantCorpusError(Exception):
    """The corpus could not be read, or does not assert anything."""


class InvariantCase(ContractModel):
    """One scenario and what must be true of it."""

    id: str
    invariant: str
    fixture: str
    # Qualified name -> the reason that name must be reported with. Both
    # halves are asserted: membership in `test_gaps` AND the reason. Checking
    # membership alone would pass if every reason collapsed to one constant.
    expect_gap_reasons: dict[str, GapReasonCode] = Field(default_factory=dict)
    # Names that must NOT be gaps. Without this, a bug making every symbol a
    # permanent gap would satisfy every other assertion in the corpus.
    expect_not_gaps: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_asserts_something(self) -> InvariantCase:
        if not self.expect_gap_reasons and not self.expect_not_gaps:
            raise ValueError(f"case {self.id} asserts nothing and can never fail")
        return self


class InvariantCorpus(ContractModel):
    """Every invariant case, and the fixture root they resolve against."""

    contract_version: Literal["1.0"] = "1.0"
    cases: list[InvariantCase]
    # Not serialized: it is where the corpus was loaded from, not part of it.
    root: Path = Field(default=Path("."), exclude=True)

    @model_validator(mode="after")
    def validate_cases(self) -> InvariantCorpus:
        if not self.cases:
            raise ValueError(
                "an empty corpus would report that every invariant held"
                " having checked none"
            )
        identifiers = [case.id for case in self.cases]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("case ids must be unique")
        return self


def load_corpus(directory: Path) -> InvariantCorpus:
    """Read `cases.json` from `directory`."""
    path = directory / "cases.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InvariantCorpusError(f"cannot read corpus: {error}") from error
    try:
        corpus = InvariantCorpus.model_validate(payload)
    except ValidationError as error:
        raise InvariantCorpusError(f"invalid corpus: {error}") from error
    return corpus.model_copy(update={"root": directory})


class CaseResult(ContractModel):
    """What one case did, and why if it failed."""

    case_id: str
    invariant: str
    held: bool
    # Human-readable, corpus-relative. Never an absolute path: rules.md
    # forbids emitting one, and it would also break reproducibility.
    failures: list[str] = Field(default_factory=list)


class InvariantResult(ContractModel):
    """Every case result. This is what gets committed as the artifact."""

    contract_version: Literal["1.0"] = "1.0"
    results: list[CaseResult]

    @property
    def held(self) -> bool:
        return all(result.held for result in self.results)


def check_corpus(corpus: InvariantCorpus) -> InvariantResult:
    """Run every case through the real engine and compare."""
    engine = ChangeAnalysisEngine()
    results = [_check_case(engine, corpus, case) for case in corpus.cases]
    return InvariantResult(results=results)


def _failed(case: InvariantCase, *failures: str) -> CaseResult:
    return CaseResult(
        case_id=case.id,
        invariant=case.invariant,
        held=False,
        failures=list(failures),
    )


def _check_case(
    engine: ChangeAnalysisEngine,
    corpus: InvariantCorpus,
    case: InvariantCase,
) -> CaseResult:
    fixture = corpus.root / "fixtures" / case.fixture
    # `DirectoryStateView` returns an empty scan for a root that does not
    # exist rather than raising. Without this check a mistyped fixture name
    # would report "nothing changed", and every expectation would fail for a
    # reason that names the wrong problem.
    for side in ("base", "target"):
        if not (fixture / side).is_dir():
            return _failed(case, f"fixture {case.fixture}/{side} is missing")

    try:
        report = engine.analyze(
            DirectoryStateView(fixture / "base"),
            DirectoryStateView(fixture / "target"),
        )
    except Exception as error:
        # Deliberately broad: any reason the engine cannot run this case is a
        # failure of the case, never a skip. A gate that reports "held" for a
        # case it could not execute is the exact problem this corpus exists
        # to fix.
        return _failed(case, f"case could not be run: {type(error).__name__}")

    gaps = set(report.impact.test_gaps)
    reasons = {
        item.qualified_name: item.reason for item in report.impact.test_gap_reasons
    }

    failures: list[str] = []
    for name, expected in sorted(case.expect_gap_reasons.items()):
        if name not in gaps:
            failures.append(
                f"{name} was expected to remain a gap but was not reported"
            )
            continue
        actual = reasons.get(name)
        if actual != expected:
            failures.append(
                f"{name} is a gap for {actual} but {expected} was expected"
            )
    for name in sorted(case.expect_not_gaps):
        if name in gaps:
            failures.append(
                f"{name} was expected to be covered but was reported a gap"
            )

    return CaseResult(
        case_id=case.id,
        invariant=case.invariant,
        held=not failures,
        failures=failures,
    )
