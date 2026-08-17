"""A lexical answer carries the resolved edges of what it matched.

The last of ADR-0034's four causes. `relation_path_correctness` averaged four
unrelated problems; three were settled by ADR-0034, ADR-0039 and ADR-0055, and
this is the fourth: the declared edges of q024, q027 and q029 **are stored and
resolved**, and the lexical answers returned `relation_paths: []` because only
the graph intents ever populated that field.

Ruled by the user 2026-08-17: a lexical or conceptual answer emits relation
paths, restricted to edges that **resolve to a real target**. The restriction
is ADR-0055's precedent — an unresolved route cites nothing extra — and it is
structural rather than stylistic: an unresolved edge has no far endpoint, so it
cannot form a path at all.

Two invariants the ruling turns on, both asserted below:

* a lexical hit is evidence of *wording*, not behaviour, so emitting a path
  must not upgrade the answer's claims or their derivation;
* a step cites an evidence item the answer **already returned**, never a new
  one, so `containing_evidence_rate` cannot move.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import Derivation, QueryResponse
from codeatlas.conversations.pipeline import AnswerPipeline, AnswerRequest
from codeatlas.retrieval.lexical import _containing
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

MIXED = Path("tests/evaluation/cases/fixtures/mixed_app")
DOCS_CONFIG = Path("tests/evaluation/cases/fixtures/docs_config")


def _answer(fixture: Path, tmp_path: Path, question: str) -> QueryResponse:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services: ApplicationServices = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(fixture.resolve()))
        )
        services.indexing.index(repository.repository_id)
        pipeline = AnswerPipeline(
            lookup=services.lookup, graph=services.graph, search=services.search
        )
        return pipeline.execute(
            AnswerRequest(
                repository_id=repository.repository_id,
                question=question,
                request_id="req_lexical_paths",
            )
        ).response


@pytest.fixture()
def order_route(tmp_path: Path) -> Iterator[QueryResponse]:
    """q027's question, verbatim from the corpus."""
    yield _answer(MIXED, tmp_path, "What order route is documented?")


def _steps(response: QueryResponse) -> list[str]:
    return [
        f"{step.source} {step.kind} {step.target}"
        for path in response.relation_paths
        for step in path.steps
    ]


def test_a_lexical_answer_emits_the_edge_the_corpus_declares(
    order_route: QueryResponse,
) -> None:
    """q027: `Order flow DOCUMENTS get_order` is stored, resolved, and was lost."""
    assert "Order flow DOCUMENTS get_order" in _steps(order_route)


def test_an_unresolved_edge_is_never_emitted(order_route: QueryResponse) -> None:
    """`Order flow` has ten outgoing edges and only two resolve.

    The other eight point at ordinary prose words -- "order", "flow",
    "requests", "orders", "frontend", "status", "backend", "returns" -- which
    name no symbol. Emitting them would turn a wording coincidence into an
    apparent relationship, and none of them can form a path because they have
    no far endpoint.
    """
    unresolved_hints = {
        "order",
        "flow",
        "requests",
        "orders",
        "frontend",
        "status",
        "backend",
        "returns",
    }
    targets = {
        step.target for path in order_route.relation_paths for step in path.steps
    }
    assert targets
    assert not targets & unresolved_hints
    assert {"get_order", "loadOrder"} <= targets


def test_a_step_cites_evidence_the_answer_already_returned(
    order_route: QueryResponse,
) -> None:
    """No new evidence row, so `containing_evidence_rate` cannot move.

    A step reuses the returned chunk whose range *contains* the edge's
    reference site. A step that finds no such chunk is withheld rather than
    shown with a gap, which is the rule `GraphQueryService._paths` already
    applies.
    """
    returned = {item.evidence_id for item in order_route.evidence}
    cited = {
        step.evidence_id for path in order_route.relation_paths for step in path.steps
    }
    assert cited
    assert cited <= returned


def test_emitting_a_path_does_not_upgrade_the_lexical_claims(
    order_route: QueryResponse,
) -> None:
    """A lexical match is evidence of wording, and stays labelled as such."""
    assert order_route.answer.claims
    assert all(
        claim.derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC
        for claim in order_route.answer.claims
    )


def test_a_step_keeps_the_stored_edge_derivation(
    order_route: QueryResponse,
) -> None:
    """The path carries the *edge's* derivation, not the lexical hit's.

    They are separate fields answering separate questions, and letting the
    lexical confidence overwrite a resolved edge's would hide the fact that the
    edge was resolved rather than guessed.
    """
    step = next(
        step
        for path in order_route.relation_paths
        for step in path.steps
        if step.target == "get_order"
    )
    assert step.derivation is not Derivation.HIGH_CONFIDENCE_HEURISTIC
    assert step.confidence > 0.0


def test_containment_is_directional_and_inclusive() -> None:
    """`_containing` decides which returned chunk a step may cite.

    Tested directly because the branch that *rejects* an edge -- the one
    guarding against a step citing a chunk that does not cover its reference
    site -- is not reachable from the corpus fixtures, where every edge falls
    inside a returned chunk. A mutation of the surrounding `if` therefore looks
    green whatever it says, so the rule it depends on is pinned here instead.
    See the Deferred Register entry recording the unexercised branch.
    """
    cited = [("file_a", 10, 20, "ev_1"), ("file_b", 1, 5, "ev_2")]

    assert _containing(cited, "file_a", 10) == "ev_1"  # inclusive lower bound
    assert _containing(cited, "file_a", 20) == "ev_1"  # inclusive upper bound
    assert _containing(cited, "file_a", 15) == "ev_1"
    assert _containing(cited, "file_b", 3) == "ev_2"
    # Right line, wrong file: a range must not reach across files.
    assert _containing(cited, "file_b", 15) is None
    # Outside every returned range -- the case the fixtures cannot produce.
    assert _containing(cited, "file_a", 9) is None
    assert _containing(cited, "file_a", 21) is None
    assert _containing([], "file_a", 10) is None


def test_a_config_lookup_emits_its_reference(tmp_path: Path) -> None:
    """q029: `healthPath REFERENCES health`, its only outgoing edge."""
    response = _answer(MIXED, tmp_path, "Where is the frontend health path?")
    assert "healthPath REFERENCES health" in _steps(response)


def test_a_conceptual_lookup_emits_its_document_edge(tmp_path: Path) -> None:
    """q024: `Sample Service DOCUMENTS service.port`, one resolved of six."""
    response = _answer(DOCS_CONFIG, tmp_path, "Where is the service port described?")
    assert "Sample Service DOCUMENTS service.port" in _steps(response)
