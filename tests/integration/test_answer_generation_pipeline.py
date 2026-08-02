"""Pipeline steps 14-15: optional evidence-grounded generation."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import QueryResponse
from codeatlas.conversations.pipeline import (
    AnswerPipeline,
    AnswerRequest,
    PipelineEvent,
)
from codeatlas.generation.providers import GeneratedAnswer, GeneratedClaim
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


class RecordingExplainer:
    def __init__(self) -> None:
        self.questions: list[str] = []

    def explain(
        self,
        response: QueryResponse,
        *,
        question: str,
        on_token: Callable[[str], None] | None = None,
    ) -> QueryResponse:
        self.questions.append(question)
        return response


class Fixture(NamedTuple):
    services: object
    repository_id: str


@pytest.fixture()
def fixture(tmp_path: Path, sample_repo: Path) -> Iterator[Fixture]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        services.indexing.index(repository.repository_id)
        yield Fixture(services=services, repository_id=repository.repository_id)


def _pipeline(fixture: Fixture, explainer: RecordingExplainer) -> AnswerPipeline:
    return AnswerPipeline(
        lookup=fixture.services.lookup,  # type: ignore[attr-defined]
        graph=fixture.services.graph,  # type: ignore[attr-defined]
        search=fixture.services.search,  # type: ignore[attr-defined]
        explainer=explainer,
    )


def test_conceptual_questions_reach_the_optional_explainer(
    fixture: Fixture,
) -> None:
    explainer = RecordingExplainer()

    _pipeline(fixture, explainer).execute(
        AnswerRequest(
            repository_id=fixture.repository_id,
            question="how does capture work",
            request_id="req_1",
        )
    )

    assert explainer.questions == ["how does capture work"]


@pytest.mark.parametrize(
    "question",
    [
        "PaymentService.capture",
        "who calls capture",
        "dependencies of capture",
        "what changed",
    ],
)
def test_resolved_intents_also_reach_the_explainer(
    fixture: Fixture, question: str
) -> None:
    """Every intent is eligible, including the deterministic ones.

    This test asserted the opposite until generation became prose-only. The
    reason it could change is that the explainer no longer touches claims: a
    resolved intent keeps its exact result and its citations whether or not a
    model writes the paragraph above them. What must never happen is a
    *retrieval* channel reaching a resolved intent, which `SEMANTIC_INTENTS`
    still prevents.
    """
    explainer = RecordingExplainer()

    _pipeline(fixture, explainer).execute(
        AnswerRequest(
            repository_id=fixture.repository_id,
            question=question,
            request_id="req_1",
        )
    )

    assert explainer.questions == [question]


def test_generated_tokens_are_emitted_as_stream_events(fixture: Fixture) -> None:
    class _Streaming:
        def explain(
            self,
            response: QueryResponse,
            *,
            question: str,
            on_token: Callable[[str], None] | None = None,
        ) -> QueryResponse:
            if on_token is not None:
                on_token("Hello ")
                on_token("world")
            return response

    events: list[PipelineEvent] = []

    _pipeline(fixture, _Streaming()).execute(  # type: ignore[arg-type]
        AnswerRequest(
            repository_id=fixture.repository_id,
            question="what is this project",
            request_id="req_2",
        ),
        on_event=events.append,
    )

    deltas = [
        event.payload["text"]
        for event in events
        if event.stage == "generation.delta" and "text" in event.payload
    ]
    assert "".join(str(delta) for delta in deltas) == "Hello world"


def test_every_pipeline_stage_has_a_stream_mapping() -> None:
    """An unmapped stage raises KeyError at publish time and fails the run.

    `conversation_service` publishes with `_STREAM_STAGES[event.stage]`, so a
    stage the pipeline emits but the table omits does not drop an event — it
    kills the answer. Cheap to assert, invisible until a run executes.
    """
    from codeatlas.application.conversation_service import _STREAM_STAGES

    for stage in (
        "retrieval.started",
        "retrieval.progress",
        "generation.delta",
        "answer.completed",
    ):
        assert stage in _STREAM_STAGES


def test_container_leaves_generation_out_by_default(
    fixture: Fixture,
) -> None:
    conversation = fixture.services.conversations.create(  # type: ignore[attr-defined]
        fixture.repository_id
    )

    result = fixture.services.conversations.submit(  # type: ignore[attr-defined]
        conversation.conversation_id, "how is a payment captured here"
    )

    assert result.status.value == "complete"


def test_generated_answer_remains_contract_valid(fixture: Fixture) -> None:
    from codeatlas.generation.explanations import EvidenceGroundedExplanationService

    class Provider:
        model_id = "fake-answer"
        prompt_version = "prompt-v1"

        def generate(self, prompt: object) -> GeneratedAnswer:
            evidence_id = prompt.evidence[0].evidence_id  # type: ignore[attr-defined]
            return GeneratedAnswer(
                summary="The generated answer cites verified evidence.",
                claims=(
                    GeneratedClaim(
                        text="The generated claim cites the returned evidence.",
                        evidence_ids=(evidence_id,),
                    ),
                ),
            )

        def generate_stream(self, prompt: object) -> Iterator[str]:
            yield "The generated answer cites verified evidence."

    pipeline = AnswerPipeline(
        lookup=fixture.services.lookup,  # type: ignore[attr-defined]
        graph=fixture.services.graph,  # type: ignore[attr-defined]
        search=fixture.services.search,  # type: ignore[attr-defined]
        explainer=EvidenceGroundedExplanationService(Provider()),
    )

    result = pipeline.execute(
        AnswerRequest(
            repository_id=fixture.repository_id,
            question="how does capture work",
            request_id="req_1",
        )
    )

    assert result.response.answer.summary == (
        "The generated answer cites verified evidence."
    )
