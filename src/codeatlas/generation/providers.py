"""Answer-provider contracts for evidence-grounded explanations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from codeatlas.contracts import QueryResponse, RelationPath

ANSWER_PROMPT_VERSION = "phase7-answer-v1"
NO_ANSWER_MODEL_ID = "none"
NO_ANSWER_PROMPT_VERSION = "none"


@dataclass(frozen=True)
class PromptEvidence:
    evidence_id: str
    file_path: str
    symbol: str | None
    start_line: int
    end_line: int
    excerpt: str
    derivation: str
    confidence: float


@dataclass(frozen=True)
class EvidenceGroundedPrompt:
    """The complete payload an answer provider may see."""

    question: str
    evidence: tuple[PromptEvidence, ...]
    relation_paths: tuple[RelationPath, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    prompt_version: str = ANSWER_PROMPT_VERSION


@dataclass(frozen=True)
class GeneratedClaim:
    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeneratedAnswer:
    summary: str
    claims: tuple[GeneratedClaim, ...]


class AnswerProvider(Protocol):
    """Generate a narrative from verified evidence only."""

    model_id: str
    prompt_version: str

    def generate(self, prompt: EvidenceGroundedPrompt) -> GeneratedAnswer | None: ...


class NoAnswerProvider:
    """The safe default: no model call and no answer rewrite."""

    model_id = NO_ANSWER_MODEL_ID
    prompt_version = NO_ANSWER_PROMPT_VERSION

    def generate(self, prompt: EvidenceGroundedPrompt) -> GeneratedAnswer | None:
        return None


def build_evidence_prompt(
    response: QueryResponse, question: str
) -> EvidenceGroundedPrompt:
    """Build the constrained provider payload.

    Repository content enters only through evidence excerpts that have already
    passed snapshot and hash validation. The repository root, uncited chunks,
    prompts, prior messages, and generated answers are not represented here.
    """
    return EvidenceGroundedPrompt(
        question=question,
        evidence=tuple(
            PromptEvidence(
                evidence_id=item.evidence_id,
                file_path=item.file_path,
                symbol=item.symbol,
                start_line=item.start_line,
                end_line=item.end_line,
                excerpt=item.excerpt,
                derivation=item.derivation.value,
                confidence=item.confidence,
            )
            for item in response.evidence
        ),
        relation_paths=tuple(response.relation_paths),
        warnings=tuple(response.warnings),
        limitations=tuple(response.limitations),
    )


__all__ = [
    "ANSWER_PROMPT_VERSION",
    "NO_ANSWER_MODEL_ID",
    "NO_ANSWER_PROMPT_VERSION",
    "AnswerProvider",
    "EvidenceGroundedPrompt",
    "GeneratedAnswer",
    "GeneratedClaim",
    "NoAnswerProvider",
    "PromptEvidence",
    "build_evidence_prompt",
]

