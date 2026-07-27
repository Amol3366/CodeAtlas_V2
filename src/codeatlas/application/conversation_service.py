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
from datetime import UTC, datetime
from sqlite3 import Connection

from codeatlas.domain.conversations import ConversationRecord, MessageRecord, Page
from codeatlas.domain.errors import (
    ConversationNotFoundError,
    InvalidRequestError,
    RepositoryNotFoundError,
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


class ConversationService:
    """Create and manage conversation threads for a registered repository."""

    def __init__(
        self,
        repositories: RepositoryStore,
        conversations: ConversationStore,
        connection: Connection,
    ) -> None:
        self._repositories = repositories
        self._conversations = conversations
        self._connection = connection

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
