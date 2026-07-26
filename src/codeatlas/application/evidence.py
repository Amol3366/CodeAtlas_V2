"""Shared evidence construction.

Every service that cites the repository goes through here, so the rules that
make a citation trustworthy exist once rather than once per feature:

* evidence is read from **disk at query time**, never reconstructed from a
  stored copy;
* the file's current hash must equal the hash recorded in the snapshot — when it
  does not, the candidate is dropped, the response is marked stale, and the user
  is told;
* excerpts are bounded, and truncation is reported rather than hidden.

The caller decides what a range *means* by choosing its derivation and
confidence. This module only decides whether the range can honestly be shown.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from codeatlas.contracts import (
    Derivation,
    Evidence,
    EvidenceValidation,
    SnapshotFreshness,
    SnapshotReference,
)
from codeatlas.domain.ids import evidence_id as build_evidence_id
from codeatlas.domain.paths import resolve_inside_root
from codeatlas.domain.relations import StoredEvidence
from codeatlas.domain.repository import FileRecord
from codeatlas.domain.snapshot import Snapshot
from codeatlas.storage.sqlite.stores import EvidenceStore, FileStore

MAX_EXCERPT_LINES: int = 200
MAX_EXCERPT_CHARACTERS: int = 8000


@dataclass(frozen=True)
class EvidenceCandidate:
    """A range someone wants to cite, before it has been verified."""

    file_id: str
    start_line: int
    end_line: int
    symbol: str | None = None
    derivation: Derivation = Derivation.DETERMINISTIC
    confidence: float = 1.0


@dataclass(frozen=True)
class EvidenceOutcome:
    """Verified evidence, in candidate order, with what went wrong."""

    items: tuple[tuple[int, Evidence], ...]
    warnings: tuple[str, ...]
    stale: bool

    @property
    def evidence(self) -> tuple[Evidence, ...]:
        return tuple(item for _, item in self.items)


class EvidenceBuilder:
    """Verifies candidate ranges against the snapshot and the file on disk."""

    def __init__(
        self, files: FileStore, evidence: EvidenceStore | None = None
    ) -> None:
        self._files = files
        # Optional so every existing caller keeps working. When present, each
        # verified region's *address* is recorded so it can be fetched later by
        # ID. Only the location and hash are stored — never the excerpt — so a
        # stored row can never become a staler answer than the file itself.
        self._evidence = evidence

    def build(
        self,
        *,
        repository_root: Path,
        snapshot: Snapshot,
        candidates: Sequence[EvidenceCandidate],
    ) -> EvidenceOutcome:
        items: list[tuple[int, Evidence]] = []
        warnings: list[str] = []
        stale = False
        # An evidence ID names a citable *region*, so two candidates covering the
        # same lines of the same file are one piece of evidence, not two. A file
        # summary and its module chunk legitimately share a range; citing it
        # twice would both violate the contract and mislead a reader into
        # thinking two independent sources agreed.
        seen: set[tuple[str, int, int]] = set()

        for index, candidate in enumerate(candidates):
            region = (candidate.file_id, candidate.start_line, candidate.end_line)
            if region in seen:
                continue
            record = self._files.get(snapshot.snapshot_id, candidate.file_id)
            if record is None:
                _add(warnings, "EVIDENCE_FILE_MISSING_FROM_SNAPSHOT")
                continue

            content = _read_file(repository_root, record)
            if content is None:
                _add(warnings, "EVIDENCE_FILE_UNREADABLE")
                stale = True
                continue

            if hashlib.sha256(content).hexdigest() != record.content_hash:
                _add(warnings, "EVIDENCE_STALE_FILE_CONTENT")
                stale = True
                continue

            excerpt, truncated = build_excerpt(
                content, candidate.start_line, candidate.end_line
            )
            if truncated:
                _add(warnings, "EVIDENCE_EXCERPT_TRUNCATED")

            seen.add(region)
            items.append(
                (
                    index,
                    Evidence(
                        evidence_id=build_evidence_id(
                            snapshot.snapshot_id,
                            candidate.file_id,
                            candidate.start_line,
                            candidate.end_line,
                        ),
                        repository_id=snapshot.repository_id,
                        snapshot_id=snapshot.snapshot_id,
                        file_path=record.relative_path,
                        symbol=candidate.symbol,
                        start_line=candidate.start_line,
                        end_line=candidate.end_line,
                        excerpt=excerpt,
                        content_hash=record.content_hash,
                        derivation=candidate.derivation,
                        confidence=candidate.confidence,
                        validation=EvidenceValidation.VALID,
                    ),
                )
            )

        if self._evidence is not None and items:
            self._evidence.upsert_many(
                snapshot.snapshot_id,
                [
                    StoredEvidence(
                        evidence_id=item.evidence_id,
                        file_id=candidates[index].file_id,
                        start_line=item.start_line,
                        end_line=item.end_line,
                        content_hash=item.content_hash,
                        derivation=item.derivation,
                    )
                    for index, item in items
                ],
            )

        return EvidenceOutcome(
            items=tuple(items), warnings=tuple(warnings), stale=stale
        )


def snapshot_reference(snapshot: Snapshot, *, stale: bool) -> SnapshotReference:
    return SnapshotReference(
        snapshot_id=snapshot.snapshot_id,
        git_head=snapshot.git_head,
        working_tree_fingerprint=snapshot.working_tree_fingerprint,
        freshness=SnapshotFreshness.STALE if stale else SnapshotFreshness.FRESH,
        semantic_coverage=0.0,
    )


def build_excerpt(content: bytes, start_line: int, end_line: int) -> tuple[str, bool]:
    """Return a bounded excerpt for the range and whether it was truncated."""
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


def _read_file(repository_root: Path, record: FileRecord) -> bytes | None:
    try:
        return resolve_inside_root(repository_root, record.relative_path).read_bytes()
    except (OSError, ValueError):
        return None


def _add(warnings: list[str], code: str) -> None:
    if code not in warnings:
        warnings.append(code)
