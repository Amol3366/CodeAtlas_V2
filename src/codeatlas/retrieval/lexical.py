"""Lexical and exact search over an active snapshot.

Lexical search finds *text*, not verified meaning. That difference is the whole
reason the contract separates derivation from confidence, and it is why every
lexical result is labeled `high_confidence_heuristic`: the bytes really are at
those lines, but the decision that those lines answer the question was made by a
ranking function, not by resolution.

Exact resolution therefore always runs first for symbol queries, and an exact
match is never displaced by a lexical one. A user who asks for `capture` and gets
a fuzzy neighbor instead of the definition has been given a worse answer by a
system that had the better one available.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from codeatlas.application.evidence import (
    EvidenceBuilder,
    EvidenceCandidate,
    EvidenceOutcome,
    snapshot_reference,
)
from codeatlas.contracts import Answer, Claim, Derivation, Evidence, QueryResponse
from codeatlas.domain.errors import RepositoryNotFoundError, SnapshotNotReadyError
from codeatlas.domain.repository import Repository
from codeatlas.domain.search import ChunkSearchHit
from codeatlas.domain.snapshot import Snapshot
from codeatlas.retrieval.fts_query import (
    build_match_expression,
    build_relaxed_match_expression,
)
from codeatlas.storage.sqlite.stores import (
    EvidenceStore,
    FileStore,
    RepositoryStore,
    SearchStore,
    SnapshotStore,
    SymbolStore,
)

MAX_SEARCH_RESULTS = 25

LEXICAL_CONFIDENCE = 0.7
EXACT_CLAIM_CONFIDENCE = 0.99

PHASE_LIMITATION = (
    "Lexical search matches text in the active snapshot; it does not resolve"
    " relations, and a match is evidence of wording rather than of behavior."
)


@dataclass(frozen=True)
class SearchRequest:
    """A bounded search over one repository's active snapshot."""

    repository_id: str
    query: str
    request_id: str
    limit: int = MAX_SEARCH_RESULTS


