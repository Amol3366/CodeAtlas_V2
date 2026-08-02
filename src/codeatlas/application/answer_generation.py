"""Resolving an answer provider for the repository actually being asked about.

`AnswerPipeline` is built once per request, before anyone knows which
repository the question concerns — it arrives inside `AnswerRequest`. So the
provider cannot be chosen at construction time. It is chosen here, per call,
from `response.repository_id`, exactly as `SemanticFusionService` resolves a
repository's semantic status.

Constructing the provider per call is cheap: `build_answer_provider` reads a
policy row and builds an HTTP client. No model is loaded, and a repository that
opted into nothing gets `NoAnswerProvider`, which makes no call at all.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from codeatlas.contracts import QueryResponse
from codeatlas.generation.explanations import EvidenceGroundedExplanationService
from codeatlas.generation.factory import build_answer_provider
from codeatlas.storage.sqlite.semantic_stores import ProviderPolicyStore


class RepositoryAnswerExplainer:
    """Generate prose using whichever provider this repository opted into."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._policies = ProviderPolicyStore(connection)

    def explain(
        self,
        response: QueryResponse,
        *,
        question: str,
        on_token: Callable[[str], None] | None = None,
    ) -> QueryResponse:
        policy = self._policies.get(response.repository_id)
        provider = build_answer_provider(policy)
        return EvidenceGroundedExplanationService(provider).explain(
            response, question=question, on_token=on_token
        )


__all__ = ["RepositoryAnswerExplainer"]
