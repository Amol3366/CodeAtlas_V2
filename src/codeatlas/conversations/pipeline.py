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
from typing import Protocol

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
PROJECT_OVERVIEW_SEARCH_RESULTS: int = 12
GREETING_SUMMARY: str = (
    "Hi. Ask me a question about the active repository, and I will answer from "
    "its indexed snapshot with citations when repository evidence is available."
)
PROJECT_OVERVIEW_LIMITATION: str = (
    "This overview is synthesized from indexed documentation, entry points, and "
    "symbols in the active snapshot; ask about a specific flow for graph-backed "
    "details."
)

# The one intent the semantic channel serves. Section 10.2 gives every other
# intent a resolution — an exact symbol, a call edge, a diff — and blueprint
# 15.6 rejects letting a similarity score participate in those.
#
# A frozen set rather than a check at the call site, because the safe default
# for an intent added later is *exclusion*: a new intent that nobody thought
# about must not silently acquire a provider call.
SEMANTIC_INTENTS: frozenset[Intent] = frozenset({Intent.PROJECT_OVERVIEW, Intent.TEXT})
GENERATION_INTENTS: frozenset[Intent] = frozenset({Intent.TEXT, Intent.TRACE})


class SemanticFusion(Protocol):
    """The one method this pipeline needs from the optional semantic layer.

    A protocol rather than an import, for the reason the whole phase turns on:
    the deterministic answer path must remain buildable and runnable on an
    installation where the semantic package's dependencies were never
    installed. A concrete import here would end that, quietly, the first time
    someone ran the CLI without the extras.

    The implementation is `application.semantic_fusion.SemanticFusionService`.
    """

    def augment(self, response: QueryResponse, *, question: str) -> QueryResponse: ...


class AnswerExplainer(Protocol):
    """The optional generation seam for steps 14-15."""

    def explain(self, response: QueryResponse, *, question: str) -> QueryResponse: ...


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
        fusion: SemanticFusion | None = None,
        explainer: AnswerExplainer | None = None,
    ) -> None:
        self._lookup = lookup
        self._graph = graph
        self._search = search
        # Optional, and typed as a protocol, so this module never imports the
        # semantic package. The deterministic path may not acquire a dependency
        # on the layer that is allowed to be absent — the same rule that shapes
        # `IndexRepositoryService.embedding`.
        self._fusion = fusion
        self._explainer = explainer

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

        token.raise_if_cancelled()
        response = self._fuse(response, request, classification.intent)
        if classification.intent is Intent.PROJECT_OVERVIEW:
            response = _project_overview_response(response)
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
        response = self._explain(response, request, classification.intent)

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

    def _fuse(
        self, response: QueryResponse, request: AnswerRequest, intent: Intent
    ) -> QueryResponse:
        """Add semantic candidates, for the one intent that may have them.

        The gate is checked *before* the channel is reached rather than by
        discarding its results afterwards. Filtering after the fact would still
        have spent the latency and, for a transmitting provider, would already
        have sent the question off the machine.
        """
        if self._fusion is None or intent not in SEMANTIC_INTENTS:
            return response
        return self._fusion.augment(response, question=request.question)

    def _explain(
        self, response: QueryResponse, request: AnswerRequest, intent: Intent
    ) -> QueryResponse:
        """Optionally rewrite answer prose from verified evidence only."""
        if self._explainer is None or intent not in GENERATION_INTENTS:
            return response
        return self._explainer.explain(response, question=request.question)

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

        if intent is Intent.GREETING:
            return self._search.response_without_evidence(
                SearchRequest(
                    repository_id=request.repository_id,
                    query=target,
                    request_id=request.request_id,
                    limit=1,
                ),
                summary=GREETING_SUMMARY,
                timing_ms={"conversation": 0.0},
            )

        if intent is Intent.PROJECT_OVERVIEW:
            return self._search.search_text(
                SearchRequest(
                    repository_id=request.repository_id,
                    query=target,
                    request_id=request.request_id,
                    limit=PROJECT_OVERVIEW_SEARCH_RESULTS,
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


def _project_overview_response(response: QueryResponse) -> QueryResponse:
    return response.model_copy(
        update={
            "warnings": [
                warning
                for warning in response.warnings
                if warning != "LEXICAL_QUERY_RELAXED"
            ],
            "limitations": [PROJECT_OVERVIEW_LIMITATION],
        }
    )


__all__ = [
    "DEFAULT_GRAPH_DEPTH",
    "GENERATION_INTENTS",
    "GREETING_SUMMARY",
    "PROJECT_OVERVIEW_LIMITATION",
    "PROJECT_OVERVIEW_SEARCH_RESULTS",
    "SEMANTIC_INTENTS",
    "AnswerExplainer",
    "AnswerPipeline",
    "AnswerRequest",
    "AnswerResult",
    "CancelToken",
    "CancelledError",
    "PipelineEvent",
    "SemanticFusion",
]
