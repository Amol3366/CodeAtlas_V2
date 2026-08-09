"""Adding semantic candidates to an answer that is already complete.

Step 9 of `AGENTS.md` Section 10.1 — "deduplicate and fuse candidates without
erasing derivation" — with one restriction the wording implies and this module
makes structural: **fusion only ever appends.**

The deterministic answer arrives here finished. Its claims, its evidence, and
their order are treated as immutable, and semantic candidates are added after
them. A semantic hit that could reorder or displace a deterministic result would
be deciding relevance, and deciding relevance is the authority Section 4.3
withholds from a model score. Appending is the only operation that cannot
express that mistake.

Two consequences worth naming:

* removing this layer leaves the response byte-identical, which is what makes
  the deterministic fallback verifiable rather than merely asserted;
* a candidate still goes through `EvidenceBuilder`, so it is read from disk and
  hash-checked exactly like deterministic evidence. Being a weaker *kind* of
  finding does not make it a less verified *citation*.
"""

from __future__ import annotations

import time
from pathlib import Path

from codeatlas.application.evidence import EvidenceBuilder, EvidenceCandidate
from codeatlas.application.rank_fusion import fuse_ranks
from codeatlas.application.semantic_status import SemanticStatusService
from codeatlas.contracts import (
    Answer,
    Claim,
    Derivation,
    Evidence,
    QueryResponse,
    SnapshotFreshness,
    SnapshotReference,
)
from codeatlas.retrieval.semantic import SemanticSearchRequest, SemanticSearchService
from codeatlas.semantic.reranking import (
    MAX_RERANK_CANDIDATES,
    RerankCache,
    RerankCandidate,
    Reranker,
    RerankRequest,
    rerank_cache_key,
)
from codeatlas.storage.sqlite.stores import (
    EvidenceStore,
    FileStore,
    RepositoryStore,
    SnapshotStore,
)

# Below the lexical channel's 0.7, deliberately. A literal text match is stronger
# evidence than a nearest neighbour in a similarity space, and a confidence that
# did not say so would flatten a real distinction.
SEMANTIC_CONFIDENCE = 0.5

SEMANTIC_LIMITATION = (
    "Semantic candidates are discovered by similarity, not resolved. They are"
    " labelled semantic_candidate and cannot support a finding on their own."
)
RERANK_FAILED_WARNING = "RERANK_FAILED"


