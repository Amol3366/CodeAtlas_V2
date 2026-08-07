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
