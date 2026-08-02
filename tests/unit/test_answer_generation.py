"""Evidence-grounded answer generation primitives."""

from __future__ import annotations

from collections.abc import Iterator

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
from codeatlas.generation.explanations import (
    ANSWER_GENERATION_FAILED_WARNING,
    GENERATED_CLAIM_INVALID_WARNING,
    EvidenceGroundedExplanationService,
)
from codeatlas.generation.providers import (
    GeneratedAnswer,
    GeneratedClaim,
    NoAnswerProvider,
    build_evidence_prompt,
    collect_stream,
)


def _response() -> QueryResponse:
    evidence = Evidence(
        evidence_id="ev_1",
        repository_id="repo_1",
        snapshot_id="snap_1",
        file_path="src/orders/service.py",
        symbol="OrderService.place",
        start_line=10,
        end_line=14,
        excerpt="def place(order):\n    return order",
        content_hash="hash_1",
        derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
        confidence=0.7,
        validation=EvidenceValidation.VALID,
    )
    return QueryResponse(
        request_id="req_1",
        repository_id="repo_1",
        snapshot=SnapshotReference(
            snapshot_id="snap_1",
            git_head=None,
            working_tree_fingerprint="fp",
            freshness=SnapshotFreshness.FRESH,
            semantic_coverage=0.0,
        ),
        answer=Answer(
            summary="Found one location.",
            claims=[
                Claim(
                    claim_id="c1",
                    text="The order flow is in service.py.",
                    derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
                    confidence=0.7,
                    evidence_ids=["ev_1"],
                )
            ],
        ),
        evidence=[evidence],
        warnings=["NO_LEXICAL_MATCH"],
        limitations=[],
    )


class RecordingProvider:
    model_id = "fake-answer"
    prompt_version = "prompt-v1"

    def __init__(self, answer: GeneratedAnswer) -> None:
        self.answer = answer
        self.prompts: list[object] = []

    def generate(self, prompt: object) -> GeneratedAnswer:
        self.prompts.append(prompt)
        return self.answer

    def generate_stream(self, prompt: object) -> Iterator[str]:
        self.prompts.append(prompt)
        yield self.answer.summary


class ExplodingProvider(RecordingProvider):
    def generate(self, prompt: object) -> GeneratedAnswer:
        self.prompts.append(prompt)
        raise TimeoutError("provider unavailable")

    def generate_stream(self, prompt: object) -> Iterator[str]:
        self.prompts.append(prompt)
        raise TimeoutError("provider unavailable")
        yield ""  # pragma: no cover - unreachable, keeps this a generator


def test_no_answer_provider_is_identity() -> None:
    assert NoAnswerProvider().generate(build_evidence_prompt(_response(), "q")) is None


def test_no_answer_provider_streams_nothing() -> None:
    prompt = build_evidence_prompt(_response(), "q")
    assert list(NoAnswerProvider().generate_stream(prompt)) == []


def test_collect_stream_joins_chunks_in_order() -> None:
    assert collect_stream(["Hel", "lo ", "world"]) == "Hello world"


def test_collect_stream_of_nothing_is_empty() -> None:
    assert collect_stream([]) == ""


def test_prompt_contains_only_verified_evidence_and_warnings() -> None:
    prompt = build_evidence_prompt(_response(), "What places an order?")

    dumped = repr(prompt)
    assert "def place(order)" in dumped
    assert "NO_LEXICAL_MATCH" in dumped
    assert "uncited repository text" not in dumped


def test_valid_generated_answer_replaces_only_the_answer_text() -> None:
    provider = RecordingProvider(
        GeneratedAnswer(
            summary="Orders are placed by the service.",
            claims=(
                GeneratedClaim(
                    text="`OrderService.place` is the relevant operation.",
                    evidence_ids=("ev_1",),
                ),
            ),
        )
    )
    original = _response()

    generated = EvidenceGroundedExplanationService(provider).explain(
        original, question="What places an order?"
    )

    assert generated.evidence == original.evidence
    assert generated.answer.summary == "Orders are placed by the service."
    assert generated.answer.claims[0].derivation is Derivation.MODEL_GENERATED
    assert generated.answer.claims[0].evidence_ids == ["ev_1"]


def test_generated_claim_with_unknown_evidence_is_rejected() -> None:
    provider = RecordingProvider(
        GeneratedAnswer(
            summary="Invented summary.",
            claims=(
                GeneratedClaim(text="Unknown citation.", evidence_ids=("ev_missing",)),
            ),
        )
    )
    original = _response()

    generated = EvidenceGroundedExplanationService(provider).explain(
        original, question="What places an order?"
    )

    assert generated.answer == original.answer
    assert GENERATED_CLAIM_INVALID_WARNING in generated.warnings


def test_provider_failure_preserves_the_original_answer() -> None:
    original = _response()

    generated = EvidenceGroundedExplanationService(
        ExplodingProvider(GeneratedAnswer(summary="unused", claims=()))
    ).explain(original, question="What places an order?")

    assert generated.answer == original.answer
    assert ANSWER_GENERATION_FAILED_WARNING in generated.warnings

