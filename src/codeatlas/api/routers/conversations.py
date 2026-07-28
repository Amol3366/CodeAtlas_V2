"""Conversation routes: the history half of `AGENTS.md` Section 12.2.

Thin, like every other router. Each handler validates its input, calls
`ConversationService`, and serializes the stored record into the published
contract model; no history logic lives here.

Submitting a message, retrying, cancelling, and streaming arrive in P5-03 and
P5-04. Keeping them out means this surface cannot fail for retrieval reasons.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from codeatlas.api.errors import request_id_for
from codeatlas.api.routers.repositories import Services
from codeatlas.application.conversation_service import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    SubmissionResult,
)
from codeatlas.contracts import (
    Conversation,
    ConversationPage,
    Message,
    MessageEvidenceItem,
    MessagePage,
    MessageSubmission,
)
from codeatlas.domain.conversations import (
    ConversationRecord,
    MessageEvidenceRow,
    MessageRecord,
    RunRecord,
)

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])

_LIMIT = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT)
_CURSOR = Query(default=None)
_INCLUDE_ARCHIVED = Query(default=False)


class StrictModel(BaseModel):
    """Reject unknown fields at the HTTP boundary.

    A typo'd field must fail loudly: silently dropping it would let a client
    believe it set something it did not.
    """

    model_config = ConfigDict(extra="forbid")


class CreateConversationRequest(StrictModel):
    repository_id: str
    title: str | None = Field(default=None, max_length=200)


class UpdateConversationRequest(StrictModel):
    """Rename, archive, or both. Unarchiving is not offered yet: nothing in
    Phase 5 needs it, and an unused write path is an untested one."""

    title: str | None = Field(default=None, max_length=200)
    archived: bool | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
def create_conversation(
    services: Services, body: CreateConversationRequest
) -> Conversation:
    record = services.conversations.create(body.repository_id, title=body.title)
    return _conversation(record)


@router.get("")
def list_conversations(
    services: Services,
    repository_id: str,
    limit: int = _LIMIT,
    cursor: str | None = _CURSOR,
    include_archived: bool = _INCLUDE_ARCHIVED,
) -> ConversationPage:
    page = services.conversations.list(
        repository_id,
        cursor=cursor,
        limit=limit,
        include_archived=include_archived,
    )
    return ConversationPage(
        items=[_conversation(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/{conversation_id}")
def get_conversation(services: Services, conversation_id: str) -> Conversation:
    return _conversation(services.conversations.get(conversation_id))


@router.patch("/{conversation_id}")
def update_conversation(
    services: Services, conversation_id: str, body: UpdateConversationRequest
) -> Conversation:
    record = services.conversations.get(conversation_id)
    if body.title is not None:
        record = services.conversations.rename(conversation_id, body.title)
    if body.archived:
        record = services.conversations.archive(conversation_id)
    return _conversation(record)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(services: Services, conversation_id: str) -> Response:
    services.conversations.delete(conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class SubmitMessageRequest(StrictModel):
    content: str = Field(min_length=1, max_length=4000)


class FeedbackRequest(StrictModel):
    rating: str
    reason_code: str | None = None


@router.post(
    "/{conversation_id}/messages", status_code=status.HTTP_202_ACCEPTED
)
def submit_message(
    request: Request,
    services: Services,
    conversation_id: str,
    body: SubmitMessageRequest,
) -> MessageSubmission:
    """Accept a question and return its IDs; the run answers in the background.

    202, not 201: this acknowledges an accepted turn rather than presenting a
    finished one (`CLAUDE.md` Section 12.2, ADR-0008). The user message and the
    queued run are committed before this returns, so the IDs are durable and
    the stream is already live — a client may open it immediately without
    racing the worker. The persisted message stays authoritative; streamed text
    is provisional.
    """
    result = services.conversations.submit(
        conversation_id, body.content, request_id=request_id_for(request)
    )
    return _submission(result)


@router.post("/messages/{message_id}/retry", status_code=status.HTTP_201_CREATED)
def retry_message(
    request: Request, services: Services, message_id: str
) -> MessageSubmission:
    return _submission(
        services.conversations.retry(message_id, request_id=request_id_for(request))
    )


@router.post(
    "/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT
)
def submit_feedback(
    services: Services, message_id: str, body: FeedbackRequest
) -> Response:
    services.conversations.save_feedback(
        message_id, rating=body.rating, reason_code=body.reason_code
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{conversation_id}/messages")
def list_messages(
    services: Services,
    conversation_id: str,
    limit: int = _LIMIT,
    cursor: str | None = _CURSOR,
) -> MessagePage:
    page = services.conversations.list_messages(
        conversation_id, cursor=cursor, limit=limit
    )
    return MessagePage(
        items=[
            _message(
                item,
                services.conversations.get_evidence(item.message_id),
                services.conversations.latest_run(item.message_id),
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


def _submission(result: SubmissionResult) -> MessageSubmission:
    return MessageSubmission(
        conversation_id=result.conversation_id,
        user_message_id=result.user_message_id or result.message_id,
        message_id=result.message_id,
        run_id=result.run_id,
        status=result.status,
        sequence_number=result.sequence_number,
        content=result.content,
        snapshot_id=result.snapshot_id,
        intent=result.intent,
        evidence=[_evidence_item(item) for item in result.evidence],
        warnings=list(result.warnings),
        limitations=list(result.limitations),
        error_code=result.error_code,
        latency_ms=result.latency_ms,
    )


def _conversation(record: ConversationRecord) -> Conversation:
    return Conversation(
        conversation_id=record.conversation_id,
        repository_id=record.repository_id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_message_at=record.last_message_at,
        archived_at=record.archived_at,
    )


def _message(
    record: MessageRecord,
    evidence: Sequence[MessageEvidenceRow] = (),
    run: RunRecord | None = None,
) -> Message:
    return Message(
        message_id=record.message_id,
        conversation_id=record.conversation_id,
        role=record.role,
        status=record.status,
        sequence_number=record.sequence_number,
        content=record.content,
        error_code=record.error_code,
        created_at=record.created_at,
        completed_at=record.completed_at,
        evidence=[_evidence_item(item) for item in evidence],
        # 'pending' is the placeholder a queued run carries until it
        # resolves one; reporting it as a snapshot ID would be a lie.
        snapshot_id=(
            run.snapshot_id
            if run is not None and run.snapshot_id != "pending"
            else None
        ),
        warnings=list(run.warnings) if run is not None else [],
    )


def _evidence_item(item: MessageEvidenceRow) -> MessageEvidenceItem:
    return MessageEvidenceItem(
        evidence_id=item.evidence_id,
        citation_ordinal=item.citation_ordinal,
        file_path=item.file_path,
        symbol=item.symbol,
        start_line=item.start_line,
        end_line=item.end_line,
        content_hash=item.content_hash,
        derivation=item.derivation,
        confidence=item.confidence,
        snapshot_id=item.snapshot_id,
    )
