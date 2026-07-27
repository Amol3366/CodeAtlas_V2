"""Run execution: what happens to a turn when the answer succeeds or does not.

The pipeline itself is exercised through the parity suite. What matters here is
the *lifecycle*: a question is never lost, a failure stays visible and
retryable, a cancellation is explicit, and a completed answer is bound to the
snapshot that produced it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import MessageRole, MessageStatus, RunStatus
from codeatlas.conversations.pipeline import CancelToken
from codeatlas.domain.errors import (
    ConversationArchivedError,
    MessageNotFoundError,
    QueryTooLongError,
    RunNotRetryableError,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import ConversationStore


class Fixture(NamedTuple):
    """The wired services, an indexed repository, and a direct store handle."""

    services: ApplicationServices
    repository_id: str
    store: ConversationStore


@pytest.fixture()
def services(tmp_path: Path, sample_repo: Path) -> Iterator[Fixture]:
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        built = build_services(connection)
        repository = built.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        built.indexing.index(repository.repository_id)
        yield Fixture(built, repository.repository_id, ConversationStore(connection))


def test_a_question_and_its_answer_are_both_recorded(services: Fixture) -> None:
    built, repository_id, store = services
    conversation = built.conversations.create(repository_id)

    result = built.conversations.submit(
        conversation.conversation_id, "PaymentService.capture"
    )

    assert result.status is MessageStatus.COMPLETE
    page = built.conversations.list_messages(conversation.conversation_id)
    roles = [item.role for item in page.items]
    assert roles == [MessageRole.USER, MessageRole.ASSISTANT]
    assert page.items[0].content == "PaymentService.capture"
    assert page.items[1].content == result.content
    assert store.get_evidence(result.message_id)


def test_the_run_records_the_snapshot_that_answered(services: Fixture) -> None:
    """Not "pending": the queued placeholder must be replaced by the snapshot
    the answer actually examined, or a historical message could not keep its
    own freshness label."""
    built, repository_id, store = services
    conversation = built.conversations.create(repository_id)

    result = built.conversations.submit(
        conversation.conversation_id, "PaymentService.capture"
    )

    runs = store.list_runs(result.message_id)
    assert len(runs) == 1
    assert runs[0].status is RunStatus.COMPLETE
    assert runs[0].snapshot_id == result.snapshot_id
    assert runs[0].snapshot_id != "pending"


def test_the_first_question_names_the_thread(services: Fixture) -> None:
    built, repository_id, _ = services
    conversation = built.conversations.create(repository_id)
    assert conversation.title == "New conversation"

    built.conversations.submit(
        conversation.conversation_id, "who calls PaymentService.capture"
    )

    renamed = built.conversations.get(conversation.conversation_id)
    assert renamed.title == "who calls PaymentService.capture"


def test_a_cancelled_run_leaves_an_explicit_cancelled_turn(
    services: Fixture,
) -> None:
    """Cancelling must not look like an empty answer."""
    built, repository_id, store = services
    conversation = built.conversations.create(repository_id)
    token = CancelToken()
    token.cancel()

    result = built.conversations.submit(
        conversation.conversation_id, "PaymentService.capture", cancel=token
    )

    assert result.status is MessageStatus.CANCELLED
    page = built.conversations.list_messages(conversation.conversation_id)
    # The question survives: what the user typed is not lost because the
    # answer was stopped.
    assert page.items[0].content == "PaymentService.capture"
    assert page.items[1].status is MessageStatus.CANCELLED
    assert store.list_runs(result.message_id)[0].status is RunStatus.CANCELLED


def test_a_cancelled_turn_can_be_retried(services: Fixture) -> None:
    built, repository_id, store = services
    conversation = built.conversations.create(repository_id)
    token = CancelToken()
    token.cancel()
    cancelled = built.conversations.submit(
        conversation.conversation_id, "PaymentService.capture", cancel=token
    )

    retried = built.conversations.retry(cancelled.message_id)

    assert retried.status is MessageStatus.COMPLETE
    assert retried.content
    runs = store.list_runs(cancelled.message_id)
    # Two attempts, the first preserved: the record of what already happened
    # is not rewritten by trying again.
    assert len(runs) == 2
    assert runs[0].status is RunStatus.CANCELLED
    assert runs[1].status is RunStatus.COMPLETE


def test_retrying_a_completed_message_is_refused(services: Fixture) -> None:
    """A second answer to one question would make the persisted answer
    ambiguous."""
    built, repository_id, _ = services
    conversation = built.conversations.create(repository_id)
    result = built.conversations.submit(
        conversation.conversation_id, "PaymentService.capture"
    )

    with pytest.raises(RunNotRetryableError):
        built.conversations.retry(result.message_id)


def test_retrying_an_unknown_message_is_not_found(services: Fixture) -> None:
    built, _, _ = services
    with pytest.raises(MessageNotFoundError):
        built.conversations.retry("msg_missing")


def test_an_archived_conversation_rejects_new_messages(services: Fixture) -> None:
    built, repository_id, _ = services
    conversation = built.conversations.create(repository_id)
    built.conversations.archive(conversation.conversation_id)

    with pytest.raises(ConversationArchivedError):
        built.conversations.submit(conversation.conversation_id, "capture")


def test_an_over_long_question_leaves_no_turn_behind(services: Fixture) -> None:
    """Refusal happens before anything is written, so a rejected question does
    not leave a half-thread the user has to clean up."""
    built, repository_id, _ = services
    conversation = built.conversations.create(repository_id)

    with pytest.raises(QueryTooLongError):
        built.conversations.submit(conversation.conversation_id, "x" * 5000)

    page = built.conversations.list_messages(conversation.conversation_id)
    assert page.items == ()


def test_an_unanswerable_question_completes_with_an_abstention(
    services: Fixture,
) -> None:
    """Abstention is a successful outcome, not a failure: the pipeline ran and
    honestly found nothing."""
    built, repository_id, _ = services
    conversation = built.conversations.create(repository_id)

    result = built.conversations.submit(
        conversation.conversation_id, "NoSuchSymbolAnywhere"
    )

    assert result.status is MessageStatus.COMPLETE
    assert result.evidence == ()
    assert "not answering rather than guessing" in result.content


def test_feedback_requires_a_known_message(services: Fixture) -> None:
    built, _, _ = services
    with pytest.raises(MessageNotFoundError):
        built.conversations.save_feedback("msg_missing", rating="up")


def test_answering_twice_is_byte_stable(services: Fixture) -> None:
    """An unchanged snapshot answers the same question the same way; anything
    else would make a retry look like a change in the repository."""
    built, repository_id, _ = services
    first_conversation = built.conversations.create(repository_id)
    second_conversation = built.conversations.create(repository_id)

    first = built.conversations.submit(
        first_conversation.conversation_id, "PaymentService.capture"
    )
    second = built.conversations.submit(
        second_conversation.conversation_id, "PaymentService.capture"
    )

    assert first.content == second.content
