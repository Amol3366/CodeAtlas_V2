"""A flow answer follows routes, and says so when it cannot build a path.

`trace` traversed `CALLS`, `MAY_CALL` and `IMPORTS` only. `ROUTES_TO` — the
relation that exists specifically to model an HTTP boundary, added in P4-05 —
was absent, so a flow question could never cross from a frontend caller to the
backend handler it invokes. That is the cross-language capability the
`mixed_app` fixture was built to demonstrate, and two corpus cases (q026, q032)
declare exactly that edge.

The second defect is quieter. `loadOrder` also calls `fetch` and `json`, which
are browser globals and resolve to nothing. A path needs resolved endpoints, so
none could be built — yet the response reported "loadOrder has 2 flow",
rendered two claims, and returned an **empty** `relation_paths` with **no
warning**. A client reading the structured field saw nothing and was told
nothing, which is the gap ADR-0020 set out to close.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.graph_queries import GraphQueryRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

FIXTURE = Path("tests/evaluation/cases/fixtures/mixed_app")


@pytest.fixture()
def services(tmp_path: Path):  # type: ignore[no-untyped-def]
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        built = build_services(connection)
        repository = built.registration.register(
            RegisterRepositoryRequest(path=str(FIXTURE.resolve()))
        )
        built.indexing.index(repository.repository_id)
        yield built, repository.repository_id


def _trace(services, symbol: str):  # type: ignore[no-untyped-def]
    built, repository_id = services
    return built.graph.trace(
        GraphQueryRequest(
            repository_id=repository_id, symbol=symbol, request_id="req_1"
        )
    )


def test_a_flow_follows_a_route_across_the_http_boundary(services) -> None:  # type: ignore[no-untyped-def]
    """The capability the fixture exists to demonstrate."""
    response = _trace(services, "loadOrder")

    steps = [
        f"{step.source} {step.kind} {step.target}"
        for path in response.relation_paths
        for step in path.steps
    ]

    assert "loadOrder ROUTES_TO get_order" in steps


def test_an_answer_with_edges_but_no_path_says_so(services) -> None:  # type: ignore[no-untyped-def]
    """Silence is the defect, not the empty list.

    `loadOrder` calls `fetch` and `json`, which resolve to nothing, so those
    edges legitimately produce no path. Reporting claims about them while
    returning an empty structured field and no warning tells a machine reader
    nothing at all — Section 4.1 requires saying what CodeAtlas does not know.
    """
    response = _trace(services, "loadOrder")

    unresolved = [
        claim
        for claim in response.answer.claims
        if "fetch" in claim.text or "json" in claim.text
    ]
    assert unresolved, "the fixture no longer exercises unresolved targets"
    assert "RELATION_PATH_UNRESOLVED" in response.warnings


def test_a_subject_with_no_relations_still_warns(services) -> None:  # type: ignore[no-untyped-def]
    """The existing behaviour, pinned so the new warning does not replace it.

    A subject with no edges at all reports NO_RELATIONS_FLOW. That is a
    different statement from "edges exist but none could be pathed", and
    collapsing the two would lose the distinction.
    """
    response = _trace(services, "Order flow")

    assert not response.relation_paths
    assert "NO_RELATIONS_FLOW" in response.warnings
    assert "RELATION_PATH_UNRESOLVED" not in response.warnings


def test_a_fully_resolved_flow_warns_about_nothing(services) -> None:  # type: ignore[no-untyped-def]
    """The guard against warning on every answer.

    Without this, emitting the warning unconditionally would pass the test
    above while making it meaningless.
    """
    response = _trace(services, "get_order")

    assert "RELATION_PATH_UNRESOLVED" not in response.warnings


# --- ADR-0055: a route cites the handler it reaches ---------------------------


def test_a_route_cites_the_handler_it_reaches(services) -> None:  # type: ignore[no-untyped-def]
    """The far end, which the reference site alone cannot show.

    A route literal sits in the caller's file and names a handler in another
    language's. ADR-0034 added `ROUTES_TO` to `trace` precisely to cross that
    boundary, so citing only the near side answers half the question.
    """
    response = _trace(services, "loadOrder")

    cited = {
        (item.file_path, item.symbol, item.start_line, item.end_line)
        for item in response.evidence
    }
    assert ("backend.py", "get_order", 1, 2) in cited, cited


def test_the_route_claim_survives_a_line_it_shares(services) -> None:  # type: ignore[no-untyped-def]
    """The defect this uncovered, and it was silent.

    `loadOrder ROUTES_TO get_order` and `loadOrder CALLS fetch` both sit on
    `frontend.ts:2`. Evidence is deduplicated by region — correctly, since one
    region is one citation — but claims were built from the surviving pairs, so
    the second edge at that line lost its claim entirely. The engine dropped its
    only *resolved*, cross-language edge and kept two unresolved browser
    globals, decided purely by iteration order. `relation_paths` carried it and
    the prose did not.
    """
    response = _trace(services, "loadOrder")

    texts = [claim.text for claim in response.answer.claims]
    routes = [text for text in texts if "get_order" in text]
    assert len(routes) == 1, texts
    # And it must read as a route, not fall through to the generic verb.
    assert "routes to" in routes[0], routes[0]


def test_a_route_states_its_assertion_once(services) -> None:  # type: ignore[no-untyped-def]
    """Two citations, one claim.

    **This does not currently exercise the merge, and the reason is recorded
    rather than papered over.** A route literal and the call carrying it are the
    same expression, so they share a line; the route's near-side candidate is
    therefore deduplicated away and only one citation survives. Deleting the
    merge in `_claims` leaves this test green.

    It is kept because the merge is not dead — it fires whenever the near side
    *does* survive, which needs a fixture whose route literal sits alone on its
    line. Recorded in the register as a stated limit of what this file measures,
    not as coverage it has.
    """
    response = _trace(services, "loadOrder")

    texts = [claim.text for claim in response.answer.claims]
    assert len(texts) == len(set(texts)), texts


def test_the_carve_out_does_not_reach_a_resolved_plain_call(tmp_path: Path) -> None:
    """The carve-out is for routes only, checked where it could actually break.

    `mixed_app` cannot show this: every non-route edge in it targets a browser
    global and resolves to nothing, so widening the destination citation to
    every kind is a no-op there and the guard looked green while proving
    nothing. `python_app` has a resolved `CALLS`, which is the case that would
    gain a second citation if the carve-out leaked.
    """
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        built = build_services(connection)
        repository = built.registration.register(
            RegisterRepositoryRequest(
                path=str(Path("tests/evaluation/cases/fixtures/python_app").resolve())
            )
        )
        built.indexing.index(repository.repository_id)
        response = built.graph.trace(
            GraphQueryRequest(
                repository_id=repository.repository_id,
                symbol="PaymentService.capture",
                request_id="req_2",
            )
        )

    resolved = [
        claim
        for claim in response.answer.claims
        if "IdempotencyStore.claim" in claim.text
    ]
    assert resolved, [claim.text for claim in response.answer.claims]
    for claim in resolved:
        assert len(claim.evidence_ids) == 1, claim.text
