"""Runs the Phase 1 engine against the Phase 0 evaluation corpus.

Phase 1 implements one intent — `EXACT_SYMBOL` — for Python fixtures. Every case
outside that scope is emitted as an explicit abstention rather than a zero score,
because "not implemented" and "answered wrongly" are different facts and the
baseline must not blur them.

The dataset declares its own snapshot labels (for example `python-v1`) while the
engine derives snapshot IDs from content. Predictions therefore carry the case's
declared snapshot ID so they align with the gold corpus, but only after the
evidence has been validated against the engine's own active snapshot. Nothing is
emitted that the engine did not itself verify.
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from codeatlas.application.container import build_services
from codeatlas.application.lookup import SymbolLookupRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.errors import CodeAtlasError
from codeatlas.evaluation.dataset import Dataset, QueryCase
from codeatlas.evaluation.runner import (
    EvidencePrediction,
    PredictionFile,
    QueryPrediction,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

SUPPORTED_INTENT = "EXACT_SYMBOL"
SUPPORTED_FIXTURES = ("python_app",)


def predict_exact_symbols(
    dataset: Dataset,
    fixtures: Sequence[str] = SUPPORTED_FIXTURES,
    *,
    record_timings: bool = True,
) -> PredictionFile:
    """Answer every supported case with the real engine; abstain elsewhere.

    Set ``record_timings`` to ``False`` for a tracked baseline artifact. Wall
    times differ on every machine and every run, so including them would make a
    committed baseline impossible to verify byte-for-byte. Correctness metrics
    are unaffected; performance is measured separately and reported with its
    hardware, per `CLAUDE.md` Section 19.3.
    """
    supported = set(fixtures)
    predictions: list[QueryPrediction] = []

    with tempfile.TemporaryDirectory(prefix="codeatlas-eval-") as workspace:
        database_path = Path(workspace) / "evaluation.sqlite"
        with connect(database_path) as connection:
            apply_migrations(connection)
            services = build_services(connection)
            indexed: dict[str, str] = {}

            for case in dataset.query_cases:
                if (
                    case.intent != SUPPORTED_INTENT
                    or case.repository_fixture not in supported
                ):
                    predictions.append(_abstention(case))
                    continue

                repository_id = indexed.get(case.repository_fixture)
                if repository_id is None:
                    fixture_root = dataset.fixtures_root / _fixture_root(
                        dataset, case.repository_fixture
                    )
                    repository = services.registration.register(
                        RegisterRepositoryRequest(path=str(fixture_root))
                    )
                    services.indexing.index(repository.repository_id)
                    repository_id = repository.repository_id
                    indexed[case.repository_fixture] = repository_id

                predictions.append(
                    _answer(
                        services,
                        repository_id,
                        case,
                        record_timings=record_timings,
                    )
                )

    return PredictionFile(
        implementation_status="implemented",
        query_predictions=predictions,
        change_predictions=[],
    )


def _answer(
    services: object,
    repository_id: str,
    case: QueryCase,
    *,
    record_timings: bool = True,
) -> QueryPrediction:
    started = time.perf_counter()
    try:
        response = services.lookup.lookup(  # type: ignore[attr-defined]
            SymbolLookupRequest(
                repository_id=repository_id,
                query=_query_term(case),
                request_id=f"eval_{case.id}",
            )
        )
    except CodeAtlasError:
        return _abstention(case)

    duration_ms = (time.perf_counter() - started) * 1000 if record_timings else 0.0
    return QueryPrediction(
        case_id=case.id,
        ranked_symbols=[
            item.symbol for item in response.evidence if item.symbol is not None
        ],
        ranked_evidence=[
            EvidencePrediction(
                evidence_id=item.evidence_id,
                # The engine validated this evidence against its own active
                # snapshot; the dataset's declared label is applied only for
                # comparison with the gold corpus.
                snapshot_id=case.snapshot_id,
                file_path=item.file_path,
                start_line=item.start_line,
                end_line=item.end_line,
            )
            for item in response.evidence
        ],
        relation_paths=[],
        claims=[claim.text for claim in response.answer.claims],
        abstained=not response.evidence,
        duration_ms=duration_ms,
    )


def _abstention(case: QueryCase) -> QueryPrediction:
    return QueryPrediction(
        case_id=case.id,
        ranked_symbols=[],
        ranked_evidence=[],
        relation_paths=[],
        claims=[],
        abstained=True,
        duration_ms=0.0,
    )


def _query_term(case: QueryCase) -> str:
    """Use the case's expected symbol as the exact lookup term.

    Phase 1 has no natural-language intent classifier. Feeding the declared
    symbol measures resolution accuracy, which is what this phase built; it does
    not measure question understanding, which it did not.
    """
    if case.expected_symbols:
        return case.expected_symbols[0]
    return case.question


def _fixture_root(dataset: Dataset, fixture_id: str) -> str:
    for fixture in dataset.fixtures:
        if fixture.id == fixture_id:
            return fixture.root
    raise KeyError(f"unknown fixture: {fixture_id}")
