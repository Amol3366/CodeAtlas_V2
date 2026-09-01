"""Routing is a second axis, and the corpus holds it still by design.

`engine_adapter._query_term` feeds the declared symbol rather than the
question, because Phase 1 measured resolution accuracy and said so. The
consequence was recorded but never measured: a question a real user types may
reach a different channel than the one the corpus scored, and **no number
moves**.

These tests pin the reroute itself -- the map is total, the corpus is not
mutated, and a rerouted case still satisfies ADR-0075's depth rule. The number
the instrument produces is not asserted here: it is a measurement of the
product, not a property of it, and pinning it would turn a routing improvement
into a test failure.

Placed beside `test_report_intent_agreement.py`, which pins the DR-09
instrument this one extends.
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.conversations.intent import Intent
from codeatlas.evaluation.dataset import GRAPH_INTENTS, load_dataset
from scripts.report_intent_agreement import _CHANNEL_BY_INTENT
from scripts.report_routing_fidelity import (
    CORPUS_INTENT_BY_CHANNEL,
    reroute,
    route,
)

DATASET_ROOT = Path("tests/evaluation/cases")


def test_every_classifier_channel_has_a_declared_corpus_intent() -> None:
    """Total, so a new `Intent` member cannot be silently unrouted.

    A missing key would raise `KeyError` mid-run for whichever question
    happened to hit it, which reads as a broken instrument rather than as an
    unmapped channel.
    """
    assert set(CORPUS_INTENT_BY_CHANNEL) == set(Intent)


def test_the_map_inverts_the_one_dr_09_already_committed() -> None:
    """Derived from `_CHANNEL_BY_INTENT`, so the two cannot disagree.

    DR-09 committed corpus-intent -> channel. This tool needs the inverse, and
    a transcribed inverse is a second definition that can drift -- the exact
    failure ADR-0023 moved the intent vocabulary into `dataset.py` to prevent.
    Written out and checked instead.

    Without this the map's *values* are unpinned: the totality test above only
    proves every `Intent` is a key, so pointing `TRACE` at `None` would leave
    the whole module green.
    """
    for corpus_intent, channel in _CHANNEL_BY_INTENT.items():
        if channel is None:
            continue
        assert CORPUS_INTENT_BY_CHANNEL[Intent(channel)] == corpus_intent, channel


def test_the_text_channel_maps_to_the_lexical_corpus_intent() -> None:
    """The one entry DR-09's map cannot supply, pinned with its reason.

    `_CHANNEL_BY_INTENT` records `CONCEPTUAL: None` -- the classifier has no
    *conceptual* channel to agree with. The inverse question is different and
    does have an answer: a question the classifier gives up on becomes `TEXT`,
    and `TEXT` is answered by `search_text`, which is precisely the adapter's
    `else` branch and the channel `CONCEPTUAL` names.
    """
    assert CORPUS_INTENT_BY_CHANNEL[Intent.TEXT] == "CONCEPTUAL"
    assert _CHANNEL_BY_INTENT["CONCEPTUAL"] is None


def test_rerouting_never_mutates_the_loaded_corpus() -> None:
    """ADR-0003: the corpus is not edited to move a number."""
    dataset = load_dataset(DATASET_ROOT)
    before = [(c.id, c.intent, c.traversal_depth) for c in dataset.query_cases]
    reroute(dataset)
    after = [(c.id, c.intent, c.traversal_depth) for c in dataset.query_cases]
    assert before == after


def test_a_rerouted_graph_case_carries_a_depth_and_a_lexical_one_does_not() -> None:
    """ADR-0075 makes depth required for graph intents and forbidden elsewhere.

    A reroute ignoring this would build cases the loader would refuse, so the
    instrument would be measuring a corpus the product could never validate.
    """
    routed, _ = reroute(load_dataset(DATASET_ROOT))
    for case in routed.query_cases:
        if case.intent in GRAPH_INTENTS:
            assert case.traversal_depth is not None, case.id
        else:
            assert case.traversal_depth is None, case.id


def test_a_case_the_classifier_routes_elsewhere_is_reported_as_moved() -> None:
    """The moved list is the instrument's own evidence.

    Every case whose channel changes must appear in it, or the delta would be
    attributed to a reroute nobody can enumerate.
    """
    dataset = load_dataset(DATASET_ROOT)
    routed, moved = reroute(dataset)
    moved_ids = {case_id for case_id, _, _ in moved}
    for before, after in zip(dataset.query_cases, routed.query_cases, strict=True):
        if before.intent != after.intent:
            assert before.id in moved_ids, before.id


def test_an_unroutable_case_keeps_its_declared_intent() -> None:
    """DR-09's `n/a` treatment, for its reason.

    `CALLEES`, `CHANGE`, `GREETING` and `PROJECT_OVERVIEW` are channels the
    corpus has no intent for. Scoring a case sent there as a miss would invent
    a disagreement, so it stays as declared and is reported separately.
    """
    dataset = load_dataset(DATASET_ROOT)
    routed, moved = reroute(dataset)
    unroutable = {case_id for case_id, _, target in moved if target is None}
    by_id = {case.id: case for case in routed.query_cases}
    for case in dataset.query_cases:
        if case.id in unroutable:
            assert by_id[case.id].intent == case.intent


def test_the_unroutable_branch_is_exercised_even_though_the_corpus_has_none() -> None:
    """Measured: **zero** corpus cases are unroutable, so the check above is
    vacuous today.

    Every one of the 63 questions the classifier re-routes lands on `TEXT`;
    none reaches `CALLEES`, `CHANGE`, `GREETING` or `PROJECT_OVERVIEW`. A
    mutation that broke the unroutable path would therefore leave the corpus
    assertion green -- a mutation that cannot apply is indistinguishable from a
    test that cannot catch it (ADR-0055) -- so the branch is driven directly
    with a question the classifier does send to a channel the corpus lacks.
    """
    dataset = load_dataset(DATASET_ROOT)
    probe = dataset.query_cases[0].model_copy(
        update={
            "id": "qZZZ",
            "question": "what does capture call",
            "intent": "EXACT_SYMBOL",
        }
    )
    assert route(probe) is None, "a CALLEES question has no corpus intent"

    synthetic = dataset.model_copy(update={"query_cases": [probe]})
    routed, moved = reroute(synthetic)
    assert moved == [("qZZZ", "EXACT_SYMBOL", None)]
    assert routed.query_cases[0].intent == "EXACT_SYMBOL"
