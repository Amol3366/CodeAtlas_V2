"""Conversation persistence against real SQLite (P5-01, ADR-0006 decisions 1-2).

Chat history is first-class application data, so these tests are about the
guarantees a user would notice if they broke: a thread that keeps its order, a
turn that is either fully recorded or not recorded at all, a deletion that
stays deleted, and an answer whose citations still say what they said after the
snapshot moved on.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codeatlas.contracts import (
    Derivation,
    MessageRole,
    MessageStatus,
    RunStatus,
)
from codeatlas.domain.conversations import (
    ConversationRecord,
    MessageEvidenceRow,
    MessageRecord,
    RunRecord,
)
from codeatlas.storage.sqlite.connection import connect, write_transaction
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import ConversationStore

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with connect(tmp_path / "db.sqlite") as handle:
        apply_migrations(handle)
        handle.execute(
            "INSERT INTO repositories"
            " (repository_id, display_name, canonical_root, created_at)"
            " VALUES (?, ?, ?, ?)",
            ("repo_1", "demo", "C:/repos/demo", "2026-07-25T00:00:00Z"),
        )
        yield handle


@pytest.fixture
def store(connection: sqlite3.Connection) -> ConversationStore:
    return ConversationStore(connection)


def _conversation(
    conversation_id: str = "conv_1", **overrides: object
) -> ConversationRecord:
    payload: dict[str, object] = {
        "conversation_id": conversation_id,
        "repository_id": "repo_1",
        "title": "What changed?",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return ConversationRecord(**payload)  # type: ignore[arg-type]


def _user_message(message_id: str = "msg_1", sequence: int = 1) -> MessageRecord:
    return MessageRecord(
        message_id=message_id,
        conversation_id="conv_1",
        role=MessageRole.USER,
        status=MessageStatus.COMPLETE,
        sequence_number=sequence,
        content="Who calls PaymentService.capture?",
        created_at=NOW,
        completed_at=NOW,
    )


def _assistant_message(
    message_id: str = "msg_2", sequence: int = 2
) -> MessageRecord:
    return MessageRecord(
        message_id=message_id,
        conversation_id="conv_1",
        role=MessageRole.ASSISTANT,
        status=MessageStatus.QUEUED,
        sequence_number=sequence,
        content="",
        created_at=NOW,
    )


def _run(run_id: str = "run_1", message_id: str = "msg_2") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        message_id=message_id,
        repository_id="repo_1",
        snapshot_id="snap_1",
        normalized_query="who calls paymentservice.capture",
        intent="callers",
        retrieval_policy_version="5.0",
        status=RunStatus.QUEUED,
        created_at=NOW,
    )


def _evidence(evidence_id: str = "ev_1", ordinal: int = 1) -> MessageEvidenceRow:
    return MessageEvidenceRow(
        evidence_id=evidence_id,
        citation_ordinal=ordinal,
        file_path="src/payments/service.py",
        symbol="PaymentService.capture",
        start_line=7,
        end_line=8,
        content_hash="abc123",
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
        snapshot_id="snap_1",
    )


def test_a_conversation_round_trips(store: ConversationStore) -> None:
    store.create_conversation(_conversation())

    loaded = store.get_conversation("conv_1")

    assert loaded is not None
    assert loaded.title == "What changed?"
    assert loaded.repository_id == "repo_1"
    assert loaded.created_at == NOW
    assert loaded.archived_at is None


def test_timestamps_come_back_as_utc(store: ConversationStore) -> None:
    """Storage keeps UTC; the client renders the local zone (Section 15)."""
    store.create_conversation(_conversation())

    loaded = store.get_conversation("conv_1")

    assert loaded is not None
    assert loaded.created_at.tzinfo is not None
    assert loaded.created_at.utcoffset() == timedelta(0)


def test_creating_a_turn_is_atomic(
    store: ConversationStore, connection: sqlite3.Connection
) -> None:
    """The user message, the assistant placeholder, and the run are one fact.
    A half-written turn would show a question with no answer coming."""
    store.create_conversation(_conversation())

    with pytest.raises(sqlite3.IntegrityError), write_transaction(connection):
        store.create_user_turn(
            _user_message(),
            _assistant_message(),
            # A run for a message that does not exist violates the foreign
            # key, which is the cheapest way to force a mid-turn failure.
            _run(message_id="msg_missing"),
        )

    assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM message_runs").fetchone()[0] == 0


def test_sequence_numbers_are_unique_within_a_conversation(
    store: ConversationStore, connection: sqlite3.Connection
) -> None:
    """Two messages at the same position would make thread order ambiguous."""
    store.create_conversation(_conversation())
    with write_transaction(connection):
        store.create_user_turn(_user_message(), _assistant_message(), _run())

    with pytest.raises(sqlite3.IntegrityError), write_transaction(connection):
        store.create_user_turn(
            _user_message("msg_3", sequence=1),
            _assistant_message("msg_4", sequence=4),
            _run("run_2", "msg_4"),
        )


def test_next_sequence_number_continues_the_thread(
    store: ConversationStore, connection: sqlite3.Connection
) -> None:
    store.create_conversation(_conversation())
    assert store.next_sequence_number("conv_1") == 1

    with write_transaction(connection):
        store.create_user_turn(_user_message(), _assistant_message(), _run())

    assert store.next_sequence_number("conv_1") == 3


def test_completing_an_assistant_message_writes_content_and_evidence_together(
    store: ConversationStore, connection: sqlite3.Connection
) -> None:
    store.create_conversation(_conversation())
    with write_transaction(connection):
        store.create_user_turn(_user_message(), _assistant_message(), _run())

    with write_transaction(connection):
        store.complete_assistant(
            message_id="msg_2",
            content="PaymentService.capture is called by one symbol.",
            evidence=(_evidence(),),
            run_id="run_1",
            latency_ms=42.0,
            completed_at=NOW,
        )

    messages = store.list_messages("conv_1", cursor=None, limit=10)
    assistant = messages.items[1]
    assert assistant.status is MessageStatus.COMPLETE
    assert "called by one symbol" in assistant.content
    citations = store.get_evidence("msg_2")
    assert [item.evidence_id for item in citations] == ["ev_1"]
    assert citations[0].snapshot_id == "snap_1"


def test_completion_is_atomic(
    store: ConversationStore, connection: sqlite3.Connection
) -> None:
    """Answer text without its citations is exactly the uncited claim the
    evidence contract forbids, so neither may land without the other."""
    store.create_conversation(_conversation())
    with write_transaction(connection):
        store.create_user_turn(_user_message(), _assistant_message(), _run())

    with pytest.raises(sqlite3.IntegrityError), write_transaction(connection):
        store.complete_assistant(
            message_id="msg_2",
            content="An answer whose citations cannot be written.",
            # Duplicate ordinals violate the primary key.
            evidence=(_evidence("ev_1"), _evidence("ev_2", ordinal=1)),
            run_id="run_1",
            latency_ms=1.0,
            completed_at=NOW,
        )

    messages = store.list_messages("conv_1", cursor=None, limit=10)
    assert messages.items[1].status is MessageStatus.QUEUED
    assert messages.items[1].content == ""
    assert store.get_evidence("msg_2") == ()


def test_a_failed_run_stays_visible_and_retryable(
    store: ConversationStore, connection: sqlite3.Connection
) -> None:
    store.create_conversation(_conversation())
    with write_transaction(connection):
        store.create_user_turn(_user_message(), _assistant_message(), _run())

    with write_transaction(connection):
        store.fail_or_cancel(
            message_id="msg_2",
            run_id="run_1",
            status=MessageStatus.FAILED,
            error_code="SNAPSHOT_NOT_READY",
            completed_at=NOW,
        )
    with write_transaction(connection):
        store.create_retry_run("msg_2", _run("run_2"))

    messages = store.list_messages("conv_1", cursor=None, limit=10)
    assert messages.items[1].status is MessageStatus.QUEUED
    assert messages.items[1].error_code is None
    runs = store.list_runs("msg_2")
    # The failed attempt is preserved: retry adds an attempt, it does not
    # rewrite the record of what already happened.
    assert [item.run_id for item in runs] == ["run_1", "run_2"]
    assert runs[0].status is RunStatus.FAILED


def test_soft_delete_hides_a_conversation_without_destroying_it(
    store: ConversationStore, connection: sqlite3.Connection
) -> None:
    store.create_conversation(_conversation())

    store.soft_delete("conv_1", deleted_at=NOW)

    assert store.get_conversation("conv_1") is None
    assert store.list_conversations("repo_1", cursor=None, limit=10).items == ()
    surviving = connection.execute(
        "SELECT COUNT(*) FROM conversations WHERE deleted_at IS NOT NULL"
    ).fetchone()[0]
    assert surviving == 1


def test_archiving_hides_from_the_default_list_but_not_by_id(
    store: ConversationStore,
) -> None:
    store.create_conversation(_conversation())

    store.archive("conv_1", archived_at=NOW)

    assert store.list_conversations("repo_1", cursor=None, limit=10).items == ()
    included = store.list_conversations(
        "repo_1", cursor=None, limit=10, include_archived=True
    )
    assert [item.conversation_id for item in included.items] == ["conv_1"]
    loaded = store.get_conversation("conv_1")
    assert loaded is not None and loaded.archived_at == NOW


def test_renaming_updates_the_title_and_the_timestamp(
    store: ConversationStore,
) -> None:
    store.create_conversation(_conversation())
    later = NOW + timedelta(minutes=5)

    store.rename("conv_1", title="Impact of the capture change", updated_at=later)

    loaded = store.get_conversation("conv_1")
    assert loaded is not None
    assert loaded.title == "Impact of the capture change"
    assert loaded.updated_at == later


def test_conversations_list_newest_activity_first_with_a_stable_cursor(
    store: ConversationStore,
) -> None:
    for index in range(3):
        store.create_conversation(
            _conversation(
                f"conv_{index}",
                last_message_at=NOW + timedelta(minutes=index),
            )
        )

    first = store.list_conversations("repo_1", cursor=None, limit=2)
    assert [item.conversation_id for item in first.items] == ["conv_2", "conv_1"]
    assert first.next_cursor is not None

    second = store.list_conversations("repo_1", cursor=first.next_cursor, limit=2)
    assert [item.conversation_id for item in second.items] == ["conv_0"]
    assert second.next_cursor is None


def test_messages_page_in_sequence_order(
    store: ConversationStore, connection: sqlite3.Connection
) -> None:
    store.create_conversation(_conversation())
    with write_transaction(connection):
        store.create_user_turn(_user_message(), _assistant_message(), _run())
    with write_transaction(connection):
        store.create_user_turn(
            _user_message("msg_3", sequence=3),
            _assistant_message("msg_4", sequence=4),
            _run("run_2", "msg_4"),
        )

    page = store.list_messages("conv_1", cursor=None, limit=3)

    assert [item.sequence_number for item in page.items] == [1, 2, 3]
    assert page.next_cursor is not None
    rest = store.list_messages("conv_1", cursor=page.next_cursor, limit=3)
    assert [item.sequence_number for item in rest.items] == [4]


def test_deleting_a_repository_cascades_to_its_conversations(
    store: ConversationStore, connection: sqlite3.Connection
) -> None:
    """Derived content about a repository the user removed must not linger."""
    store.create_conversation(_conversation())
    with write_transaction(connection):
        store.create_user_turn(_user_message(), _assistant_message(), _run())
    with write_transaction(connection):
        store.complete_assistant(
            message_id="msg_2",
            content="An answer.",
            evidence=(_evidence(),),
            run_id="run_1",
            latency_ms=1.0,
            completed_at=NOW,
        )

    connection.execute("DELETE FROM repositories WHERE repository_id = 'repo_1'")

    for table in (
        "conversations",
        "messages",
        "message_runs",
        "message_evidence",
    ):
        remaining = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert remaining == 0, table


def test_evidence_survives_its_snapshot(
    store: ConversationStore, connection: sqlite3.Connection
) -> None:
    """A historical message keeps telling the truth it told: nothing here
    references `snapshots`, so pruning cannot rewrite an old citation."""
    store.create_conversation(_conversation())
    with write_transaction(connection):
        store.create_user_turn(_user_message(), _assistant_message(), _run())
    with write_transaction(connection):
        store.complete_assistant(
            message_id="msg_2",
            content="An answer.",
            evidence=(_evidence(),),
            run_id="run_1",
            latency_ms=1.0,
            completed_at=NOW,
        )

    citations = store.get_evidence("msg_2")

    assert citations[0].snapshot_id == "snap_1"
    references = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'message_evidence'"
    ).fetchone()[0]
    assert "REFERENCES snapshots" not in references


def test_feedback_is_stored_once_per_message(
    store: ConversationStore, connection: sqlite3.Connection
) -> None:
    store.create_conversation(_conversation())
    with write_transaction(connection):
        store.create_user_turn(_user_message(), _assistant_message(), _run())

    store.save_feedback("msg_2", rating="up", reason_code=None, created_at=NOW)
    store.save_feedback("msg_2", rating="down", reason_code="wrong", created_at=NOW)

    rows = connection.execute(
        "SELECT rating, reason_code FROM message_feedback WHERE message_id = 'msg_2'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "down"


def test_oversized_content_is_refused(
    store: ConversationStore, connection: sqlite3.Connection
) -> None:
    """The repository corpus is never duplicated into chat rows (Section 15)."""
    store.create_conversation(_conversation())
    with write_transaction(connection):
        store.create_user_turn(_user_message(), _assistant_message(), _run())

    with pytest.raises(ValueError), write_transaction(connection):
        store.complete_assistant(
            message_id="msg_2",
            content="x" * (64 * 1024 + 1),
            evidence=(),
            run_id="run_1",
            latency_ms=1.0,
            completed_at=NOW,
        )
