"""Conversation lifecycle: create, list, read, rename, archive, delete.

This is the history half of the conversation surface. Submitting a message and
running the answer pipeline arrive in P5-03; keeping them apart means the web
client can build its sidebar against a service that cannot fail for retrieval
reasons.

Two rules shape everything here:

- **A conversation is bound to one repository for its whole life.** The binding
  is checked at creation, not at first question, because a thread whose
  repository never existed would only reveal the problem once a user had typed
  something into it.
- **A deleted conversation is gone to every caller.** Storage keeps the row so
  Phase 6 can define recovery, but every read path treats it as absent:
  reporting it because it physically survives would contradict what the user
  was told.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Connection

from codeatlas.contracts import (
    Derivation,
    MessageRole,
    MessageStatus,
    RunStatus,
    StreamEventType,
)
from codeatlas.conversations.events import EventHub
from codeatlas.conversations.pipeline import (
    AnswerPipeline,
    AnswerRequest,
    CancelledError,
    CancelToken,
    PipelineEvent,
)
from codeatlas.domain.conversations import (
    ConversationRecord,
    MessageEvidenceRow,
    MessageRecord,
    Page,
    RunRecord,
)
from codeatlas.domain.errors import (
    CodeAtlasError,
    ConversationArchivedError,
    ConversationNotFoundError,
    InvalidRequestError,
    MessageNotFoundError,
    RepositoryNotFoundError,
    RunNotCancellableError,
    RunNotRetryableError,
)
from codeatlas.storage.sqlite.connection import write_transaction
from codeatlas.storage.sqlite.stores import ConversationStore, RepositoryStore

# A title is a label in a sidebar, not a document. The bound is generous for a
# sentence and far too small for pasted content.
MAX_TITLE_CHARACTERS: int = 200

# Deterministic titles only (ADR-0006 decision 8): the first user message,
# truncated at a word boundary. Until a message exists, a new thread is named
# for what it is.
DEFAULT_TITLE: str = "New conversation"

MAX_PAGE_LIMIT: int = 100
DEFAULT_PAGE_LIMIT: int = 50

# Pipeline stage names mapped onto the published Section 11.2 vocabulary. The
# pipeline names its own stages; this table is where they become a contract, so
# a renamed stage cannot silently change what a client receives.
_STREAM_STAGES: dict[str, StreamEventType] = {
    "retrieval.started": StreamEventType.RETRIEVAL_STARTED,
    "retrieval.progress": StreamEventType.RETRIEVAL_PROGRESS,
    "generation.delta": StreamEventType.GENERATION_DELTA,
}


def derive_title(text: str) -> str:
    """Name a thread after its first question, truncated at a word boundary.

    Deterministic by construction: the same first message always produces the
    same title, so a title can never become a claim about the repository that
    nothing supports.
    """
    normalized = " ".join(text.split())
    if not normalized:
        return DEFAULT_TITLE
    if len(normalized) <= 60:
        return normalized
    clipped = normalized[:60]
    boundary = clipped.rfind(" ")
    if boundary >= 20:
        clipped = clipped[:boundary]
    return f"{clipped.rstrip()}…"


@dataclass(frozen=True)
class SubmissionResult:
    """One completed turn: the IDs, the answer, and everything it cites."""

    conversation_id: str
    user_message_id: str
    message_id: str
    run_id: str
    status: MessageStatus
    sequence_number: int
    content: str
    intent: str
    snapshot_id: str | None = None
    evidence: tuple[MessageEvidenceRow, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    error_code: str | None = None
    latency_ms: float | None = None


class ConversationService:
    """Create and manage conversation threads for a registered repository."""

    def __init__(
        self,
        repositories: RepositoryStore,
        conversations: ConversationStore,
        connection: Connection,
        pipeline: AnswerPipeline | None = None,
        hub: EventHub | None = None,
    ) -> None:
        self._repositories = repositories
        self._conversations = conversations
        self._connection = connection
        self._pipeline = pipeline
        self._hub = hub

    @property
    def hub(self) -> EventHub | None:
        """The live-run registry, for the stream adapter."""
        return self._hub

    def create(
        self,
        repository_id: str,
        *,
        title: str | None = None,
    ) -> ConversationRecord:
        """Open a thread against a repository that exists right now."""
        self._require_repository(repository_id)
        resolved = self._validate_title(title) if title is not None else DEFAULT_TITLE

        now = datetime.now(UTC)
        record = ConversationRecord(
            conversation_id=f"conv_{uuid.uuid4().hex}",
            repository_id=repository_id,
            title=resolved,
            created_at=now,
            updated_at=now,
        )
        with write_transaction(self._connection):
            self._conversations.create_conversation(record)
        return record

    def get(self, conversation_id: str) -> ConversationRecord:
        record = self._conversations.get_conversation(conversation_id)
        if record is None:
            raise ConversationNotFoundError(
                "No conversation matches that ID.",
                details={"conversation_id": conversation_id},
            )
        return record

    def list(
        self,
        repository_id: str,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        include_archived: bool = False,
    ) -> Page[ConversationRecord]:
        self._require_repository(repository_id)
        return self._conversations.list_conversations(
            repository_id,
            cursor=cursor,
            limit=self._validate_limit(limit),
            include_archived=include_archived,
        )

    def rename(self, conversation_id: str, title: str) -> ConversationRecord:
        self.get(conversation_id)
        resolved = self._validate_title(title)
        with write_transaction(self._connection):
            self._conversations.rename(
                conversation_id, title=resolved, updated_at=datetime.now(UTC)
            )
        return self.get(conversation_id)

    def archive(self, conversation_id: str) -> ConversationRecord:
        """Mark a thread finished. It stays readable by ID and by explicit ask."""
        self.get(conversation_id)
        with write_transaction(self._connection):
            self._conversations.archive(
                conversation_id, archived_at=datetime.now(UTC)
            )
        return self.get(conversation_id)

    def delete(self, conversation_id: str) -> None:
        """Remove a thread from every read path, keeping the rows recoverable."""
        self.get(conversation_id)
        with write_transaction(self._connection):
            self._conversations.soft_delete(
                conversation_id, deleted_at=datetime.now(UTC)
            )

    def list_messages(
        self,
        conversation_id: str,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> Page[MessageRecord]:
        self.get(conversation_id)
        return self._conversations.list_messages(
            conversation_id, cursor=cursor, limit=self._validate_limit(limit)
        )

    def submit(
        self,
        conversation_id: str,
        content: str,
        *,
        request_id: str = "",
        on_event: object = None,
        cancel: CancelToken | None = None,
    ) -> SubmissionResult:
        """Record a question, answer it, and commit both.

        The turn is written before retrieval starts, so a failure mid-answer
        leaves a visible question with a failed answer attached rather than
        losing what the user typed. The answer and its citations are committed
        together afterwards.
        """
        conversation = self.get(conversation_id)
        if conversation.archived_at is not None:
            raise ConversationArchivedError(
                "This conversation is archived and accepts no new messages.",
                details={"conversation_id": conversation_id},
            )
        question = content.strip()
        if not question:
            raise InvalidRequestError("A message cannot be empty.")

        now = datetime.now(UTC)
        sequence = self._conversations.next_sequence_number(conversation_id)
        user_message_id = f"msg_{uuid.uuid4().hex}"
        assistant_message_id = f"msg_{uuid.uuid4().hex}"
        run_id = f"run_{uuid.uuid4().hex}"
        resolved_request_id = request_id or f"conv_{uuid.uuid4().hex}"

        # Classification happens before the turn is written so an unanswerable
        # question (too long, empty) is refused without leaving a turn behind.
        from codeatlas.conversations.intent import classify

        classification = classify(question)

        with write_transaction(self._connection):
            if conversation.title == DEFAULT_TITLE:
                self._conversations.rename(
                    conversation_id, title=derive_title(question), updated_at=now
                )
            self._conversations.create_user_turn(
                MessageRecord(
                    message_id=user_message_id,
                    conversation_id=conversation_id,
                    role=MessageRole.USER,
                    status=MessageStatus.COMPLETE,
                    sequence_number=sequence,
                    content=question,
                    created_at=now,
                    completed_at=now,
                ),
                MessageRecord(
                    message_id=assistant_message_id,
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    status=MessageStatus.QUEUED,
                    sequence_number=sequence + 1,
                    content="",
                    created_at=now,
                ),
                RunRecord(
                    run_id=run_id,
                    message_id=assistant_message_id,
                    repository_id=conversation.repository_id,
                    # Replaced with the answering snapshot on completion; a
                    # queued run has not resolved one yet.
                    snapshot_id="pending",
                    normalized_query=question.lower(),
                    intent=classification.intent.value,
                    retrieval_policy_version=classification.policy_version,
                    status=RunStatus.QUEUED,
                    created_at=now,
                ),
            )

        return self._execute_run(
            conversation=conversation,
            user_message_id=user_message_id,
            message_id=assistant_message_id,
            run_id=run_id,
            question=question,
            sequence=sequence + 1,
            request_id=resolved_request_id,
            intent=classification.intent.value,
            cancel=cancel,
        )

    def retry(self, message_id: str, *, request_id: str = "") -> SubmissionResult:
        """Answer a failed or cancelled message again, preserving the old run."""
        message = self._conversations.get_message(message_id)
        if message is None:
            raise MessageNotFoundError(
                "No message matches that ID.", details={"message_id": message_id}
            )
        if message.status not in {MessageStatus.FAILED, MessageStatus.CANCELLED}:
            raise RunNotRetryableError(
                "Only a failed or cancelled message can be retried.",
                details={"message_id": message_id, "status": message.status.value},
            )
        conversation = self.get(message.conversation_id)
        question = self._question_for(message)

        from codeatlas.conversations.intent import classify

        classification = classify(question)
        run_id = f"run_{uuid.uuid4().hex}"
        with write_transaction(self._connection):
            self._conversations.create_retry_run(
                message_id,
                RunRecord(
                    run_id=run_id,
                    message_id=message_id,
                    repository_id=conversation.repository_id,
                    snapshot_id="pending",
                    normalized_query=question.lower(),
                    intent=classification.intent.value,
                    retrieval_policy_version=classification.policy_version,
                    status=RunStatus.QUEUED,
                    created_at=datetime.now(UTC),
                ),
            )

        return self._execute_run(
            conversation=conversation,
            user_message_id="",
            message_id=message_id,
            run_id=run_id,
            question=question,
            sequence=message.sequence_number,
            request_id=request_id or f"conv_{uuid.uuid4().hex}",
            intent=classification.intent.value,
            cancel=None,
        )

    def save_feedback(
        self, message_id: str, *, rating: str, reason_code: str | None = None
    ) -> None:
        if self._conversations.get_message(message_id) is None:
            raise MessageNotFoundError(
                "No message matches that ID.", details={"message_id": message_id}
            )
        if rating not in {"up", "down"}:
            raise InvalidRequestError("rating must be 'up' or 'down'.")
        with write_transaction(self._connection):
            self._conversations.save_feedback(
                message_id,
                rating=rating,
                reason_code=reason_code,
                created_at=datetime.now(UTC),
            )

    def cancel_run(self, run_id: str) -> None:
        """Ask an in-flight run to stop at its next checkpoint.

        Cancellation is cooperative, so this returns as soon as the flag is
        set. The run's own terminal event is what tells a client it stopped —
        the UI must never paint a cancelled state ahead of the server.
        """
        channel = self._hub.get(run_id) if self._hub else None
        if channel is None or channel.terminal:
            raise RunNotCancellableError(
                "That run is not in flight.", details={"run_id": run_id}
            )
        channel.cancel.cancel()

    def _execute_run(
        self,
        *,
        conversation: ConversationRecord,
        user_message_id: str,
        message_id: str,
        run_id: str,
        question: str,
        sequence: int,
        request_id: str,
        intent: str,
        cancel: CancelToken | None,
    ) -> SubmissionResult:
        """Run the pipeline and commit whatever outcome it reaches."""
        if self._pipeline is None:  # pragma: no cover - wiring guard
            raise InvalidRequestError("Answering is not available.")

        channel = None
        if self._hub is not None:
            channel = self._hub.open(
                run_id=run_id,
                request_id=request_id,
                conversation_id=conversation.conversation_id,
                message_id=message_id,
            )
            channel.publish(
                StreamEventType.RUN_ACCEPTED,
                {"run_id": run_id, "intent": intent},
            )
            # A caller-supplied token wins; otherwise the channel's token is
            # the one `cancel_run` can reach.
            cancel = cancel or channel.cancel

        def relay(event: PipelineEvent) -> None:
            if channel is None:
                return
            channel.publish(_STREAM_STAGES[event.stage], dict(event.payload))

        try:
            result = self._pipeline.execute(
                AnswerRequest(
                    repository_id=conversation.repository_id,
                    question=question,
                    request_id=request_id,
                ),
                on_event=relay,
                cancel=cancel,
            )
        except CancelledError:
            if channel is not None:
                channel.publish(StreamEventType.RUN_CANCELLED, {"run_id": run_id})
            return self._terminate(
                conversation_id=conversation.conversation_id,
                user_message_id=user_message_id,
                message_id=message_id,
                run_id=run_id,
                sequence=sequence,
                intent=intent,
                status=MessageStatus.CANCELLED,
                error_code=None,
            )
        except CodeAtlasError as error:
            # A retrieval failure is the answer's outcome, not the request's:
            # the turn stays visible and retryable rather than vanishing.
            if channel is not None:
                channel.publish(
                    StreamEventType.RUN_FAILED,
                    {"run_id": run_id, "error_code": error.code.value},
                )
            return self._terminate(
                conversation_id=conversation.conversation_id,
                user_message_id=user_message_id,
                message_id=message_id,
                run_id=run_id,
                sequence=sequence,
                intent=intent,
                status=MessageStatus.FAILED,
                error_code=error.code.value,
            )

        snapshot_id = result.response.snapshot.snapshot_id
        evidence = tuple(
            MessageEvidenceRow(
                evidence_id=item.evidence_id,
                citation_ordinal=ordinal,
                file_path=item.file_path,
                symbol=item.symbol,
                start_line=item.start_line,
                end_line=item.end_line,
                content_hash=item.content_hash,
                derivation=Derivation(item.derivation),
                confidence=item.confidence,
                snapshot_id=item.snapshot_id,
            )
            for ordinal, item in enumerate(result.response.evidence, start=1)
        )
        completed_at = datetime.now(UTC)
        with write_transaction(self._connection):
            self._conversations.complete_assistant(
                message_id=message_id,
                content=result.markdown,
                evidence=evidence,
                run_id=run_id,
                latency_ms=result.latency_ms,
                completed_at=completed_at,
            )
            self._conversations.set_run_snapshot(run_id, snapshot_id)

        if channel is not None:
            channel.publish(
                StreamEventType.EVIDENCE_AVAILABLE,
                {"count": len(evidence)},
            )
            for warning in result.response.warnings:
                channel.publish(StreamEventType.RUN_WARNING, {"warning": warning})
            # Published only after the message is committed: the persisted
            # answer is the authoritative one, so a client must never be told
            # the run completed before that answer exists.
            channel.publish(
                StreamEventType.ANSWER_COMPLETED,
                {"message_id": message_id, "snapshot_id": snapshot_id},
            )

        return SubmissionResult(
            conversation_id=conversation.conversation_id,
            user_message_id=user_message_id,
            message_id=message_id,
            run_id=run_id,
            status=MessageStatus.COMPLETE,
            sequence_number=sequence,
            content=result.markdown,
            intent=result.intent.value,
            snapshot_id=snapshot_id,
            evidence=evidence,
            warnings=tuple(result.response.warnings),
            limitations=tuple(result.response.limitations),
            latency_ms=result.latency_ms,
        )

    def _terminate(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        message_id: str,
        run_id: str,
        sequence: int,
        intent: str,
        status: MessageStatus,
        error_code: str | None,
    ) -> SubmissionResult:
        with write_transaction(self._connection):
            self._conversations.fail_or_cancel(
                message_id=message_id,
                run_id=run_id,
                status=status,
                error_code=error_code,
                completed_at=datetime.now(UTC),
            )
        return SubmissionResult(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            message_id=message_id,
            run_id=run_id,
            status=status,
            sequence_number=sequence,
            content="",
            intent=intent,
            error_code=error_code,
        )

    def _question_for(self, message: MessageRecord) -> str:
        """The user message immediately preceding an assistant message."""
        page = self._conversations.list_messages(
            message.conversation_id, cursor=None, limit=MAX_PAGE_LIMIT
        )
        preceding = [
            item
            for item in page.items
            if item.role is MessageRole.USER
            and item.sequence_number < message.sequence_number
        ]
        if not preceding:
            raise RunNotRetryableError(
                "This message has no question to answer again.",
                details={"message_id": message.message_id},
            )
        return preceding[-1].content

    def _require_repository(self, repository_id: str) -> None:
        if self._repositories.get(repository_id) is None:
            raise RepositoryNotFoundError(
                "No repository matches that ID.",
                details={"repository_id": repository_id},
            )

    def _validate_title(self, title: str) -> str:
        cleaned = title.strip()
        if not cleaned:
            raise InvalidRequestError("A conversation title cannot be empty.")
        if len(cleaned) > MAX_TITLE_CHARACTERS:
            raise InvalidRequestError(
                "A conversation title is limited to "
                f"{MAX_TITLE_CHARACTERS} characters."
            )
        return cleaned

    def _validate_limit(self, limit: int) -> int:
        if limit < 1 or limit > MAX_PAGE_LIMIT:
            raise InvalidRequestError(
                f"limit must be between 1 and {MAX_PAGE_LIMIT}."
            )
        return limit


__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "DEFAULT_TITLE",
    "MAX_PAGE_LIMIT",
    "MAX_TITLE_CHARACTERS",
    "ConversationService",
    "derive_title",
]
