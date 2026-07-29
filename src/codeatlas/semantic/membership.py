"""Snapshot membership decides what a vector search is allowed to return.

This module is gate condition 4, and blueprint 8.20's rule in one place:

    old vector physically present != old vector eligible for retrieval

A vector store is append-friendly; a repository is not. Content is deleted,
symbols renamed, branches switched, snapshots superseded. If eligibility
depended on the vector store forgetting things promptly, each of those would be
a race — and losing the race means citing code that no longer exists, which is
the single failure the evidence contract exists to prevent.

So eligibility never depends on it. The vector store may hold anything; SQLite
decides what is current, and it decides by joining on content hash within one
snapshot.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from codeatlas.semantic.vector_store import VectorMatch

_MAX_PARAMETERS = 500


@dataclass(frozen=True)
class SemanticCandidate:
    """A vector hit resolved to a chunk that is really in the snapshot.

    Carries the file and lines because a candidate has to become citable
    evidence, and returning bare hashes would push an extra lookup onto every
    caller — the kind of lookup that gets skipped once and produces a citation
    nobody validated.

    Still a *candidate*: it earns `semantic_candidate` derivation and cannot
    support an authoritative finding on its own (AGENTS.md Section 11).
    """

    logical_chunk_id: str
    chunk_version_id: str
    snapshot_id: str
    file_id: str
    content_hash: str
    qualified_name: str
    start_line: int
    end_line: int
    part_index: int
    score: float


class SnapshotMembershipFilter:
    """Keep only the vector hits whose content is in a given snapshot."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def keep_active(
        self, snapshot_id: str, matches: Sequence[VectorMatch]
    ) -> tuple[SemanticCandidate, ...]:
        """Resolve matches to chunks of ``snapshot_id``, preserving rank order.

        Filtering removes candidates; it must not reorder the survivors, so the
        result follows the incoming score order rather than any database
        ordering.

        One content hash can resolve to more than one chunk — the same body
        appearing in two files is ordinary — and every one of them is a real
        place that content lives, so all are returned.
        """
        if not matches:
            return ()

        scores = {match.content_hash: match.score for match in matches}
        rows_by_hash: dict[str, list[sqlite3.Row]] = {}
        hashes = list(dict.fromkeys(match.content_hash for match in matches))

        for start in range(0, len(hashes), _MAX_PARAMETERS):
            batch = hashes[start : start + _MAX_PARAMETERS]
            placeholders = ", ".join("?" for _ in batch)
            rows = self._connection.execute(
                "SELECT snapshot_id, logical_chunk_id, chunk_version_id, file_id,"
                " content_hash, qualified_name, start_line, end_line, part_index"
                " FROM chunks"
                f" WHERE snapshot_id = ? AND content_hash IN ({placeholders})"
                " ORDER BY logical_chunk_id, part_index",
                (snapshot_id, *batch),
            ).fetchall()
            for row in rows:
                rows_by_hash.setdefault(row["content_hash"], []).append(row)

        candidates: list[SemanticCandidate] = []
        for match in matches:
            for row in rows_by_hash.get(match.content_hash, ()):
                candidates.append(
                    SemanticCandidate(
                        logical_chunk_id=row["logical_chunk_id"],
                        chunk_version_id=row["chunk_version_id"],
                        snapshot_id=row["snapshot_id"],
                        file_id=row["file_id"],
                        content_hash=row["content_hash"],
                        qualified_name=row["qualified_name"],
                        start_line=int(row["start_line"]),
                        end_line=int(row["end_line"]),
                        part_index=int(row["part_index"]),
                        score=scores[match.content_hash],
                    )
                )
        return tuple(candidates)

    def content_hashes_in_snapshot(self, snapshot_id: str) -> tuple[str, ...]:
        """Every distinct content hash the snapshot's chunks carry.

        This is the embedding queue's input: subtracting what is already
        covered from this set gives exactly the work an edit created.
        """
        rows = self._connection.execute(
            "SELECT DISTINCT content_hash FROM chunks WHERE snapshot_id = ?"
            " ORDER BY content_hash",
            (snapshot_id,),
        ).fetchall()
        return tuple(row[0] for row in rows)
