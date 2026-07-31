"""Evidence-grounded answer rewriting.

This is pipeline steps 14-15 when an answer provider is explicitly injected:
generate a narrative from verified evidence, then validate every generated
claim's citations before replacing the deterministic/template answer.
"""

from __future__ import annotations

import time

from codeatlas.contracts import Answer, Claim, Derivation, QueryResponse
from codeatlas.generation.providers import (
    AnswerProvider,
    GeneratedAnswer,
    build_evidence_prompt,
)

ANSWER_GENERATION_FAILED_WARNING = "ANSWER_GENERATION_FAILED"
GENERATED_CLAIM_INVALID_WARNING = "GENERATED_CLAIM_INVALID"
MODEL_GENERATED_CONFIDENCE = 0.6


class EvidenceGroundedExplanationService:
    """Optionally replace answer prose with provider-generated prose."""

    def __init__(
        self,
        provider: AnswerProvider,
        *,
        confidence: float = MODEL_GENERATED_CONFIDENCE,
    ) -> None:
        self._provider = provider
        self._confidence = confidence

    def explain(self, response: QueryResponse, *, question: str) -> QueryResponse:
        """Return a generated answer, or the original response on any fault."""
        if not response.evidence:
            return response

        prompt = build_evidence_prompt(response, question)
        started = time.perf_counter()
        try:
            generated = self._provider.generate(prompt)
        except Exception:
            return _with_warning(response, ANSWER_GENERATION_FAILED_WARNING)
        if generated is None:
            return response

        validation = _validate_generated(generated, response)
        if validation is not None:
            return _with_warning(response, validation)

        elapsed = (time.perf_counter() - started) * 1000
        try:
            answer = Answer(
                summary=generated.summary,
                claims=[
                    Claim(
                        claim_id=f"c{position + 1}",
                        text=claim.text,
                        derivation=Derivation.MODEL_GENERATED,
                        confidence=self._confidence,
                        evidence_ids=list(claim.evidence_ids),
                    )
                    for position, claim in enumerate(generated.claims)
                ],
            )
            return response.model_copy(
                update={
                    "answer": answer,
                    "timing_ms": {
                        **response.timing_ms,
                        "answer_generation": elapsed,
                    },
                }
            )
        except ValueError:
            return _with_warning(response, GENERATED_CLAIM_INVALID_WARNING)


def _validate_generated(
    generated: GeneratedAnswer, response: QueryResponse
) -> str | None:
    known = {item.evidence_id for item in response.evidence}
    if not generated.summary.strip() or not generated.claims:
        return GENERATED_CLAIM_INVALID_WARNING
    for claim in generated.claims:
        if not claim.text.strip() or not claim.evidence_ids:
            return GENERATED_CLAIM_INVALID_WARNING
        if set(claim.evidence_ids) - known:
            return GENERATED_CLAIM_INVALID_WARNING
    return None


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

