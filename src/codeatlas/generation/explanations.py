"""Evidence-grounded answer rewriting.

Pipeline steps 14-15 when an answer provider is configured: generate prose from
verified evidence, check what it cites, and replace the answer's summary with
it.

**Only the summary changes.** `answer.claims` and `evidence` pass through
untouched, with their original derivation and confidence. Generation runs on
every intent, including ones whose claims are `deterministic`, so rewriting
claims here would present a traced call graph as something a model said. The
summary is the prose slot; the claims are the findings.

**Nothing here can fail a run.** Every fault returns the response that came in,
plus a warning naming the cause. The response was already a complete,
deliverable answer before generation was attempted, and discarding it to report
trouble in an optional layer would be a poor trade.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import replace

from codeatlas.contracts import Answer, QueryResponse
from codeatlas.generation.failures import AnswerProviderFailure
from codeatlas.generation.providers import (
    NO_ANSWER_MODEL_ID,
    AnswerProvider,
    EvidenceGroundedPrompt,
    build_evidence_prompt,
    collect_stream,
)

# Pure string work: `redaction` imports only `re`, `dataclasses`, and `typing`,
# so the deterministic generation path takes on no optional dependency by
# reaching into the semantic package for it.
from codeatlas.semantic.redaction import redact

ANSWER_GENERATION_FAILED_WARNING = "ANSWER_GENERATION_FAILED"
GENERATED_CLAIM_INVALID_WARNING = "GENERATED_CLAIM_INVALID"
MODEL_GENERATED_CONFIDENCE = 0.6

# Evidence IDs are `ev_<digest>` (`domain.ids.evidence_id`). Anchoring on that
# prefix is what lets prose keep ordinary brackets — a template cites as `[1]`,
# and prose legitimately contains `[2]` — while still catching a fabricated
# `[ev_...]` marker. A looser pattern would reject correct answers, which is a
# worse failure than the one it prevents.
_CITATION = re.compile(r"\[(ev_[A-Za-z0-9_]+)\]")


class EvidenceGroundedExplanationService:
    """Replace answer prose with provider-generated prose, or explain why not."""

    def __init__(
        self,
        provider: AnswerProvider,
        *,
        confidence: float = MODEL_GENERATED_CONFIDENCE,
    ) -> None:
        self._provider = provider
        self._confidence = confidence

    def explain(
        self,
        response: QueryResponse,
        *,
        question: str,
        on_token: Callable[[str], None] | None = None,
    ) -> QueryResponse:
        """Return the response with generated prose, or unchanged with a cause."""
        if self._provider.model_id == NO_ANSWER_MODEL_ID:
            # No provider is configured, which is the default and not a fault.
            # Checked before anything else so the common case builds no prompt
            # and reports nothing: a repository that opted into no generation
            # must produce exactly the answer it produced before this feature
            # existed, warnings included.
            return response

        if not response.evidence:
            # An abstention is never dressed up. "What CodeAtlas does not know"
            # is one of the product's five questions, and prose over no evidence
            # is the easiest way to lose it.
            return response

        prompt = _redacted_prompt(response, question)
        started = time.perf_counter()
        try:
            text = self._produce(prompt, on_token)
        except AnswerProviderFailure as failure:
            return _with_warning(response, failure.warning_code)
        except Exception:
            return _with_warning(response, ANSWER_GENERATION_FAILED_WARNING)

        if not text.strip():
            return _with_warning(response, GENERATED_CLAIM_INVALID_WARNING)
        if _cites_unknown_evidence(text, response):
            return _with_warning(response, GENERATED_CLAIM_INVALID_WARNING)

        elapsed = (time.perf_counter() - started) * 1000
        try:
            answer = Answer(
                summary=text.strip(), claims=list(response.answer.claims)
            )
        except ValueError:
            return _with_warning(response, GENERATED_CLAIM_INVALID_WARNING)
        return response.model_copy(
            update={
                "answer": answer,
                "timing_ms": {**response.timing_ms, "answer_generation": elapsed},
            }
        )

    def _produce(
        self,
        prompt: EvidenceGroundedPrompt,
        on_token: Callable[[str], None] | None,
    ) -> str:
        """Stream when someone is watching; otherwise ask once.

        A CLI run or a contract test has nobody to stream to, and one call is
        cheaper than a connection held open for an audience that does not exist.
        """
        if on_token is None:
            generated = self._provider.generate(prompt)
            return "" if generated is None else generated.summary

        chunks: list[str] = []
        for chunk in self._provider.generate_stream(prompt):
            chunks.append(chunk)
            on_token(chunk)
        return collect_stream(chunks)


def _redacted_prompt(
    response: QueryResponse, question: str
) -> EvidenceGroundedPrompt:
    """Build the provider payload with secrets removed from every excerpt.

    Applied here rather than inside each provider, so there is one place to
    audit and no way to add a third provider that forgets. Applied for local
    providers too: a local model transmits nothing, but it can still write a
    secret into an answer that is then pasted into a ticket or a pull request.

    Only the *prompt* is redacted. The response keeps its real excerpts,
    because the evidence drawer shows the user their own file on their own
    machine, and blanking it there would hide something they already have.
    """
    prompt = build_evidence_prompt(response, question)
    return replace(
        prompt,
        evidence=tuple(
            replace(item, excerpt=redact(item.excerpt).text)
            for item in prompt.evidence
        ),
    )


def _cites_unknown_evidence(text: str, response: QueryResponse) -> bool:
    """Whether the prose references an evidence ID that does not exist.

    The structured claims below the summary are always correct, but a citation
    the reader can follow is the product's whole promise. A marker pointing at
    nothing is exactly the hallucination the evidence contract exists to
    prevent, so the summary is discarded rather than shown with it.
    """
    known = {item.evidence_id for item in response.evidence}
    return any(cited not in known for cited in _CITATION.findall(text))


def _with_warning(response: QueryResponse, warning: str) -> QueryResponse:
    warnings = list(response.warnings)
    if warning not in warnings:
        warnings.append(warning)
    return response.model_copy(update={"warnings": warnings})


__all__ = [
    "ANSWER_GENERATION_FAILED_WARNING",
    "GENERATED_CLAIM_INVALID_WARNING",
    "MODEL_GENERATED_CONFIDENCE",
    "EvidenceGroundedExplanationService",
]
