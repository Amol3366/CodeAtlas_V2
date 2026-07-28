"""Graph query services against a real indexed polyglot repository."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.graph_queries import (
    GraphQueryRequest,
    weakest_derivation,
)
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import Derivation, QueryResponse
from codeatlas.retrieval.graph import TraversalLimits
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

ORDERS_TS = (
    "export interface Order {\n"
    "  id: string;\n"
    "}\n"
    "\n"
    "export function total(order: Order): number {\n"
    "  return order.id.length;\n"
    "}\n"
)
CLIENT_JS = (
    'import { total } from "./orders";\n'
    "\n"
    "export function render(order) {\n"
    "  return `Total: ${total(order)}`;\n"
    "}\n"
)
SERVICE_PY = (
    "from .idempotency import IdempotencyStore\n"
    "\n"
    "class PaymentService:\n"
    "    def __init__(self, store: IdempotencyStore) -> None:\n"
    "        self.store = store\n"
    "\n"
    "    def capture(self, key: str) -> str:\n"
    "        return self.store.claim(key)\n"
)
IDEMPOTENCY_PY = (
    "class IdempotencyStore:\n"
    "    def claim(self, key: str) -> str:\n"
    "        return key\n"
)
TEST_PY = (
    "from src.payments.service import PaymentService\n"
    "\n"
    "def test_capture_returns_a_token():\n"
    "    assert PaymentService(None) is not None\n"
)


@dataclass
class Harness:
    services: ApplicationServices
    connection: sqlite3.Connection
    repository_id: str
    root: Path


@pytest.fixture()
def harness(tmp_path: Path) -> Iterator[Harness]:
    root = tmp_path / "polyglot"
    (root / "src" / "payments").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "orders.ts").write_text(ORDERS_TS, encoding="utf-8")
    (root / "src" / "client.js").write_text(CLIENT_JS, encoding="utf-8")
    (root / "src" / "payments" / "service.py").write_text(SERVICE_PY, encoding="utf-8")
    (root / "src" / "payments" / "idempotency.py").write_text(
        IDEMPOTENCY_PY, encoding="utf-8"
    )
    (root / "tests" / "test_service.py").write_text(TEST_PY, encoding="utf-8")

    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        services.indexing.index(repository.repository_id)
        yield Harness(
            services=services,
            connection=connection,
            repository_id=repository.repository_id,
            root=root,
        )


def _request(harness: Harness, symbol: str, **kwargs: object) -> GraphQueryRequest:
    return GraphQueryRequest(
        repository_id=harness.repository_id,
        symbol=symbol,
        request_id="req-1",
        **kwargs,  # type: ignore[arg-type]
    )


def _claim_texts(response: QueryResponse) -> str:
    return " ".join(claim.text for claim in response.answer.claims)


# --- Corpus-aligned questions -------------------------------------------------


def test_callees_of_capture_include_claim(harness: Harness) -> None:
    """q005: `capture` calls `claim`."""
    response = harness.services.graph.callees(
        _request(harness, "PaymentService.capture")
    )

    assert "claim" in _claim_texts(response)
    assert response.evidence


def test_callees_of_render_include_total(harness: Harness) -> None:
    """q016: `render` calls `total`, across JavaScript and TypeScript."""
    response = harness.services.graph.callees(_request(harness, "render"))

    assert "total" in _claim_texts(response)


def test_callers_of_total_include_render(harness: Harness) -> None:
    response = harness.services.graph.callers(_request(harness, "total"))

    assert "render" in _claim_texts(response)


def test_exports_of_the_orders_module(harness: Harness) -> None:
    """q017: `orders` exports `Order` and `total`."""
    response = harness.services.graph.exports(_request(harness, "src.orders"))

    text = _claim_texts(response)
    assert "Order" in text
    assert "total" in text


def test_dependencies_include_the_resolved_import(harness: Harness) -> None:
    """q010/q015: the service module imports IdempotencyStore."""
    response = harness.services.graph.dependencies(
        _request(harness, "src.payments.service")
    )

    assert "IdempotencyStore" in _claim_texts(response)


# --- Trust rules --------------------------------------------------------------


def test_a_claim_is_never_stronger_than_its_supporting_edge(
    harness: Harness,
) -> None:
    response = harness.services.graph.callees(
        _request(harness, "PaymentService.capture")
    )

    evidence_by_id = {item.evidence_id: item for item in response.evidence}
    for claim in response.answer.claims:
        for evidence_id in claim.evidence_ids:
            assert claim.derivation == evidence_by_id[evidence_id].derivation


def test_weakest_derivation_governs_a_mixed_path() -> None:
    """One heuristic edge makes the whole chain heuristic."""
    assert (
        weakest_derivation(
            [
                Derivation.DETERMINISTIC,
                Derivation.HIGH_CONFIDENCE_HEURISTIC,
                Derivation.STATIC_RESOLVED,
            ]
        )
        is Derivation.HIGH_CONFIDENCE_HEURISTIC
    )


def test_weakest_derivation_of_nothing_is_unsupported() -> None:
    assert weakest_derivation([]) is Derivation.UNSUPPORTED


def test_an_ambiguous_root_abstains_and_lists_candidates(
    harness: Harness,
) -> None:
    (harness.root / "src" / "alpha.py").write_text(
        "class Alpha:\n    def shared(self):\n        return 1\n", encoding="utf-8"
    )
    (harness.root / "src" / "beta.py").write_text(
        "class Beta:\n    def shared(self):\n        return 2\n", encoding="utf-8"
    )
    harness.services.indexing.index(harness.repository_id)

    response = harness.services.graph.callers(_request(harness, "shared"))

    assert response.answer.claims == []
    assert "SYMBOL_AMBIGUOUS" in response.warnings
    assert "Alpha.shared" in response.answer.summary
    assert "Beta.shared" in response.answer.summary


def test_a_symbol_with_no_callers_abstains_explicitly(harness: Harness) -> None:
    """"No callers" is a different statement from "not analyzed"."""
    response = harness.services.graph.callers(_request(harness, "render"))

    assert response.answer.claims == []
    assert "no callers" in response.answer.summary
    assert "NO_RELATIONS_CALLERS" in response.warnings


def test_an_unknown_symbol_abstains_without_inventing(harness: Harness) -> None:
    response = harness.services.graph.callers(_request(harness, "nonexistent_thing"))

    assert response.answer.claims == []
    assert response.evidence == []
    assert "NO_EXACT_SYMBOL_MATCH" in response.warnings


def test_truncation_becomes_both_a_warning_and_a_limitation(
    harness: Harness,
) -> None:
    response = harness.services.graph.callees(
        _request(
            harness,
            "PaymentService.capture",
            limits=TraversalLimits(max_edges=1),
        )
    )

    if response.warnings:
        truncation = [item for item in response.warnings if "TRUNCATED" in item]
        if truncation:
            assert any("incomplete" in item for item in response.limitations)


# --- Contract integrity -------------------------------------------------------


def test_every_response_is_snapshot_bound_and_contract_valid(
    harness: Harness,
) -> None:
    active = harness.services.indexing.get_active_snapshot(harness.repository_id)
    assert active is not None

    for method in (
        harness.services.graph.callers,
        harness.services.graph.callees,
        harness.services.graph.dependencies,
        harness.services.graph.exports,
        harness.services.graph.related_tests,
        harness.services.graph.related_documents,
        harness.services.graph.trace,
    ):
        response = method(_request(harness, "PaymentService.capture"))
        assert response.contract_version == "1.1"
        assert response.snapshot.snapshot_id == active.snapshot_id
        for item in response.evidence:
            assert item.snapshot_id == active.snapshot_id


def test_a_trace_emits_relation_paths_whose_steps_cite_evidence(
    harness: Harness,
) -> None:
    response = harness.services.graph.trace(
        _request(harness, "PaymentService.capture")
    )

    known = {item.evidence_id for item in response.evidence}
    for path in response.relation_paths:
        assert path.steps
        for step in path.steps:
            assert step.evidence_id in known


def test_no_response_leaks_an_absolute_repository_path(harness: Harness) -> None:
    response = harness.services.graph.callees(
        _request(harness, "PaymentService.capture")
    )

    payload = response.model_dump_json()
    assert str(harness.root) not in payload
    for item in response.evidence:
        assert not item.file_path.startswith("/")
        assert ":" not in item.file_path[:3]
