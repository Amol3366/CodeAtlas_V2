"""Upgrading a database written by a real earlier build of CodeAtlas.

The fixture under `tests/fixtures/upgrade/` was not hand-written. It was
produced by checking out the commit before migration `0009` and running *that*
code — `scripts/make_upgrade_fixture.py` does it and refuses to run against the
current tree. The Phase 6 plan asks for exactly this: "the upgrade path is
tested from a real prior-version database, not a synthetic one", because a
synthetic database proves the migration against my reading of the old schema
rather than against what the old code actually wrote.

What these tests defend is gate condition 5's second half: a packaged build
"upgrades from the previous schema version without losing a snapshot or a
conversation".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from codeatlas.application.container import build_services
from codeatlas.storage.sqlite.backup import (
    check_integrity,
    read_schema_version,
    restore,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import SCHEMA_VERSION
from codeatlas.storage.sqlite.upgrade import plan_upgrade, upgrade_database

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "upgrade" / "schema_0008.db"
)


def _expected_pending() -> tuple[int, ...]:
    """Every schema version between the fixture's and this build's.

    Derived rather than written out. The fixture is a real artifact of an older
    build and stays where it is, so each new migration widens the gap it has to
    cross — since migration 0010 this is a *multi-step* upgrade, which is
    exactly the case a hand-edited literal would have stopped exercising.
    """
    return tuple(range(read_schema_version(_FIXTURE) + 1, SCHEMA_VERSION + 1))


@pytest.fixture
def manifest(prior_version_manifest: dict[str, Any]) -> dict[str, Any]:
    return prior_version_manifest


@pytest.fixture
def prior_database(prior_version_database: Path) -> Path:
    """A writable copy of the fixture. The committed file is never modified."""
    return prior_version_database


def test_the_fixture_really_is_older_than_this_build(manifest: dict[str, Any]) -> None:
    """If someone regenerates the fixture with the current code, every other
    test here would pass while proving nothing. This is the tripwire."""
    assert _FIXTURE.is_file(), "the prior-version fixture is missing"
    assert read_schema_version(_FIXTURE) < SCHEMA_VERSION
    assert manifest["schema_version"] == read_schema_version(_FIXTURE)
    assert len(manifest["produced_by"]) == 40, "the producing commit is not recorded"
    check_integrity(_FIXTURE)


def test_planning_an_upgrade_changes_nothing(prior_database: Path) -> None:
    before = prior_database.stat().st_mtime_ns

    plan = plan_upgrade(prior_database)

    assert plan.current_version == read_schema_version(_FIXTURE)
    assert plan.target_version == SCHEMA_VERSION
    assert plan.pending == _expected_pending()
    assert plan.is_required
    assert prior_database.stat().st_mtime_ns == before


def test_upgrading_moves_the_schema_forward(prior_database: Path) -> None:
    result = upgrade_database(prior_database)

    assert result.from_version == 8
    assert result.to_version == SCHEMA_VERSION
    assert result.applied == _expected_pending()
    assert read_schema_version(prior_database) == SCHEMA_VERSION
    check_integrity(prior_database)


def test_no_snapshot_and_no_conversation_is_lost(
    prior_database: Path, manifest: dict[str, Any]
) -> None:
    """The gate condition, measured directly: every table the old build wrote
    still holds exactly the rows it wrote."""
    upgrade_database(prior_database)

    with connect(prior_database) as connection:
        for table, expected in manifest["row_counts"].items():
            row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            assert row[0] == expected, f"{table} lost rows during the upgrade"


def test_the_upgraded_database_still_answers(
    prior_database: Path, manifest: dict[str, Any]
) -> None:
    """Preserved rows are not enough — the services must still read them.

    Deliberately asks only questions the database can answer on its own: the
    repository this fixture indexed lived in a temporary directory that is long
    gone, which is itself a realistic upgrade situation.
    """
    upgrade_database(prior_database)

    with connect(prior_database) as connection:
        services = build_services(connection)

        repositories = services.repositories.list_all()
        assert [item.repository_id for item in repositories] == [
            manifest["repository_id"]
        ]

        conversations = services.conversations.list(
            manifest["repository_id"], include_archived=True
        )
        titles = {item.title for item in conversations.items}
        assert {"Capture flow", "Archived thread"} <= titles

        answered = manifest["conversations"]["answered"]
        messages = services.conversations.list_messages(answered).items
        assert len(messages) == 4  # two questions, two answers

        expected = {item["message_id"]: item for item in manifest["messages"]}
        for message in messages:
            if message.message_id in expected:
                assert message.content == expected[message.message_id]["content"]


def test_the_evidence_of_an_old_answer_survives(
    prior_database: Path, manifest: dict[str, Any]
) -> None:
    """A historical message stays tied to the snapshot that answered it
    (`CLAUDE.md` Section 8.2). An upgrade that dropped its citations would break
    that quietly, leaving an answer that cites nothing."""
    cited = next(item for item in manifest["messages"] if item["evidence_count"] > 0)

    upgrade_database(prior_database)

    with connect(prior_database) as connection:
        rows = connection.execute(
            "SELECT COUNT(*) FROM message_evidence WHERE message_id = ?",
            (cited["message_id"],),
        ).fetchone()
        assert rows[0] == cited["evidence_count"]


def test_the_active_snapshot_is_still_active(
    prior_database: Path, manifest: dict[str, Any]
) -> None:
    upgrade_database(prior_database)

    with connect(prior_database) as connection:
        row = connection.execute(
            "SELECT state FROM snapshots WHERE snapshot_id = ?",
            (manifest["active_snapshot_id"],),
        ).fetchone()
        assert row is not None, "the active snapshot did not survive the upgrade"
        assert row[0] == "active"


def test_the_upgrade_checkpoints_before_it_migrates(prior_database: Path) -> None:
    """"A migration that can lose data must be preceded by a checkpoint" — the
    Phase 6 constraint, taken literally."""
    result = upgrade_database(prior_database)

    assert result.checkpoint_path is not None
    assert result.checkpoint_path.is_file()
    check_integrity(result.checkpoint_path)
    assert read_schema_version(result.checkpoint_path) == result.from_version


def test_the_checkpoint_restores_to_the_pre_upgrade_state(
    prior_database: Path, manifest: dict[str, Any]
) -> None:
    """A checkpoint nobody has restored from is a claim, not a safety net."""
    result = upgrade_database(prior_database)
    assert result.checkpoint_path is not None

    restored = restore(result.checkpoint_path, prior_database)

    assert restored.schema_version == result.from_version
    with connect(prior_database) as connection:
        row = connection.execute("SELECT COUNT(*) FROM conversations").fetchone()
        assert row[0] == manifest["row_counts"]["conversations"]


def test_upgrading_an_upgraded_database_does_nothing(prior_database: Path) -> None:
    upgrade_database(prior_database)

    second = upgrade_database(prior_database)

    assert second.applied == ()
    assert second.from_version == second.to_version == SCHEMA_VERSION
    assert second.checkpoint_path is None, "a no-op upgrade wrote a pointless copy"


def test_the_upgrade_reports_what_it_preserved(
    prior_database: Path, manifest: dict[str, Any]
) -> None:
    result = upgrade_database(prior_database)

    assert result.counts["repositories"] == manifest["row_counts"]["repositories"]
    assert result.counts["snapshots"] == manifest["row_counts"]["snapshots"]
    assert result.counts["conversations"] == manifest["row_counts"]["conversations"]
    assert result.warnings == ()
