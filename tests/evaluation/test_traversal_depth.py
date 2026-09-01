"""A graph case declares how far its traversal runs (ADR-0073 ruling 3).

Depth used to be implied. `GraphQueryRequest.max_depth` defaults to 2 and every
graph case silently took it, while ADR-0059 ruled that an expectation declares
**direct** results. So a case declared depth-1 answers and was scored against a
depth-2 traversal, and the undeclared second-hop results read as distractors --
which is exactly why q003, q005, q015 and q053 are reversal-sensitive.

**Every graph case declares 2, the value it was already getting, and that is the
point.** Measurement showed all 31 satisfy their declared relations at depth 1,
but dropping to 1 would delete the depth-2 distractors and with them the ranking
sensitivity ADR-0059 preserved deliberately, turning `exact_symbol_resolution`
from a ranking gate back into a resolution one. ADR-0073 says ruling 3 *extends*
ADR-0059; that would have overturned it. The field is introduced carrying
today's behaviour, so the tracked baselines reproduce byte-for-byte, and any
retuning is a separate decision with its own measurement.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import ValidationError

from codeatlas.application.graph_queries import GraphQueryRequest
from codeatlas.evaluation.dataset import GRAPH_INTENTS, QueryCase, load_dataset
from codeatlas.evaluation.engine_adapter import (
    GRAPH_INTENTS as ADAPTER_GRAPH_INTENTS,
)
from codeatlas.evaluation.engine_adapter import _answer

DATASET_ROOT = Path("tests/evaluation/cases")


def _case(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "qX",
        "repository_fixture": "f",
        "snapshot_id": "s",
        "question": "Who calls total?",
        "intent": "CALLERS",
        "expected_abstention": False,
        "expected_symbols": ["render"],
        "expected_relations": [],
        "expected_evidence": [],
        "warnings": [],
        "limitations": [],
        "forbidden_claims": [],
    }
    base.update(overrides)
    return base


def test_a_graph_case_must_declare_its_depth() -> None:
    """Required, not defaulted -- a default is the implication being removed."""
    with pytest.raises(ValidationError, match="must declare traversal_depth"):
        QueryCase.model_validate(_case())


def test_a_non_graph_case_may_not_declare_a_depth() -> None:
    """Enforced in both directions, because a silently ignored field lies.

    A `traversal_depth` on an `EXACT_SYMBOL` case would read as though it
    controlled the traversal, and nothing would contradict it -- the shape
    ADR-0053 recorded, where a constant nobody checked changed a denominator
    without saying so.
    """
    with pytest.raises(ValidationError, match="would have no effect"):
        QueryCase.model_validate(
            _case(intent="EXACT_SYMBOL", traversal_depth=2)
        )


def test_a_graph_case_declaring_a_depth_is_accepted() -> None:
    case = QueryCase.model_validate(_case(traversal_depth=1))
    assert case.traversal_depth == 1


def test_the_corpus_and_the_adapter_agree_on_which_intents_traverse() -> None:
    """One definition of "graph intent", for ADR-0023's reason.

    The adapter maps each graph intent to a service method; the corpus decides
    which cases must declare a depth. Two definitions that drifted would let a
    case be dispatched to a traversal it never declared a depth for.
    """
    assert set(ADAPTER_GRAPH_INTENTS) == set(GRAPH_INTENTS)


def test_every_graph_case_in_the_corpus_declares_a_depth() -> None:
    """Derived from the corpus, so a new graph case cannot skip the field."""
    dataset = load_dataset(DATASET_ROOT)
    graph_cases = [
        case for case in dataset.query_cases if case.intent in GRAPH_INTENTS
    ]
    assert len(graph_cases) == 31
    assert all(case.traversal_depth is not None for case in graph_cases)


def test_no_non_graph_case_carries_a_depth() -> None:
    dataset = load_dataset(DATASET_ROOT)
    assert all(
        case.traversal_depth is None
        for case in dataset.query_cases
        if case.intent not in GRAPH_INTENTS
    )


def test_the_declared_depths_preserve_the_previous_default() -> None:
    """The introduction changes no answer, and this is what says so.

    If a future change retunes a depth, this test fails and the change has to
    be argued rather than absorbed -- and the tracked baselines will move with
    it, which is the signal ADR-0073 asked to watch for.
    """
    dataset = load_dataset(DATASET_ROOT)
    declared = {
        case.traversal_depth
        for case in dataset.query_cases
        if case.intent in GRAPH_INTENTS
    }
    assert declared == {2}


def test_the_corpus_file_gained_only_the_new_key() -> None:
    """The corpus was not reformatted, which is a real risk here.

    A round-trip through `json.dumps` rewrites all 2600 lines of this file and
    buries the 31 real insertions -- the unrelated reflow the ADR-0069 handoff
    had to strip out of four files. The text is edited in place instead, so
    every case keeps the spacing it had.
    """
    text = (DATASET_ROOT / "queries.json").read_text(encoding="utf-8")
    assert text.count('"traversal_depth":  2,') == 31
    # The file's own convention: two spaces after the colon. If a rewrite
    # normalised it to one, this catches that too.
    assert '"expected_abstention":  false,' in text


class _RecordingGraph:
    """Captures the request the adapter builds, and answers it emptily.

    A real fixture cannot prove this wiring. Every corpus case declares depth
    **2** and `GraphQueryRequest.max_depth` also defaults to 2, so deleting the
    `max_depth=` argument leaves every corpus-driven test green -- verified by
    mutation: 26 of them passed with the wiring removed. Only a stub that reads
    the request can tell "passed the declared depth" from "took the default".
    """

    def __init__(self) -> None:
        self.requests: list[GraphQueryRequest] = []

    def callers(self, request: GraphQueryRequest) -> object:
        self.requests.append(request)
        return _EMPTY_RESPONSE


class _Services:
    def __init__(self, graph: _RecordingGraph) -> None:
        self.graph = graph


class _Answer:
    summary = ""
    claims: ClassVar[list[object]] = []


class _Response:
    evidence: ClassVar[list[object]] = []
    relation_paths: ClassVar[list[object]] = []
    answer = _Answer()


_EMPTY_RESPONSE = _Response()


@pytest.mark.parametrize("declared", [1, 2, 3])
def test_the_adapter_traverses_to_the_depth_the_case_declares(
    declared: int,
) -> None:
    """The wiring, pinned directly.

    Parametrised across three depths on purpose: asserting only `2` would pass
    against a hard-coded default, which is the very thing this field replaces.
    """
    graph = _RecordingGraph()
    case = QueryCase.model_validate(_case(traversal_depth=declared))

    _answer(_Services(graph), "repo-1", case, record_timings=False)

    assert len(graph.requests) == 1
    assert graph.requests[0].max_depth == declared
