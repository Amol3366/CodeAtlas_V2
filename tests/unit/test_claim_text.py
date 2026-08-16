"""The sentence a claim renders, and what it may not assert.

ADR-0016: a `TESTS` edge derived through a fixture parameter or a helper call
explains rather than proves. `impact` applied that rule; this surface did not,
and rendered such an edge as "X tests Y" while citing a line that never names
Y.
"""

from __future__ import annotations

import pytest

from codeatlas.application.graph_queries import claim_text
from codeatlas.contracts import Derivation, RelationKind
from codeatlas.domain.relations import (
    FIXTURE_HINT,
    HELPER_HINT,
    RelationRecord,
    ResolutionState,
)


def _edge(
    *,
    kind: RelationKind = RelationKind.TESTS,
    module_hint: str = "",
    derivation: Derivation = Derivation.HIGH_CONFIDENCE_HEURISTIC,
) -> RelationRecord:
    return RelationRecord(
        relation_id="rel_1",
        source_symbol_id="sym_test_total",
        target_symbol_id="sym_Order",
        file_id="file_1",
        kind=kind,
        target_hint="Order",
        resolution=ResolutionState.RESOLVED,
        derivation=derivation,
        confidence=0.5,
        start_line=7,
        end_line=7,
        candidate_count=1,
        module_hint=module_hint,
    )


def _text(edge: RelationRecord) -> str:
    return claim_text(
        edge=edge,
        other="test_total",
        root_name="Order",
        file_path="tests/test_orders.py",
        start_line=7,
        inbound=True,
    )


def test_a_strict_tests_edge_still_reads_as_a_test() -> None:
    # Without this, a change that hedged EVERY claim would satisfy every other
    # test in this file.
    text = _text(_edge())

    assert text == "test_total tests Order at tests/test_orders.py:7."


def test_a_fixture_mediated_edge_does_not_assert_coverage() -> None:
    text = _text(
        _edge(
            module_hint=FIXTURE_HINT,
            derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
        )
    )

    assert "may exercise" in text
    assert "through a fixture" in text
    assert "indirectly" in text


def test_a_helper_mediated_edge_names_the_helper_path() -> None:
    text = _text(
        _edge(
            module_hint=HELPER_HINT,
            derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
        )
    )

    assert "through a helper" in text


@pytest.mark.parametrize("hint", [FIXTURE_HINT, HELPER_HINT])
def test_a_mediated_claim_never_says_the_test_tests_the_symbol(hint: str) -> None:
    # The actual invariant, and the one a future refactor would break without
    # noticing. Any rewording is free as long as it does not reintroduce the
    # bare verb.
    text = _text(
        _edge(module_hint=hint, derivation=Derivation.LOW_CONFIDENCE_HEURISTIC)
    )

    assert " tests " not in text


def test_the_citation_is_still_present_on_a_mediated_claim() -> None:
    # The line does not show the relationship, but dropping it would leave the
    # claim uncitable, which is worse than citing a weak location honestly.
    text = _text(
        _edge(
            module_hint=FIXTURE_HINT,
            derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
        )
    )

    assert "tests/test_orders.py:7" in text


def test_a_hint_on_a_non_tests_edge_is_ignored() -> None:
    # `module_hint` is also used by document derivation. Only a TESTS edge may
    # be reworded, or an unrelated edge kind would start hedging.
    text = claim_text(
        edge=_edge(kind=RelationKind.CALLS, module_hint=FIXTURE_HINT),
        other="render",
        root_name="total",
        file_path="a.py",
        start_line=3,
        inbound=True,
    )

    assert text == "render calls total at a.py:3."


def test_an_outbound_claim_leads_with_the_root() -> None:
    text = claim_text(
        edge=_edge(kind=RelationKind.CALLS),
        other="helper",
        root_name="total",
        file_path="a.py",
        start_line=3,
        inbound=False,
    )

    assert text == "total calls helper at a.py:3."


# --- ADR-0052: a claim beyond the first hop ---------------------------------
#
# `max_depth` is 2 by default, so a graph answer routinely contains edges that
# touch neither end of the root. `_claims` used to render those with the root's
# name anyway, producing "A calls ROOT" for an A that calls something else
# entirely — and citing A's call to the intermediate as proof. The structured
# `relation_paths` always carried the real path; only the prose overstated it.


def test_an_indirect_inbound_claim_does_not_assert_a_direct_call() -> None:
    text = claim_text(
        edge=_edge(kind=RelationKind.CALLS),
        other="test_capture",
        root_name="IdempotencyStore.claim",
        file_path="tests/test_service.py",
        start_line=5,
        inbound=True,
        intermediate="PaymentService.capture",
    )

    # The thing it must never say: the test does not call `claim`.
    assert "test_capture calls IdempotencyStore.claim" not in text
    assert "indirectly" in text
    assert "PaymentService.capture" in text
    assert text.endswith(" at tests/test_service.py:5.")


def test_an_indirect_outbound_claim_names_the_symbol_it_went_through() -> None:
    text = claim_text(
        edge=_edge(kind=RelationKind.REFERENCES),
        other="Order",
        root_name="src.client",
        file_path="src/orders.ts",
        start_line=5,
        inbound=False,
        intermediate="total",
    )

    assert "src.client references Order" not in text
    assert "indirectly" in text
    assert "total" in text


def test_a_direct_claim_is_unchanged_when_no_intermediate_is_given() -> None:
    # The regression this pairs with: hedging every claim would satisfy both
    # tests above while destroying the direct wording.
    text = claim_text(
        edge=_edge(kind=RelationKind.CALLS),
        other="render",
        root_name="total",
        file_path="a.py",
        start_line=3,
        inbound=True,
        intermediate=None,
    )

    assert text == "render calls total at a.py:3."
