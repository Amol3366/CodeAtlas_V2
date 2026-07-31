"""Pipeline steps 14-15: optional evidence-grounded generation."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import QueryResponse
from codeatlas.conversations.pipeline import AnswerPipeline, AnswerRequest
from codeatlas.generation.providers import GeneratedAnswer, GeneratedClaim
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


class RecordingExplainer:
    def __init__(self) -> None:
        self.questions: list[str] = []

    def explain(self, response: QueryResponse, *, question: str) -> QueryResponse:
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
def test_resolved_intents_do_not_reach_the_optional_explainer(
    fixture: Fixture, question: str
) -> None:
    explainer = RecordingExplainer()

    _pipeline(fixture, explainer).execute(
        AnswerRequest(
            repository_id=fixture.repository_id,
            question=question,
            request_id="req_1",
        )
    )

    assert explainer.questions == []


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
