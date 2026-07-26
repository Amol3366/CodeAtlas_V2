"""Exact symbol lookup returning contract-valid, snapshot-bound evidence.

Two rules govern everything here.

**Never invent.** If nothing matches, the service abstains with an explicit
summary and no claims. It does not guess a path, a line, or a symbol.

**Never cite drifted content.** Evidence is read from disk at query time and the
file's current hash must equal the hash recorded in the active snapshot. When it
does not, the candidate is dropped, the response is marked stale, and the user is
told — a citation that no longer matches the file is worse than no citation.

`Evidence.derivation` is `deterministic`: that bytes exist at those lines in that
snapshot is a syntactic fact. `Claim.derivation` is `static_resolved`: the
identity of the symbol was resolved statically, and Python permits dynamic
redefinition that static analysis cannot see. The two fields stay separate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from codeatlas.application.evidence import (
    EvidenceBuilder,
    EvidenceCandidate,
    snapshot_reference,
)
from codeatlas.contracts import (
    Answer,
    Claim,
    Derivation,
    Evidence,
    QueryResponse,
)
from codeatlas.domain.errors import (
    InvalidRequestError,
    RepositoryNotFoundError,
    SnapshotNotReadyError,
)
from codeatlas.domain.snapshot import Snapshot
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.storage.sqlite.stores import (
    EvidenceStore,
    FileStore,
    RepositoryStore,
    SnapshotStore,
    SymbolStore,
)

MAX_QUERY_LENGTH: int = 512
MAX_RESULTS: int = 10

PHASE_LIMITATION = (
    "Phase 1 resolves Python definitions only; relations, other languages, and"
    " semantic retrieval are unavailable."
)


@dataclass(frozen=True)
class SymbolLookupRequest:
    """A bounded request for one exact symbol."""

    repository_id: str
    query: str
    request_id: str
    max_results: int = MAX_RESULTS


class ExactSymbolLookupService:
    """Resolves an exact symbol to verified file-and-line evidence."""

    def __init__(
        self,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        files: FileStore,
        symbols: SymbolStore,
        evidence: EvidenceStore | None = None,
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots
        self._symbols = symbols
        self._evidence = EvidenceBuilder(files, evidence)

    def lookup(self, request: SymbolLookupRequest) -> QueryResponse:
        """Resolve ``request.query`` or abstain."""
        query = request.query.strip()
        if not query or len(query) > MAX_QUERY_LENGTH:
            raise InvalidRequestError(
                "The query must be between 1 and"
                f" {MAX_QUERY_LENGTH} characters."
            )

        repository = self._repositories.get(request.repository_id)
        if repository is None:
            raise RepositoryNotFoundError("The repository is not registered.")

        snapshot = self._snapshots.get_active(request.repository_id)
        if snapshot is None:
            raise SnapshotNotReadyError(
                "The repository has no active snapshot. Index it first."
            )

        limit = max(1, min(request.max_results, MAX_RESULTS))
        lookup_started = time.perf_counter()
        matches = self._symbols.find_exact(snapshot.snapshot_id, query, limit)
        lookup_ms = (time.perf_counter() - lookup_started) * 1000

        evidence_started = time.perf_counter()
        built = self._evidence.build(
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
                for symbol in matches
            ],
        )
        pairs = tuple((matches[index], item) for index, item in built.items)
        evidence_ms = (time.perf_counter() - evidence_started) * 1000

        timing = {"lookup": lookup_ms, "evidence": evidence_ms}
        if not built.evidence:
            return self._abstain(
                request=request,
                snapshot=snapshot,
                query=query,
                warnings=built.warnings
                if matches
                else (*built.warnings, "NO_EXACT_SYMBOL_MATCH"),
                stale=built.stale,
                timing=timing,
            )

        claims = [
            Claim(
                claim_id=f"c{index + 1}",
                text=(
                    f"{symbol.qualified_name} is defined in"
                    f" {evidence.file_path} lines"
                    f" {evidence.start_line}-{evidence.end_line}."
                ),
                derivation=Derivation.STATIC_RESOLVED,
                confidence=0.99,
                evidence_ids=[evidence.evidence_id],
            )
            for index, (symbol, evidence) in enumerate(pairs)
        ]

        return QueryResponse(
            request_id=request.request_id,
            repository_id=request.repository_id,
            snapshot=snapshot_reference(snapshot, stale=built.stale),
            answer=Answer(summary=_summary(query, pairs), claims=claims),
            evidence=list(built.evidence),
            warnings=list(built.warnings),
            limitations=[PHASE_LIMITATION],
            timing_ms=timing,
        )

    def _abstain(
        self,
        *,
        request: SymbolLookupRequest,
        snapshot: Snapshot,
        query: str,
        warnings: tuple[str, ...],
        stale: bool,
        timing: dict[str, float],
    ) -> QueryResponse:
        return QueryResponse(
            request_id=request.request_id,
            repository_id=request.repository_id,
            snapshot=snapshot_reference(snapshot, stale=stale),
            answer=Answer(
                summary=(
                    f"CodeAtlas found no verifiable definition matching '{query}'"
                    " in the active snapshot."
                ),
                claims=[],
            ),
            evidence=[],
            warnings=list(warnings),
            limitations=[PHASE_LIMITATION],
            timing_ms=timing,
        )


def _summary(query: str, pairs: tuple[tuple[SymbolRecord, Evidence], ...]) -> str:
    if len(pairs) == 1:
        symbol, evidence = pairs[0]
        return (
            f"{symbol.qualified_name} is defined in {evidence.file_path}"
            f" lines {evidence.start_line}-{evidence.end_line}."
        )
    return f"Found {len(pairs)} definitions matching '{query}'."
