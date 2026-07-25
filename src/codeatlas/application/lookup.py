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

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from codeatlas.contracts import (
    Answer,
    Claim,
    Derivation,
    Evidence,
    EvidenceValidation,
    QueryResponse,
    SnapshotFreshness,
    SnapshotReference,
)
from codeatlas.domain.errors import (
    InvalidRequestError,
    RepositoryNotFoundError,
    SnapshotNotReadyError,
)
from codeatlas.domain.ids import evidence_id as build_evidence_id
from codeatlas.domain.paths import resolve_inside_root
from codeatlas.domain.repository import FileRecord
from codeatlas.domain.snapshot import Snapshot
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.storage.sqlite.stores import (
    FileStore,
    RepositoryStore,
    SnapshotStore,
    SymbolStore,
)

MAX_QUERY_LENGTH: int = 512
MAX_RESULTS: int = 10
MAX_EXCERPT_LINES: int = 200
MAX_EXCERPT_CHARACTERS: int = 8000

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
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots
        self._files = files
        self._symbols = symbols

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
        built = self._build_evidence(
            repository_root=Path(repository.canonical_root),
            snapshot=snapshot,
            matches=matches,
        )
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
            for index, (symbol, evidence) in enumerate(built.pairs)
        ]

        return QueryResponse(
            request_id=request.request_id,
            repository_id=request.repository_id,
            snapshot=_snapshot_reference(snapshot, stale=built.stale),
            answer=Answer(summary=_summary(query, built.pairs), claims=claims),
            evidence=list(built.evidence),
            warnings=list(built.warnings),
            limitations=[PHASE_LIMITATION],
            timing_ms=timing,
        )

    def _build_evidence(
        self,
        *,
        repository_root: Path,
        snapshot: Snapshot,
        matches: tuple[SymbolRecord, ...],
    ) -> _EvidenceOutcome:
        pairs: list[tuple[SymbolRecord, Evidence]] = []
        warnings: list[str] = []
        stale = False

        for symbol in matches:
            record = self._files.get(snapshot.snapshot_id, symbol.file_id)
            if record is None:
                warnings.append("EVIDENCE_FILE_MISSING_FROM_SNAPSHOT")
                continue

            content = _read_file(repository_root, record)
            if content is None:
                if "EVIDENCE_FILE_UNREADABLE" not in warnings:
                    warnings.append("EVIDENCE_FILE_UNREADABLE")
                stale = True
                continue

            if hashlib.sha256(content).hexdigest() != record.content_hash:
                if "EVIDENCE_STALE_FILE_CONTENT" not in warnings:
                    warnings.append("EVIDENCE_STALE_FILE_CONTENT")
                stale = True
                continue

            excerpt, truncated = _excerpt(content, symbol.start_line, symbol.end_line)
            if truncated and "EVIDENCE_EXCERPT_TRUNCATED" not in warnings:
                warnings.append("EVIDENCE_EXCERPT_TRUNCATED")

            pairs.append(
                (
                    symbol,
                    Evidence(
                        evidence_id=build_evidence_id(
                            snapshot.snapshot_id,
                            symbol.file_id,
                            symbol.start_line,
                            symbol.end_line,
                        ),
                        repository_id=snapshot.repository_id,
                        snapshot_id=snapshot.snapshot_id,
                        file_path=record.relative_path,
                        symbol=symbol.qualified_name,
                        start_line=symbol.start_line,
                        end_line=symbol.end_line,
                        excerpt=excerpt,
                        content_hash=record.content_hash,
                        derivation=Derivation.DETERMINISTIC,
                        confidence=1.0,
                        validation=EvidenceValidation.VALID,
                    ),
                )
            )

        return _EvidenceOutcome(
            pairs=tuple(pairs),
            evidence=tuple(evidence for _, evidence in pairs),
            warnings=tuple(warnings),
            stale=stale,
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
            snapshot=_snapshot_reference(snapshot, stale=stale),
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


@dataclass(frozen=True)
class _EvidenceOutcome:
    pairs: tuple[tuple[SymbolRecord, Evidence], ...]
    evidence: tuple[Evidence, ...]
    warnings: tuple[str, ...]
    stale: bool


def _snapshot_reference(snapshot: Snapshot, *, stale: bool) -> SnapshotReference:
    return SnapshotReference(
        snapshot_id=snapshot.snapshot_id,
        git_head=snapshot.git_head,
        working_tree_fingerprint=snapshot.working_tree_fingerprint,
        freshness=SnapshotFreshness.STALE if stale else SnapshotFreshness.FRESH,
        semantic_coverage=0.0,
    )


def _summary(query: str, pairs: tuple[tuple[SymbolRecord, Evidence], ...]) -> str:
    if len(pairs) == 1:
        symbol, evidence = pairs[0]
        return (
            f"{symbol.qualified_name} is defined in {evidence.file_path}"
            f" lines {evidence.start_line}-{evidence.end_line}."
        )
    return f"Found {len(pairs)} definitions matching '{query}'."


def _read_file(repository_root: Path, record: FileRecord) -> bytes | None:
    try:
        return resolve_inside_root(repository_root, record.relative_path).read_bytes()
    except (OSError, ValueError):
        return None


def _excerpt(content: bytes, start_line: int, end_line: int) -> tuple[str, bool]:
    """Return a bounded excerpt for the definition and whether it was truncated."""
    # `utf-8-sig` strips a byte-order mark when present and behaves like `utf-8`
    # otherwise, which keeps excerpt line numbers aligned with the parser's.
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("utf-8", errors="replace")

    lines = text.splitlines()
    selected = lines[start_line - 1 : end_line]
    truncated = False

    if len(selected) > MAX_EXCERPT_LINES:
        selected = selected[:MAX_EXCERPT_LINES]
        truncated = True

    excerpt = "\n".join(selected)
    if len(excerpt) > MAX_EXCERPT_CHARACTERS:
        excerpt = excerpt[:MAX_EXCERPT_CHARACTERS]
        truncated = True
    return excerpt, truncated
