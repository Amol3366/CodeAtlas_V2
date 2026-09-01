"""The instrument DR-09's audit was taken with, committed rather than probed.

A Deferred Register row called the ``TRACE_FLOW`` label "systemically wrong" on
the evidence of three cases, and carried a wrong count twice: "six cases" after
ADR-0051 had already re-typed one of them, and "the classifier disagrees for
every one checked" when one of five agrees. ADR-0073 ruling 4 authorised an
audit before a ruling. This module tests the tool that audit was run with.

The property that matters is the one ADR-0053 records: **an intent the
classifier has no channel for must not be scored as a disagreement.** Counting
it as a miss would invent a disagreement exactly as a gated intent leaving the
denominator invented an average -- and `CONFIG_LOOKUP` alone is six of the
corpus's eighty cases, so the invented figure would be large enough to be
believed.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.report_intent_agreement import report_agreement

_MANIFEST = {
    "contract_version": "1.0",
    "fixtures_root": "fixtures",
    "fixtures": [
        {
            "id": "f",
            "root": "f",
            "kind": "python",
            "snapshots": [{"id": "s", "members": ["a.py"]}],
        }
    ],
    "query_cases_file": "queries.json",
    "change_cases_file": "changes.json",
}


_CHANGE_CASE: dict[str, object] = {
    "id": "c1",
    "repository_fixture": "f",
    "snapshot_id": "s",
    "base_ref": "HEAD",
    "target_ref": "working-tree:none",
    "expected_symbols": ["x"],
    "expected_relations": [],
    "expected_evidence": [],
    "expected_changed_symbols": ["x"],
    "expected_impact_paths": [],
    "expected_findings": [],
    "warnings": [],
    "limitations": [],
    "forbidden_claims": [],
}


def _corpus(root: Path, cases: list[dict[str, object]]) -> Path:
    """A minimal on-disk corpus holding just the cases a test needs."""
    (root / "fixtures" / "f").mkdir(parents=True)
    (root / "fixtures" / "f" / "a.py").write_text("x = 1\n", encoding="utf-8")
    # The manifest declares its own cardinality, so the loader refuses a corpus
    # that lost or gained a case silently. Each test builds its own count.
    manifest = {
        **_MANIFEST,
        "expected_query_count": len(cases),
        "expected_change_count": 1,
    }
    (root / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")
    # The loader requires at least one change case. This tool reads only query
    # cases, so the change side is the smallest thing that validates.
    (root / "changes.json").write_text(
        json.dumps({"cases": [_CHANGE_CASE]}), encoding="utf-8"
    )
    (root / "queries.json").write_text(
        json.dumps({"cases": cases}), encoding="utf-8"
    )
    return root


def _case(case_id: str, intent: str, question: str) -> dict[str, object]:
    return {
        "id": case_id,
        "repository_fixture": "f",
        "snapshot_id": "s",
        "question": question,
        "intent": intent,
        "expected_abstention": False,
        "expected_symbols": ["x"],
        "expected_relations": [],
        "expected_evidence": [],
        "warnings": [],
        "limitations": [],
        "forbidden_claims": [],
    }


def test_a_command_shaped_question_agrees_with_its_declared_intent(
    tmp_path: Path,
) -> None:
    """`callers of X` is the phrasing the classifier's rule was written for."""
    root = _corpus(tmp_path, [_case("a1", "CALLERS", "callers of total")])
    (report,) = report_agreement(root)
    assert report.intent == "CALLERS"
    assert report.agreeing == 1
    assert report.returned == {"callers": 1}


def test_a_natural_language_question_disagrees_and_is_counted_as_a_miss(
    tmp_path: Path,
) -> None:
    """The corpus's normal shape. This is the disagreement the audit measured."""
    root = _corpus(tmp_path, [_case("a2", "CALLERS", "What uses the total?")])
    (report,) = report_agreement(root)
    assert report.agreeing == 0
    assert report.returned == {"text": 1}


def test_an_intent_with_no_classifier_channel_is_not_scored_at_all(
    tmp_path: Path,
) -> None:
    """ADR-0053's shape: undefined must not be reported as false.

    `CONFIG_LOOKUP` has no `Intent` member, so there is no value `classify()`
    could return that would count as agreement. Scoring it 0/n would report a
    disagreement that cannot exist, and six of the corpus's cases carry it.
    """
    root = _corpus(
        tmp_path, [_case("a3", "CONFIG_LOOKUP", "What is the service port?")]
    )
    (report,) = report_agreement(root)
    assert report.agreeing is None
    assert report.cases == 1


def test_each_declared_intent_is_reported_once_with_its_own_tally(
    tmp_path: Path,
) -> None:
    """Per-intent tallies are the control the register row never had.

    The row generalised from `TRACE_FLOW` alone. Only a per-intent breakdown
    shows that `EXACT_SYMBOL` disagrees more often, which is what turns the
    finding from "this label is wrong" into "declared intent is not a classifier
    prediction anywhere in this corpus".
    """
    root = _corpus(
        tmp_path,
        [
            _case("a4", "RELATED_TESTS", "tests for capture"),
            _case("a5", "TRACE_FLOW", "Trace the flow from mount."),
            _case("a6", "TRACE_FLOW", "Where does the frontend load orders?"),
        ],
    )
    reports = {item.intent: item for item in report_agreement(root)}
    assert reports["RELATED_TESTS"].agreeing == 1
    assert reports["TRACE_FLOW"].cases == 2
    assert reports["TRACE_FLOW"].agreeing == 1
    assert reports["TRACE_FLOW"].returned == {"trace": 1, "text": 1}
