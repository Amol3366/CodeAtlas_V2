"""The ADR-0016 invariant corpus: its model, and the check it drives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeatlas.contracts import GapReasonCode
from codeatlas.evaluation.invariants import (
    InvariantCorpusError,
    load_corpus,
)


def _write(directory: Path, payload: dict[str, object]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cases.json").write_text(json.dumps(payload), encoding="utf-8")
    return directory


def _case(**overrides: object) -> dict[str, object]:
    case: dict[str, object] = {
        "id": "i001",
        "invariant": "a fixture-mediated symbol stays a gap",
        "fixture": "orders",
        "expect_gap_reasons": {"Order": "FIXTURE_MEDIATED_ONLY"},
        "expect_not_gaps": [],
    }
    case.update(overrides)
    return case


def test_a_corpus_round_trips(tmp_path: Path) -> None:
    directory = _write(tmp_path, {"contract_version": "1.0", "cases": [_case()]})

    corpus = load_corpus(directory)

    assert corpus.cases[0].id == "i001"
    assert (
        corpus.cases[0].expect_gap_reasons["Order"]
        is GapReasonCode.FIXTURE_MEDIATED_ONLY
    )


def test_an_unknown_reason_code_is_refused(tmp_path: Path) -> None:
    # A typo in a reason code must not silently become an expectation that
    # can never fail.
    directory = _write(
        tmp_path,
        {
            "contract_version": "1.0",
            "cases": [_case(expect_gap_reasons={"Order": "FIXTURE_ONLY"})],
        },
    )

    with pytest.raises(InvariantCorpusError):
        load_corpus(directory)


def test_an_unknown_field_is_refused(tmp_path: Path) -> None:
    directory = _write(
        tmp_path,
        {"contract_version": "1.0", "cases": [_case(expect_coverage=True)]},
    )

    with pytest.raises(InvariantCorpusError):
        load_corpus(directory)


def test_a_missing_corpus_is_an_error_not_an_empty_pass(tmp_path: Path) -> None:
    # An empty corpus would report "all invariants held" having checked none.
    with pytest.raises(InvariantCorpusError):
        load_corpus(tmp_path / "absent")


def test_a_corpus_with_no_cases_is_refused(tmp_path: Path) -> None:
    directory = _write(tmp_path, {"contract_version": "1.0", "cases": []})

    with pytest.raises(InvariantCorpusError):
        load_corpus(directory)


def test_a_case_asserting_nothing_is_refused(tmp_path: Path) -> None:
    # Both expectation fields empty means the case cannot fail.
    directory = _write(
        tmp_path,
        {
            "contract_version": "1.0",
            "cases": [_case(expect_gap_reasons={}, expect_not_gaps=[])],
        },
    )

    with pytest.raises(InvariantCorpusError):
        load_corpus(directory)


def test_duplicate_case_ids_are_refused(tmp_path: Path) -> None:
    directory = _write(
        tmp_path, {"contract_version": "1.0", "cases": [_case(), _case()]}
    )

    with pytest.raises(InvariantCorpusError):
        load_corpus(directory)
