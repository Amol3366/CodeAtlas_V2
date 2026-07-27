"""Phase 5 conversation contract models (ADR-0006 decisions 1, 2, 4).

These are additive: `contract_version` stays "1.0", and a client written
against Phase 4 keeps working against a backend that never serves a
conversation. The rules asserted here are the ones the persistence and stream
layers depend on, so a later task cannot quietly weaken them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from codeatlas.contracts import (
    CONTRACT_VERSION,
    Conversation,
    ConversationPage,
    Derivation,
    Message,
    MessageEvidenceItem,
    MessagePage,
    MessageRole,
    MessageRun,
    MessageStatus,
    RunStatus,
    StreamEvent,
    StreamEventType,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _conversation(**overrides: object) -> Conversation:
    payload: dict[str, object] = {
        "conversation_id": "conv_1",
        "repository_id": "repo_1",
        "title": "What changed?",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return Conversation(**payload)  # type: ignore[arg-type]


def _message(**overrides: object) -> Message:
    payload: dict[str, object] = {
        "message_id": "msg_1",
        "conversation_id": "conv_1",
        "role": MessageRole.USER,
        "status": MessageStatus.COMPLETE,
        "sequence_number": 1,
        "content": "Who calls PaymentService.capture?",
        "created_at": NOW,
    }
    payload.update(overrides)
    return Message(**payload)  # type: ignore[arg-type]


def test_models_are_frozen_and_reject_unknown_fields() -> None:
    conversation = _conversation()
    with pytest.raises(ValidationError):
        Conversation(**{**conversation.model_dump(), "unexpected": 1})
    with pytest.raises(ValidationError):
        conversation.title = "other"


def test_timestamps_must_be_utc() -> None:
    naive = datetime(2026, 7, 27, 12, 0)
    with pytest.raises(ValidationError):
        _conversation(created_at=naive)
    offset = datetime(2026, 7, 27, 12, 0, tzinfo=UTC).astimezone()
    if offset.utcoffset() != timedelta(0):
        with pytest.raises(ValidationError):
            _conversation(created_at=offset)


def test_a_sequence_number_starts_at_one() -> None:
    """Sequence numbers order a conversation and are the stream's resume key;
    zero would make "no messages yet" and "the first message" the same value."""
    with pytest.raises(ValidationError):
        _message(sequence_number=0)


def test_an_assistant_message_may_be_empty_until_it_completes() -> None:
    queued = _message(
        role=MessageRole.ASSISTANT, status=MessageStatus.QUEUED, content=""
    )
    assert queued.content == ""
    assert queued.completed_at is None


def test_a_complete_assistant_message_requires_content() -> None:
    """A completed answer with no text is the silent-success failure mode the
    evidence contract exists to prevent."""
    with pytest.raises(ValidationError):
        _message(
            role=MessageRole.ASSISTANT,
            status=MessageStatus.COMPLETE,
            content="",
            completed_at=NOW,
        )


def test_a_failed_message_carries_its_error_code() -> None:
    failed = _message(
        role=MessageRole.ASSISTANT,
        status=MessageStatus.FAILED,
        content="",
        error_code="SNAPSHOT_NOT_READY",
        completed_at=NOW,
    )
    assert failed.error_code == "SNAPSHOT_NOT_READY"
    with pytest.raises(ValidationError):
        _message(
            role=MessageRole.ASSISTANT, status=MessageStatus.FAILED, content=""
        )


def test_a_run_records_the_snapshot_it_answered_against() -> None:
    """Snapshot binding is what lets a historical message keep its own
    freshness label forever (Section 14.5)."""
    run = MessageRun(
        run_id="run_1",
        message_id="msg_2",
        repository_id="repo_1",
        snapshot_id="snap_1",
        normalized_query="who calls paymentservice.capture",
        intent="callers",
        retrieval_policy_version="5.0",
        status=RunStatus.COMPLETE,
        created_at=NOW,
        completed_at=NOW,
        latency_ms=42.0,
    )
    assert run.snapshot_id == "snap_1"
    assert run.warnings == []


def test_message_evidence_carries_its_citation_ordinal_and_snapshot() -> None:
    item = MessageEvidenceItem(
        evidence_id="ev_1",
        citation_ordinal=1,
        file_path="src/payments/service.py",
        symbol="PaymentService.capture",
        start_line=7,
        end_line=8,
        content_hash="abc123",
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
        snapshot_id="snap_1",
    )
    assert item.citation_ordinal == 1
    with pytest.raises(ValidationError):
        MessageEvidenceItem(
            evidence_id="ev_1",
            citation_ordinal=0,
            file_path="src/payments/service.py",
            start_line=7,
            end_line=8,
            content_hash="abc123",
            derivation=Derivation.DETERMINISTIC,
            confidence=1.0,
            snapshot_id="snap_1",
        )


def test_evidence_line_range_must_not_invert() -> None:
    with pytest.raises(ValidationError):
        MessageEvidenceItem(
            evidence_id="ev_1",
            citation_ordinal=1,
            file_path="src/payments/service.py",
            start_line=9,
            end_line=8,
            content_hash="abc123",
            derivation=Derivation.DETERMINISTIC,
            confidence=1.0,
            snapshot_id="snap_1",
        )


def test_a_stream_event_carries_the_envelope_and_a_typed_payload() -> None:
    event = StreamEvent(
        contract_version=CONTRACT_VERSION,
        request_id="req_1",
        conversation_id="conv_1",
        message_id="msg_2",
        sequence=3,
        timestamp=NOW,
        event=StreamEventType.RETRIEVAL_PROGRESS,
        payload={"channel": "graph", "candidates": 4},
    )
    assert event.event is StreamEventType.RETRIEVAL_PROGRESS
    assert event.sequence == 3


def test_every_section_11_2_event_type_exists() -> None:
    """The event vocabulary is a published contract; a client ignores unknown
    types, but the ones the spec names must be present."""
    assert {item.value for item in StreamEventType} == {
        "run.accepted",
        "retrieval.started",
        "retrieval.progress",
        "evidence.available",
        "generation.delta",
        "answer.completed",
        "run.warning",
        "run.failed",
        "run.cancelled",
        "heartbeat",
    }


def test_pages_carry_an_opaque_cursor() -> None:
    conversations = ConversationPage(items=[_conversation()], next_cursor=None)
    messages = MessagePage(items=[_message()], next_cursor="opaque")
    assert conversations.next_cursor is None
    assert messages.next_cursor == "opaque"
