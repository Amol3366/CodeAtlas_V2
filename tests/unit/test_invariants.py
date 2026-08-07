"""The ADR-0016 invariant corpus: its model, and the check it drives."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from codeatlas.contracts import GapReasonCode
from codeatlas.evaluation.invariants import (
    CaseResult,
    InvariantCase,
    InvariantCorpus,
    InvariantCorpusError,
    InvariantResult,
    check_corpus,
    load_corpus,
    render_invariant_markdown,
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


def _corpus(case: InvariantCase, root: Path) -> InvariantCorpus:
    return InvariantCorpus(cases=[case], root=root)


def _fixture_root() -> Path:
    return Path("tests/evaluation/invariant_cases")


def test_an_unrunnable_case_fails_rather_than_skipping(tmp_path: Path) -> None:
    # "did not hold" and "was not measured" must not be the same result.
    # A missing fixture is the realistic way this happens: DirectoryStateView
    # returns an empty scan for a nonexistent root rather than raising, so
    # without an explicit existence check the case would report "nothing
    # changed" and fail for a misleading reason.
    case = InvariantCase(
        id="i001",
        invariant="x",
        fixture="does-not-exist",
        expect_gap_reasons={"Order": GapReasonCode.FIXTURE_MEDIATED_ONLY},
        expect_not_gaps=[],
    )

    result = check_corpus(_corpus(case, tmp_path))

    assert result.held is False
    assert result.results[0].held is False
    assert "fixture" in " ".join(result.results[0].failures)


def test_a_wrong_reason_fails_even_though_it_is_a_gap() -> None:
    # `Order` IS a gap in the real fixture, but for the fixture reason.
    # Demanding the helper reason must fail, or membership alone is all that
    # is being checked.
    case = InvariantCase(
        id="i001",
        invariant="x",
        fixture="orders",
        expect_gap_reasons={"Order": GapReasonCode.HELPER_MEDIATED_ONLY},
        expect_not_gaps=[],
    )

    result = check_corpus(_corpus(case, _fixture_root()))

    assert result.held is False


def test_a_symbol_wrongly_expected_to_be_covered_fails() -> None:
    case = InvariantCase(
        id="i001",
        invariant="x",
        fixture="orders",
        expect_gap_reasons={},
        expect_not_gaps=["Order"],
    )

    result = check_corpus(_corpus(case, _fixture_root()))

    assert result.held is False


def test_the_real_corpus_holds() -> None:
    result = check_corpus(load_corpus(_fixture_root()))

    assert result.held is True


def test_the_markdown_names_a_failure_rather_than_only_counting_it() -> None:
    result = InvariantResult(
        results=[
            CaseResult(
                case_id="i001",
                invariant="a fixture-mediated symbol stays a gap",
                held=False,
                failures=["Order is a gap for None but FIXTURE... expected"],
            )
        ]
    )

    text = render_invariant_markdown(result)

    assert "i001" in text
    assert "Order is a gap" in text


def test_a_pipe_in_a_failure_cannot_break_the_table() -> None:
    result = InvariantResult(
        results=[
            CaseResult(case_id="i001", invariant="a|b", held=False, failures=["x|y"])
        ]
    )

    text = render_invariant_markdown(result)

    row = next(line for line in text.splitlines() if line.startswith("| i001"))
    # `escape_cell` renders a pipe as `\|`, which still contains the character.
    # What must hold is that no *unescaped* pipe was introduced, since only an
    # unescaped one creates a new column.
    assert re.findall(r"(?<!\\)\|", row) == ["|"] * 5