class LexicalSearchService:
    """Text, path, and symbol search returning contract-valid responses."""

    def __init__(
        self,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        files: FileStore,
        symbols: SymbolStore,
        search: SearchStore,
        evidence: EvidenceStore | None = None,
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots
        self._symbols = symbols
        self._search = search
        self._evidence = EvidenceBuilder(files, evidence)
        self._files = files

    def search_text(self, request: SearchRequest) -> QueryResponse:
        """Find chunks whose retrieval text matches the query.

        Two passes, and the order is the design. The strict pass ANDs every
        term, which is what makes a targeted lookup precise. Only when it
        matches *nothing* is the query re-read broadly, with function words
        dropped and the remainder ORed — the reading a typed sentence needs,
        since no chunk contains all twelve words of a question.

        Because the second pass runs only after the first returned nothing, a
        query that finds results today finds exactly the same results after
        this change. That is what let the fallback land without moving a single
        committed baseline, and it is the property to preserve if this is ever
        reworked.
        """
        repository, snapshot, expression, limit = self._prepare(request)
        started = time.perf_counter()
        hits = self._search.search_chunks(snapshot.snapshot_id, expression, limit)
        relaxed = False
        if not hits:
            broadened = build_relaxed_match_expression(request.query)
            if broadened is not None and broadened != expression:
                hits = self._search.search_chunks(
                    snapshot.snapshot_id, broadened, limit
                )
                relaxed = bool(hits)
        elapsed = (time.perf_counter() - started) * 1000
        return self._from_chunk_hits(
            request, repository, snapshot, hits, elapsed, relaxed=relaxed
        )

    def response_without_evidence(
        self,
        request: SearchRequest,
        *,
        summary: str,
        warnings: Sequence[str] = (),
        limitations: Sequence[str] = (),
        timing_ms: dict[str, float] | None = None,
    ) -> QueryResponse:
        """Return a snapshot-bound conversational answer without searching.

        Chat-level turns such as greetings still need the active snapshot in
        their run record, but they should not be treated as repository lookup
        requests. This keeps that response contract-valid without inventing an
        evidence row or running a lexical query that the user did not ask for.
        """
        repository = self._repositories.get(request.repository_id)
        if repository is None:
            raise RepositoryNotFoundError("The repository is not registered.")

        snapshot = self._snapshots.get_active(request.repository_id)
        if snapshot is None:
            raise SnapshotNotReadyError(
                "The repository has no active snapshot. Index it first."
            )

        return QueryResponse(
            request_id=request.request_id,
            repository_id=request.repository_id,
            snapshot=snapshot_reference(snapshot, stale=False),
            answer=Answer(summary=summary, claims=[]),
            evidence=[],
            warnings=list(warnings),
            limitations=list(limitations),
            timing_ms={} if timing_ms is None else timing_ms,
        )

    def search_symbols(self, request: SearchRequest) -> QueryResponse:
        """Resolve a symbol exactly, falling back to lexical name matching."""
        repository, snapshot, expression, limit = self._prepare(request)

        started = time.perf_counter()
        exact = self._symbols.find_exact(
            snapshot.snapshot_id, request.query.strip(), limit
        )
        if exact:
            outcome = self._evidence.build(
                repository_root=Path(repository.canonical_root),
                snapshot=snapshot,
                candidates=[
                    EvidenceCandidate(
                        file_id=symbol.file_id,
                        start_line=symbol.start_line,
                        end_line=symbol.end_line,
                        symbol=symbol.qualified_name,
                        derivation=Derivation.DETERMINISTIC,
                        confidence=1.0,
                    )
                    for symbol in exact
                ],
            )
            elapsed = (time.perf_counter() - started) * 1000
            if outcome.items:
                claims = [
                    Claim(
                        claim_id=f"c{position + 1}",
                        text=(
                            f"{exact[index].qualified_name} is defined in"
                            f" {item.file_path} lines"
                            f" {item.start_line}-{item.end_line}."
                        ),
                        derivation=Derivation.STATIC_RESOLVED,
                        confidence=EXACT_CLAIM_CONFIDENCE,
                        evidence_ids=[item.evidence_id],
                    )
                    for position, (index, item) in enumerate(outcome.items)
                ]
                return self._respond(
                    request=request,
                    snapshot=snapshot,
                    summary=_exact_summary(request.query, outcome.evidence),
                    claims=claims,
                    outcome=outcome,
                    elapsed=elapsed,
                )

        # Only now, with no exact resolution available, does text matching run.
        hits = self._search.search_chunks(
            snapshot.snapshot_id, expression, limit, column="symbol_name"
        )
        elapsed = (time.perf_counter() - started) * 1000
        return self._from_chunk_hits(request, repository, snapshot, hits, elapsed)

    def search_files(self, request: SearchRequest) -> QueryResponse:
        """Find files whose path matches the query."""
        repository, snapshot, expression, limit = self._prepare(request)
        started = time.perf_counter()
        hits = self._search.search_files(snapshot.snapshot_id, expression, limit)
        elapsed = (time.perf_counter() - started) * 1000

        candidates: list[EvidenceCandidate] = []
        for hit in hits:
            record = self._files.get(snapshot.snapshot_id, hit.file_id)
            if record is None:
                continue
            candidates.append(
                EvidenceCandidate(
                    file_id=hit.file_id,
                    start_line=1,
                    end_line=max(record.line_count, 1),
                    symbol=None,
                    derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                    confidence=LEXICAL_CONFIDENCE,
                )
            )

        outcome = self._evidence.build(
            repository_root=Path(repository.canonical_root),
            snapshot=snapshot,
            candidates=candidates,
        )
        claims = [
            Claim(
                claim_id=f"c{position + 1}",
                text=f"{item.file_path} matches '{request.query}' by path.",
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                confidence=LEXICAL_CONFIDENCE,
                evidence_ids=[item.evidence_id],
            )
            for position, (_, item) in enumerate(outcome.items)
        ]
        return self._respond(
            request=request,
            snapshot=snapshot,
            summary=_lexical_summary(request.query, len(outcome.items), "files"),
            claims=claims,
            outcome=outcome,
            elapsed=elapsed,
        )

    def _prepare(self, request: SearchRequest) -> tuple[Repository, Snapshot, str, int]:
        repository = self._repositories.get(request.repository_id)
        if repository is None:
            raise RepositoryNotFoundError("The repository is not registered.")

        snapshot = self._snapshots.get_active(request.repository_id)
        if snapshot is None:
            raise SnapshotNotReadyError(
                "The repository has no active snapshot. Index it first."
            )

        expression = build_match_expression(request.query)
        limit = max(1, min(request.limit, MAX_SEARCH_RESULTS))
        return repository, snapshot, expression, limit

    def _from_chunk_hits(
        self,
        request: SearchRequest,
        repository: Repository,
        snapshot: Snapshot,
        hits: Sequence[ChunkSearchHit],
        elapsed: float,
        *,
        relaxed: bool = False,
    ) -> QueryResponse:
        outcome = self._evidence.build(
            repository_root=Path(repository.canonical_root),
            snapshot=snapshot,
            candidates=[
                EvidenceCandidate(
                    file_id=hit.file_id,
                    start_line=hit.start_line,
                    end_line=hit.end_line,
                    symbol=hit.qualified_name or None,
                    derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                    confidence=LEXICAL_CONFIDENCE,
                )
                for hit in hits
            ],
        )
        claims = [
            Claim(
                claim_id=f"c{position + 1}",
                text=(
                    f"{item.file_path} lines {item.start_line}-{item.end_line}"
                    f" contain text matching '{request.query}'."
                ),
                derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                confidence=LEXICAL_CONFIDENCE,
                evidence_ids=[item.evidence_id],
            )
            for position, (_, item) in enumerate(outcome.items)
        ]
        return self._respond(
            request=request,
            snapshot=snapshot,
            summary=_lexical_summary(request.query, len(outcome.items), "locations"),
            claims=claims,
            outcome=outcome,
            elapsed=elapsed,
            relaxed=relaxed,
        )

    def _respond(
        self,
        *,
        request: SearchRequest,
        snapshot: Snapshot,
        summary: str,
        claims: Sequence[Claim],
        outcome: EvidenceOutcome,
        elapsed: float,
        relaxed: bool = False,
    ) -> QueryResponse:
        warnings = list(outcome.warnings)
        if not outcome.items:
            warnings.append("NO_LEXICAL_MATCH")
        if relaxed:
            # The answer came from a broader reading than the user typed, so it
            # answers a slightly different question. Section 4.1: say so rather
            # than present it as an exact match.
            warnings.append("LEXICAL_QUERY_RELAXED")
        return QueryResponse(
            request_id=request.request_id,
            repository_id=request.repository_id,
            snapshot=snapshot_reference(snapshot, stale=outcome.stale),
            answer=Answer(summary=summary, claims=list(claims)),
            evidence=list(outcome.evidence),
            warnings=warnings,
            limitations=[PHASE_LIMITATION],
            timing_ms={"search": elapsed},
        )


def _exact_summary(query: str, evidence: Sequence[Evidence]) -> str:
    if len(evidence) == 1:
        item = evidence[0]
        return (
            f"{item.symbol} is defined in {item.file_path}"
            f" lines {item.start_line}-{item.end_line}."
        )
    return f"Found {len(evidence)} definitions matching '{query}'."


def _lexical_summary(query: str, count: int, noun: str) -> str:
    if count == 0:
        return f"CodeAtlas found no {noun} matching '{query}' in the active snapshot."
    return f"Found {count} {noun} matching '{query}' by text."