class SemanticFusionService:
    """Append verified semantic candidates to a deterministic response."""

    def __init__(
        self,
        *,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        files: FileStore,
        evidence: EvidenceStore | None,
        status: SemanticStatusService,
        semantic: SemanticSearchService,
        reranker: Reranker | None = None,
        rerank_cache: RerankCache | None = None,
        max_rerank_candidates: int = MAX_RERANK_CANDIDATES,
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots
        self._status = status
        self._semantic = semantic
        self._evidence = EvidenceBuilder(files, evidence)
        self._reranker = reranker
        self._rerank_cache = rerank_cache or RerankCache()
        self._max_rerank_candidates = max(1, max_rerank_candidates)

    def augment(self, response: QueryResponse, *, question: str) -> QueryResponse:
        """Return ``response`` with semantic candidates added, or unchanged.

        Never raises. The response passed in is a complete, deliverable answer;
        an exception here would discard it to report trouble in an optional
        layer.
        """
        result = self._semantic.search(
            SemanticSearchRequest(
                repository_id=response.repository_id,
                snapshot_id=response.snapshot.snapshot_id,
                query=question,
            )
        )
        if not result.enabled:
            # Identity, not a rebuilt copy. Reconstructing an equal response
            # would let a future field be dropped here without any test noticing.
            return response

        # Applied before the candidates, and regardless of whether any were
        # found: coverage describes the index, not the query. A run that
        # matched nothing still has to report how much of the snapshot was
        # searchable, or "found nothing" and "could not look" become
        # indistinguishable.
        response = self._with_coverage(response)
        if not result.candidates:
            return self._with_warnings(response, result.warnings)

        repository = self._repositories.get(response.repository_id)
        snapshot = self._snapshots.get(response.snapshot.snapshot_id)
        if repository is None or snapshot is None:
            # The snapshot was superseded and pruned between the deterministic
            # answer and this call. The answer is still valid for the snapshot
            # it names; only the addition is lost.
            return self._with_warnings(response, result.warnings)

        # A region the deterministic half already cited is not cited again: the
        # two channels finding the same chunk is the point of fusing them, and
        # showing it twice would read as two independent sources agreeing.
        already_cited = {
            (item.file_path, item.start_line, item.end_line)
            for item in response.evidence
        }

        outcome = self._evidence.build(
            repository_root=Path(repository.canonical_root),
            snapshot=snapshot,
            candidates=[
                EvidenceCandidate(
                    file_id=candidate.file_id,
                    start_line=candidate.start_line,
                    end_line=candidate.end_line,
                    symbol=candidate.qualified_name or None,
                    derivation=Derivation.SEMANTIC_CANDIDATE,
                    confidence=SEMANTIC_CONFIDENCE,
                )
                for candidate in result.candidates
            ],
        )

        candidate_order = [
            (item.file_path, item.start_line, item.end_line)
            for item in outcome.evidence
        ]

        added_evidence = [
            item
            for item in outcome.evidence
            if (item.file_path, item.start_line, item.end_line) not in already_cited
        ]
        if not added_evidence and not (already_cited & set(candidate_order)):
            return self._with_warnings(response, result.warnings + outcome.warnings)

        rerank_warnings: tuple[str, ...] = ()
        rerank_timing: dict[str, float] = {}
        added_evidence, rerank_warnings, rerank_timing = self._rerank(
            response, question=question, evidence=added_evidence
        )

        # The semantic channel's final order, built *after* reranking so the
        # reranker's opinion reaches fusion. Computing this from the raw
        # candidates would have let fusion re-sort the reranked items back into
        # their original order -- the reranker's whole output discarded by the
        # step after it.
        #
        # Regions the deterministic half already cited keep their exact
        # position: they were never offered to the reranker, and they are the
        # reason this list exists. They are still cited once, in the evidence
        # list built below, but their *rank* counts here, because a chunk both
        # channels found is the strongest signal either produces and dropping
        # that agreement was the defect ADR-0028 fixes.
        reranked = iter(
            (item.file_path, item.start_line, item.end_line)
            for item in added_evidence
        )
        semantic_order = [
            region if region in already_cited else next(reranked, region)
            for region in candidate_order
        ]

        # Claim IDs continue the deterministic sequence rather than restarting.
        # Citations reference claims by ID, so a collision would silently
        # repoint a citation at another claim.
        offset = len(response.answer.claims)
        claims = [
            Claim(
                claim_id=f"c{offset + position + 1}",
                text=(
                    f"{item.file_path} lines {item.start_line}-{item.end_line}"
                    " are semantically similar to the question."
                ),
                derivation=Derivation.SEMANTIC_CANDIDATE,
                confidence=SEMANTIC_CONFIDENCE,
                evidence_ids=[item.evidence_id],
            )
            for position, item in enumerate(added_evidence)
        ]

        limitations = list(response.limitations)
        if SEMANTIC_LIMITATION not in limitations:
            limitations.append(SEMANTIC_LIMITATION)

        # One order over both channels, by rank. Each evidence object is carried
        # across unchanged -- only its position moves -- so a deterministic item
        # stays deterministic and a candidate stays a candidate wherever it
        # lands. Section 4.3 forbids a model score promoting a candidate to
        # deterministic evidence; it does not require the answer to present a
        # worse-matching citation first.
        combined = [*response.evidence, *added_evidence]
        by_region = {
            (item.file_path, item.start_line, item.end_line): item
            for item in combined
        }
        fused_regions = fuse_ranks(
            [
                (item.file_path, item.start_line, item.end_line)
                for item in response.evidence
            ],
            semantic_order,
        )
        fused_evidence = [
            by_region[region] for region in fused_regions if region in by_region
        ]

        return response.model_copy(
            update={
                "answer": Answer(
                    summary=response.answer.summary,
                    claims=[*response.answer.claims, *claims],
                ),
                "evidence": fused_evidence,
                "warnings": _merged(
                    response.warnings,
                    result.warnings + outcome.warnings + rerank_warnings,
                ),
                "limitations": limitations,
                "timing_ms": {
                    **response.timing_ms,
                    **result.timing_ms,
                    **rerank_timing,
                },
            }
        )

    def _rerank(
        self,
        response: QueryResponse,
        *,
        question: str,
        evidence: list[Evidence],
    ) -> tuple[list[Evidence], tuple[str, ...], dict[str, float]]:
        """Optionally reorder semantic evidence, preserving the tail.

        Only the bounded prefix is offered to the reranker. Candidates outside
        the bound keep their original relative order, which makes latency and
        cost independent of a broad semantic hit set.
        """
        if self._reranker is None or len(evidence) < 2:
            return evidence, (), {}

        top = evidence[: self._max_rerank_candidates]
        request = RerankRequest(
            repository_id=response.repository_id,
            snapshot_id=response.snapshot.snapshot_id,
            query=question,
            candidates=tuple(
                RerankCandidate(
                    candidate_id=item.evidence_id,
                    content_hash=item.content_hash,
                    text=item.excerpt,
                )
                for item in top
            ),
        )
        key = rerank_cache_key(
            request,
            model_id=self._reranker.model_id,
            prompt_version=self._reranker.prompt_version,
        )
        started = time.perf_counter()
        ordered = self._rerank_cache.get(key)
        if ordered is None:
            try:
                ordered = self._reranker.rerank(request)
            except Exception:
                return evidence, (RERANK_FAILED_WARNING,), {}
            if not _valid_order(ordered, {item.evidence_id for item in top}):
                return evidence, (RERANK_FAILED_WARNING,), {}
            self._rerank_cache.put(key, ordered)
        elapsed = (time.perf_counter() - started) * 1000

        by_id = {item.evidence_id: item for item in top}
        ranked = [by_id[evidence_id] for evidence_id in ordered]
        remaining_top = [
            item for item in top if item.evidence_id not in set(ordered)
        ]
        return (
            [*ranked, *remaining_top, *evidence[self._max_rerank_candidates :]],
            (),
            {"rerank": elapsed},
        )

    def _with_coverage(self, response: QueryResponse) -> QueryResponse:
        """Put the measured semantic coverage into the envelope.

        `semantic_coverage` has been hardcoded 0.0 since Phase 0, which was
        honest while nothing was embedded and becomes a false measurement the
        moment something is. A field that always reads 0.0 is worse than an
        absent one: it looks like it was measured.

        Freshness is only ever *weakened* here, from fresh to partial. A stale
        snapshot stays stale: incomplete embeddings are the lesser problem, and
        overwriting the deterministic verdict with the semantic one would hide
        the more serious fact.
        """
        try:
            status = self._status.status(response.repository_id)
        except Exception:
            return response
        if status.coverage is None:
            return response

        freshness = response.snapshot.freshness
        if freshness is SnapshotFreshness.FRESH and not status.is_complete:
            freshness = SnapshotFreshness.PARTIAL

        return response.model_copy(
            update={
                "snapshot": SnapshotReference(
                    snapshot_id=response.snapshot.snapshot_id,
                    git_head=response.snapshot.git_head,
                    working_tree_fingerprint=(
                        response.snapshot.working_tree_fingerprint
                    ),
                    freshness=freshness,
                    semantic_coverage=status.coverage,
                )
            }
        )

    def _with_warnings(
        self, response: QueryResponse, warnings: tuple[str, ...]
    ) -> QueryResponse:
        if not warnings:
            return response
        return response.model_copy(
            update={"warnings": _merged(response.warnings, warnings)}
        )


def _merged(existing: list[str], added: tuple[str, ...]) -> list[str]:
    """Append the new codes, keeping order and dropping repeats."""
    merged = list(existing)
    for code in added:
        if code not in merged:
            merged.append(code)
    return merged


def _valid_order(ordered: tuple[str, ...], known: set[str]) -> bool:
    if len(ordered) != len(set(ordered)):
        return False
    return not (set(ordered) - known)


__all__ = [
    "RERANK_FAILED_WARNING",
    "SEMANTIC_CONFIDENCE",
    "SEMANTIC_LIMITATION",
    "SemanticFusionService",
]
