"""Deleting a repository, purging conversations, and the retention sweep.

Deletion is the operation with no undo, so the contract it has to keep is
narrow: **nothing goes away that the user did not ask to go away.** The schema
makes that non-obvious — `conversations` cascades from `repositories`, so a
plain `DELETE FROM repositories` silently takes chat history with it. The guard
therefore lives in the application layer, where it can refuse.

Retention is the other half: an explicit purge for a user who wants it gone now,
and a 30-day sweep so an unattended install does not accumulate deletions
forever (ADR-0007 decision 5). Neither may touch an undeleted conversation.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.errors import (
    RepositoryHasConversationsError,
    RepositoryNotFoundError,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

RETENTION_DAYS = 30


@dataclass
class Harness:
    services: ApplicationServices
    connection: sqlite3.Connection


@pytest.fixture()
def harness(tmp_path: Path) -> Iterator[Harness]:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        yield Harness(services=build_services(connection), connection=connection)


def _register(harness: Harness, root: Path) -> str:
    repository = harness.services.registration.register(
        RegisterRepositoryRequest(path=str(root))
    )
    return repository.repository_id


def _age_deletion(
    connection: sqlite3.Connection, conversation_id: str, *, days: int
) -> None:
    """Backdate a soft deletion, so the sweep has something old to find."""
    when = datetime.now(UTC) - timedelta(days=days)
    connection.execute(
        "UPDATE conversations SET deleted_at = ? WHERE conversation_id = ?",
        (when.isoformat().replace("+00:00", "Z"), conversation_id),
    )
    connection.commit()


# --- Repository deletion ---------------------------------------------------


def test_deleting_a_repository_removes_it(harness: Harness, sample_repo: Path) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)

    harness.services.registration.delete(repository_id)

    with pytest.raises(RepositoryNotFoundError):
        harness.services.registration.get(repository_id)


def test_deleting_a_repository_never_touches_the_source_files(
    harness: Harness, sample_repo: Path
) -> None:
    """Blueprint 3.1: remove a repository *from CodeAtlas* without deleting it."""
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    source = sample_repo / "src" / "payments" / "service.py"
    before = source.read_text(encoding="utf-8")

    harness.services.registration.delete(repository_id)

    assert source.exists()
    assert source.read_text(encoding="utf-8") == before


def test_deleting_a_repository_removes_its_snapshots_and_derived_rows(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)

    harness.services.registration.delete(repository_id)

    for table in ("snapshots", "files", "symbols"):
        remaining = harness.connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE snapshot_id IN"
            " (SELECT snapshot_id FROM snapshots WHERE repository_id = ?)"
            if table != "snapshots"
            else "SELECT COUNT(*) FROM snapshots WHERE repository_id = ?",
            (repository_id,),
        ).fetchone()[0]
        assert remaining == 0, f"{table} kept rows"


def test_deleting_a_repository_with_conversations_is_refused(
    harness: Harness, sample_repo: Path
) -> None:
    """The one that matters: `conversations` cascades at the schema level.

    Without this guard a user freeing index space would silently lose their
    chat history, and would find out only by looking for it.
    """
    repository_id = _register(harness, sample_repo)
    harness.services.conversations.create(repository_id, title="Keep me")

    with pytest.raises(RepositoryHasConversationsError):
        harness.services.registration.delete(repository_id)

    assert harness.services.registration.get(repository_id) is not None


def test_a_refused_deletion_changes_nothing(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    conversation = harness.services.conversations.create(repository_id)

    with pytest.raises(RepositoryHasConversationsError):
        harness.services.registration.delete(repository_id)

    assert harness.services.conversations.get(conversation.conversation_id)
    assert harness.services.indexing.get_active_snapshot(repository_id) is not None


def test_an_explicitly_cascaded_deletion_removes_the_conversations(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.conversations.create(repository_id)

    harness.services.registration.delete(repository_id, cascade=True)

    remaining = harness.connection.execute(
        "SELECT COUNT(*) FROM conversations WHERE repository_id = ?",
        (repository_id,),
    ).fetchone()[0]
    assert remaining == 0


def test_a_soft_deleted_conversation_still_blocks_deletion(
    harness: Harness, sample_repo: Path
) -> None:
    """It is recoverable until it is purged, so it is still data to lose."""
    repository_id = _register(harness, sample_repo)
    conversation = harness.services.conversations.create(repository_id)
    harness.services.conversations.delete(conversation.conversation_id)

    with pytest.raises(RepositoryHasConversationsError):
        harness.services.registration.delete(repository_id)


def test_deleting_an_unknown_repository_raises(harness: Harness) -> None:
    with pytest.raises(RepositoryNotFoundError):
        harness.services.registration.delete("repo_missing")


# --- Retention -------------------------------------------------------------


def test_purging_removes_a_soft_deleted_conversation_permanently(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    conversation = harness.services.conversations.create(repository_id)
    harness.services.conversations.delete(conversation.conversation_id)

    purged = harness.services.conversations.purge_deleted(older_than=timedelta(0))

    assert purged == 1
    remaining = harness.connection.execute(
        "SELECT COUNT(*) FROM conversations WHERE conversation_id = ?",
        (conversation.conversation_id,),
    ).fetchone()[0]
    assert remaining == 0


def test_purging_never_touches_an_undeleted_conversation(
    harness: Harness, sample_repo: Path
) -> None:
    """The invariant ADR-0007 states for both the purge and the sweep."""
    repository_id = _register(harness, sample_repo)
    kept = harness.services.conversations.create(repository_id, title="Active")

    harness.services.conversations.purge_deleted(older_than=timedelta(0))

    assert harness.services.conversations.get(kept.conversation_id)


def test_the_sweep_leaves_a_recent_deletion_recoverable(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    conversation = harness.services.conversations.create(repository_id)
    harness.services.conversations.delete(conversation.conversation_id)
    _age_deletion(harness.connection, conversation.conversation_id, days=3)

    purged = harness.services.conversations.purge_deleted(
        older_than=timedelta(days=RETENTION_DAYS)
    )

    assert purged == 0
    remaining = harness.connection.execute(
        "SELECT COUNT(*) FROM conversations WHERE conversation_id = ?",
        (conversation.conversation_id,),
    ).fetchone()[0]
    assert remaining == 1


def test_the_sweep_removes_a_deletion_past_the_window(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    conversation = harness.services.conversations.create(repository_id)
    harness.services.conversations.delete(conversation.conversation_id)
    _age_deletion(harness.connection, conversation.conversation_id, days=45)

    purged = harness.services.conversations.purge_deleted(
        older_than=timedelta(days=RETENTION_DAYS)
    )

    assert purged == 1


def test_purging_removes_the_messages_of_the_conversation_it_removes(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    conversation = harness.services.conversations.create(repository_id)
    harness.services.conversations.submit(
        conversation.conversation_id, "Where is PaymentService.capture?"
    )
    harness.services.conversations.delete(conversation.conversation_id)

    harness.services.conversations.purge_deleted(older_than=timedelta(0))

    orphans = harness.connection.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
        (conversation.conversation_id,),
    ).fetchone()[0]
    assert orphans == 0


def test_the_sweep_runs_once_when_the_application_starts(
    tmp_path: Path, sample_repo: Path
) -> None:
    """Startup, never the request path — the mistake recovery was making.

    An unattended install is covered by its next restart, which is the trade
    ADR-0007 accepted rather than putting retention on a hot path.
    """
    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        conversation = services.conversations.create(repository.repository_id)
        services.conversations.delete(conversation.conversation_id)
        _age_deletion(connection, conversation.conversation_id, days=90)

    with TestClient(create_app(database, watch=False)):
        pass  # entering the context runs the lifespan

    with connect(database) as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM conversations WHERE conversation_id = ?",
            (conversation.conversation_id,),
        ).fetchone()[0]
    assert remaining == 0


# --- REST ------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    database = tmp_path / "api.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
    with TestClient(create_app(database, watch=False)) as test_client:
        yield test_client


def _register_over_http(client: TestClient, root: Path) -> str:
    response = client.post("/v1/repositories", json={"path": str(root)})
    assert response.status_code == 201, response.text
    return str(response.json()["repository_id"])


def test_rest_delete_removes_a_repository(
    client: TestClient, sample_repo: Path
) -> None:
    repository_id = _register_over_http(client, sample_repo)

    response = client.delete(f"/v1/repositories/{repository_id}")

    assert response.status_code == 204
    assert client.get(f"/v1/repositories/{repository_id}").status_code == 404


def test_rest_delete_refuses_when_conversations_exist(
    client: TestClient, sample_repo: Path
) -> None:
    repository_id = _register_over_http(client, sample_repo)
    created = client.post("/v1/conversations", json={"repository_id": repository_id})
    assert created.status_code == 201, created.text

    response = client.delete(f"/v1/repositories/{repository_id}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REPOSITORY_HAS_CONVERSATIONS"


def test_rest_delete_cascades_when_asked(
    client: TestClient, sample_repo: Path
) -> None:
    repository_id = _register_over_http(client, sample_repo)
    client.post("/v1/conversations", json={"repository_id": repository_id})

    response = client.delete(f"/v1/repositories/{repository_id}?cascade=true")

    assert response.status_code == 204


def test_rest_delete_of_an_unknown_repository_is_a_404(client: TestClient) -> None:
    assert client.delete("/v1/repositories/repo_missing").status_code == 404
