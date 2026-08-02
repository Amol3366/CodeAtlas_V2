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
from codeatlas.generation.failures import ModelMissing, QuotaExhausted
from codeatlas.generation.providers import (
    GeneratedAnswer,
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


def test_generation_replaces_the_summary_and_nothing_else() -> None:
    provider = RecordingProvider(
        GeneratedAnswer(summary="Orders are placed by the service.", claims=())
    )
    original = _response()

    generated = EvidenceGroundedExplanationService(provider).explain(
        original, question="What places an order?"
    )

    assert generated.answer.summary == "Orders are placed by the service."
    assert generated.evidence == original.evidence


def test_deterministic_claims_survive_generation_untouched() -> None:
    """A proven fact is never relabelled as model output.

    Generation runs on every intent, including ones whose claims are
    `deterministic`. Rewriting claims here would present a traced call graph as
    something a model said.
    """
    provider = RecordingProvider(
        GeneratedAnswer(summary="Orders are placed by the service.", claims=())
    )
    original = _response()

    generated = EvidenceGroundedExplanationService(provider).explain(
        original, question="What places an order?"
    )

    assert generated.answer.claims == original.answer.claims
    assert generated.answer.claims[0].derivation is not Derivation.MODEL_GENERATED


def test_prose_citing_unknown_evidence_is_rejected() -> None:
    """The model may not invent a citation, even in prose."""
    provider = RecordingProvider(
        GeneratedAnswer(summary="See [ev_missing] for the detail.", claims=())
    )
    original = _response()

    generated = EvidenceGroundedExplanationService(provider).explain(
        original, question="What places an order?"
    )

    assert generated.answer == original.answer
    assert GENERATED_CLAIM_INVALID_WARNING in generated.warnings


def test_prose_citing_real_evidence_is_kept() -> None:
    provider = RecordingProvider(
        GeneratedAnswer(summary="See [ev_1] for the detail.", claims=())
    )

    generated = EvidenceGroundedExplanationService(provider).explain(
        _response(), question="What places an order?"
    )

    assert generated.answer.summary == "See [ev_1] for the detail."


def test_ordinary_brackets_are_not_mistaken_for_citations() -> None:
    """Templates cite as [1]; only `ev_`-prefixed markers are evidence IDs."""
    provider = RecordingProvider(
        GeneratedAnswer(summary="The list [1] and the map [2] are used.", claims=())
    )

    generated = EvidenceGroundedExplanationService(provider).explain(
        _response(), question="What places an order?"
    )

    assert generated.answer.summary == "The list [1] and the map [2] are used."


def test_empty_generated_text_falls_back_to_the_verified_answer() -> None:
    provider = RecordingProvider(GeneratedAnswer(summary="   ", claims=()))
    original = _response()

    generated = EvidenceGroundedExplanationService(provider).explain(
        original, question="What places an order?"
    )

    assert generated.answer == original.answer
    assert GENERATED_CLAIM_INVALID_WARNING in generated.warnings


def test_a_typed_failure_reports_its_own_cause() -> None:
    class _Failing(RecordingProvider):
        def generate(self, prompt: object) -> GeneratedAnswer:
            raise ModelMissing("llama3.2:3b is not pulled")

        def generate_stream(self, prompt: object) -> Iterator[str]:
            raise ModelMissing("llama3.2:3b is not pulled")
            yield ""  # pragma: no cover - unreachable, keeps this a generator

    original = _response()
    generated = EvidenceGroundedExplanationService(
        _Failing(GeneratedAnswer(summary="unused", claims=()))
    ).explain(original, question="q")

    assert generated.answer == original.answer
    assert "GENERATION_MODEL_MISSING" in generated.warnings


def test_quota_exhaustion_is_named_separately() -> None:
    class _Failing(RecordingProvider):
        def generate(self, prompt: object) -> GeneratedAnswer:
            raise QuotaExhausted("no credit")

        def generate_stream(self, prompt: object) -> Iterator[str]:
            raise QuotaExhausted("no credit")
            yield ""  # pragma: no cover - unreachable, keeps this a generator

    generated = EvidenceGroundedExplanationService(
        _Failing(GeneratedAnswer(summary="unused", claims=()))
    ).explain(_response(), question="q")

    assert "GENERATION_QUOTA_EXHAUSTED" in generated.warnings


def test_tokens_reach_the_callback_in_order() -> None:
    class _Streaming(RecordingProvider):
        def generate_stream(self, prompt: object) -> Iterator[str]:
            yield "Orders are "
            yield "placed by the service."

    seen: list[str] = []
    generated = EvidenceGroundedExplanationService(
        _Streaming(GeneratedAnswer(summary="unused", claims=()))
    ).explain(_response(), question="q", on_token=seen.append)

    assert "".join(seen) == "Orders are placed by the service."
    assert generated.answer.summary == "Orders are placed by the service."


def test_no_evidence_means_no_model_call_and_no_prose() -> None:
    """An abstention is never dressed up."""

    class _Exploding:
        model_id = "test"
        prompt_version = "v1"

        def generate(self, prompt: object) -> GeneratedAnswer | None:
            raise AssertionError("must not be called")

        def generate_stream(self, prompt: object) -> Iterator[str]:
            raise AssertionError("must not be called")

    empty = _response().model_copy(
        update={
            "answer": Answer(summary="No match.", claims=[]),
            "evidence": [],
        }
    )

    assert (
        EvidenceGroundedExplanationService(_Exploding()).explain(empty, question="q")
        is empty
    )


def test_provider_failure_preserves_the_original_answer() -> None:
    original = _response()

    generated = EvidenceGroundedExplanationService(
        ExplodingProvider(GeneratedAnswer(summary="unused", claims=()))
    ).explain(original, question="What places an order?")

    assert generated.answer == original.answer
    assert ANSWER_GENERATION_FAILED_WARNING in generated.warnings

