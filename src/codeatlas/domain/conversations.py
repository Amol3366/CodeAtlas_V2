"""Conversation, message, and run records.

These are the stored shapes of chat history. They mirror the public contract
models in :mod:`codeatlas.contracts` but stay separate for the reason every
other domain module does: storage rows change for storage reasons, and a
published contract must not move because a column did.

The invariants worth stating here, because the rest of Phase 5 depends on them:

- ``sequence_number`` starts at 1 and is unique within a conversation. It orders
  the thread and is the stream's resume key, so 0 means "nothing yet".
- A run records the snapshot it answered against. That is what lets a historical
  message keep its own freshness label after the tree has moved on.
- Evidence rows carry their fields rather than pointing at live index rows, so a
  citation cannot be silently re-resolved against a snapshot the answer never
  examined.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from codeatlas.contracts import (
    Derivation,
    MessageRole,
    MessageStatus,
    RunStatus,
)

# The repository corpus is never duplicated into chat rows (`AGENTS.md`
# Section 15). The bound is generous for an answer and far too small for a file.
MAX_MESSAGE_CONTENT_BYTES: int = 64 * 1024
MAX_WARNINGS_BYTES: int = 8 * 1024

@dataclass(frozen=True)
class Page[T]:
    """One page of results plus the cursor that continues it.

    ``next_cursor`` is opaque to callers: it encodes the ordering key of the
    last item, so a page boundary stays stable when rows are inserted above it.
    """

    items: tuple[T, ...] = ()
    next_cursor: str | None = None


@dataclass(frozen=True)
class ConversationRecord:
    """One persisted thread, always bound to a single repository.

    A conversation never changes repository: switching requires a new thread, so
    a historical answer can never be reinterpreted against a repository it did
    not examine.
    """

    conversation_id: str
    repository_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None
    archived_at: datetime | None = None
    deleted_at: datetime | None = None
    pinned_snapshot_policy: str | None = None


@dataclass(frozen=True)
class MessageRecord:
    """One turn in a conversation."""

    message_id: str
    conversation_id: str
    role: MessageRole
    status: MessageStatus
    sequence_number: int
    content: str
    created_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class RunRecord:
    """One attempt at answering a message.

    A retry creates another run rather than rewriting this one: what was already
    attempted, and why it failed, is part of the record a user can inspect.
    """

    run_id: str
    message_id: str
    repository_id: str
    snapshot_id: str
    intent: str
    retrieval_policy_version: str
    status: RunStatus
    created_at: datetime
    normalized_query: str = ""
    latency_ms: float | None = None
    warnings: tuple[str, ...] = ()
    completed_at: datetime | None = None


@dataclass(frozen=True)
class MessageEvidenceRow:
    """One citation attached to an assistant message.

    The fields are snapshotted rather than joined, so this row still says what
    it said after its snapshot is superseded.
    """

    evidence_id: str
    citation_ordinal: int
    file_path: str
    start_line: int
    end_line: int
    content_hash: str
    derivation: Derivation
    confidence: float
    snapshot_id: str
    symbol: str | None = None
    claim_ids: tuple[str, ...] = field(default_factory=tuple)


__all__ = [
    "MAX_MESSAGE_CONTENT_BYTES",
    "MAX_WARNINGS_BYTES",
    "ConversationRecord",
    "MessageEvidenceRow",
    "MessageRecord",
    "Page",
    "RunRecord",
]
