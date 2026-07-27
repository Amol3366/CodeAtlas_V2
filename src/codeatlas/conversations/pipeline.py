"""The deterministic answer pipeline.

`AGENTS.md` Section 10.1 steps 1-13 and 16-17. Steps 14-15 — generation and
claim re-validation of generated text — are Phase 7's; nothing here invents a
repository fact, so there is nothing extra to re-validate.

**This is not a second retrieval implementation.** The pipeline classifies the
question, calls exactly one existing application service, and renders what that
service returned. A contract test asserts that the same question through this
pipeline and through `/v1/query` produces the same claims, evidence, and
warnings — if this file ever started deciding retrieval for itself, that test
is what would fail.

Cancellation is cooperative and checked between stages. A run that is cancelled
mid-retrieval stops at the next checkpoint and reports `cancelled`; it never
half-persists an answer.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from codeatlas.application.graph_queries import GraphQueryRequest, GraphQueryService
from codeatlas.application.lookup import ExactSymbolLookupService, SymbolLookupRequest
from codeatlas.contracts import QueryResponse
from codeatlas.conversations.intent import Intent, classify
from codeatlas.conversations.templates import render_answer
from codeatlas.retrieval.graph import TraversalLimits
from codeatlas.retrieval.lexical import (
    MAX_SEARCH_RESULTS,
    LexicalSearchService,
    SearchRequest,
)

DEFAULT_GRAPH_DEPTH: int = 2


class CancelledError(Exception):
    """Raised at a checkpoint when the caller asked the run to stop."""


class CancelToken:
    """A cooperative cancellation flag.

    Cooperative rather than pre-emptive because the work is synchronous SQLite
    and parsing: killing it mid-statement could leave a connection in a state
    the next request would inherit.
    """

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise CancelledError("the run was cancelled")


@dataclass(frozen=True)
class PipelineEvent:
    """One progress event, named for the stage that produced it.

    P5-04 turns these into the Section 11.2 stream vocabulary. They are emitted
    through a callback rather than returned so a client can see progress before
    the answer exists.
    """

    stage: str
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AnswerRequest:
    """One question, already bound to a repository and a request ID."""

    repository_id: str
    question: str
    request_id: str


@dataclass(frozen=True)
class AnswerResult:
    """A verified response and the message text rendered from it."""

    response: QueryResponse
    markdown: str
    intent: Intent
    target: str
    policy_version: str
    latency_ms: float


class AnswerPipeline:
    """Answer one question using the services every other adapter uses."""

    def __init__(
        self,
        lookup: ExactSymbolLookupService,
        graph: GraphQueryService,
        search: LexicalSearchService,
    ) -> None:
        self._lookup = lookup
        self._graph = graph
        self._search = search

    def execute(
        self,
        request: AnswerRequest,
        *,
        on_event: Callable[[PipelineEvent], None] | None = None,
        cancel: CancelToken | None = None,
    ) -> AnswerResult:
        emit = on_event or (lambda _event: None)
        token = cancel or CancelToken()
        started = time.perf_counter()

        token.raise_if_cancelled()
        classification = classify(request.question)
        emit(
            PipelineEvent(
                "retrieval.started",
                {
                    "intent": classification.intent.value,
                    "policy_version": classification.policy_version,
                },
            )
        )

        token.raise_if_cancelled()
        response = self._retrieve(request, classification.intent, classification.target)
        emit(
            PipelineEvent(
                "retrieval.progress",
                {
                    "intent": classification.intent.value,
                    "evidence_count": len(response.evidence),
                    "claim_count": len(response.answer.claims),
                },
            )
        )

        token.raise_if_cancelled()
        markdown = render_answer(response, intent=classification.intent)
        emit(PipelineEvent("generation.delta", {"length": len(markdown)}))

        return AnswerResult(
            response=response,
            markdown=markdown,
            intent=classification.intent,
            target=classification.target,
            policy_version=classification.policy_version,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    def _retrieve(
        self, request: AnswerRequest, intent: Intent, target: str
    ) -> QueryResponse:
        """Dispatch to the one service that answers this intent.

        Exactly the dispatch `/v1/query` performs for the equivalent mode. The
        parity test compares the two outputs field by field.
        """
        if intent in {Intent.EXACT_SYMBOL, Intent.CHANGE}:
            # `CHANGE` resolves the named subject for now: a conversational
            # change preflight needs a base ref the question does not carry,
            # and guessing one would analyze a change nobody asked about.
            # P5-09 gives it the explicit preflight action instead.
            return self._lookup.lookup(
                SymbolLookupRequest(
                    repository_id=request.repository_id,
                    query=target,
                    request_id=request.request_id,
                )
            )

        if intent is Intent.TEXT:
            return self._search.search_text(
                SearchRequest(
                    repository_id=request.repository_id,
                    query=target,
                    request_id=request.request_id,
                    limit=MAX_SEARCH_RESULTS,
                )
            )

        graph_request = GraphQueryRequest(
            repository_id=request.repository_id,
            symbol=target,
            request_id=request.request_id,
            max_depth=DEFAULT_GRAPH_DEPTH,
            limits=TraversalLimits(max_depth=DEFAULT_GRAPH_DEPTH),
        )
        handler = {
            Intent.CALLERS: self._graph.callers,
            Intent.CALLEES: self._graph.callees,
            Intent.DEPENDENCIES: self._graph.dependencies,
            Intent.TESTS: self._graph.related_tests,
            Intent.DOCUMENTS: self._graph.related_documents,
            Intent.TRACE: self._graph.trace,
        }[intent]
        return handler(graph_request)


__all__ = [
    "DEFAULT_GRAPH_DEPTH",
    "AnswerPipeline",
    "AnswerRequest",
    "AnswerResult",
    "CancelToken",
    "CancelledError",
    "PipelineEvent",
]
