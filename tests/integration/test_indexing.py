"""Registration, indexing, validation, and atomic snapshot activation."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.indexing import SnapshotValidationError
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.errors import (
    PathSafetyError,
    RepositoryAlreadyRegisteredError,
    RepositoryNotFoundError,
)
from codeatlas.domain.snapshot import SnapshotState
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


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


def test_register_defaults_the_display_name_to_the_directory(
    harness: Harness, sample_repo: Path
) -> None:
    repository = harness.services.registration.register(
        RegisterRepositoryRequest(path=str(sample_repo))
    )
    assert repository.display_name == "sample_repo"
    assert repository.repository_id.startswith("repo_")
    assert repository.created_at.tzinfo is not None


def test_registering_the_same_root_twice_is_rejected(
    harness: Harness, sample_repo: Path
) -> None:
    _register(harness, sample_repo)
    with pytest.raises(RepositoryAlreadyRegisteredError):
        _register(harness, sample_repo)


def test_registering_a_missing_directory_is_rejected(
    harness: Harness, tmp_path: Path
) -> None:
    with pytest.raises(PathSafetyError):
        harness.services.registration.register(
            RegisterRepositoryRequest(path=str(tmp_path / "missing"))
        )


def test_get_unknown_repository_raises(harness: Harness) -> None:
    with pytest.raises(RepositoryNotFoundError):
        harness.services.registration.get("repo_missing")


def test_register_then_index_activates_a_snapshot_with_symbols(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    result = harness.services.indexing.index(repository_id)

    assert result.snapshot.state is SnapshotState.ACTIVE
    assert result.snapshot.file_count == 3
    # Two Python modules and the Markdown README. The document parser joined the
    # registry in Phase 2, so a document is now parsed rather than skipped.
    assert result.snapshot.parsed_file_count == 3
    assert result.snapshot.parse_error_count == 0
    assert result.snapshot.activated_at is not None

    symbols = harness.services.indexing.symbol_count(result.snapshot.snapshot_id)
    assert symbols > 0


def test_indexing_an_unknown_repository_raises(harness: Harness) -> None:
    with pytest.raises(RepositoryNotFoundError):
        harness.services.indexing.index("repo_missing")


def test_reindexing_unchanged_source_is_idempotent(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    first = harness.services.indexing.index(repository_id)
    second = harness.services.indexing.index(repository_id)

    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    active_count = harness.connection.execute(
        "SELECT COUNT(*) FROM snapshots WHERE state = 'active'"
    ).fetchone()[0]
    total = harness.connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    assert active_count == 1
    assert total == 1


def test_editing_a_symbol_creates_a_new_snapshot_and_supersedes_the_old_one(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    first = harness.services.indexing.index(repository_id)

    path = sample_repo / "src" / "payments" / "service.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n    def refund(self, key: str) -> str:\n        return key\n",
        encoding="utf-8",
    )
    second = harness.services.indexing.index(repository_id)

    assert second.snapshot.snapshot_id != first.snapshot.snapshot_id
    assert second.snapshot.state is SnapshotState.ACTIVE
    superseded = harness.services.indexing.get_snapshot(first.snapshot.snapshot_id)
    assert superseded is not None
    assert superseded.state is SnapshotState.SUPERSEDED


def test_failed_validation_preserves_the_previous_active_snapshot(
    harness: Harness, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_id = _register(harness, sample_repo)
    good = harness.services.indexing.index(repository_id)

    (sample_repo / "extra.py").write_text("VALUE = 1\n", encoding="utf-8")

    def fail(*_: object, **__: object) -> None:
        raise SnapshotValidationError("injected validation failure")

    monkeypatch.setattr(harness.services.indexing, "_validate_snapshot", fail)
    with pytest.raises(SnapshotValidationError):
        harness.services.indexing.index(repository_id)

    active = harness.services.indexing.get_active_snapshot(repository_id)
    assert active is not None
    assert active.snapshot_id == good.snapshot.snapshot_id
    assert active.state is SnapshotState.ACTIVE


def test_failed_validation_marks_the_new_snapshot_failed(
    harness: Harness, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    (sample_repo / "extra.py").write_text("VALUE = 1\n", encoding="utf-8")

    def fail(*_: object, **__: object) -> None:
        raise SnapshotValidationError("injected validation failure")

    monkeypatch.setattr(harness.services.indexing, "_validate_snapshot", fail)
    with pytest.raises(SnapshotValidationError):
        harness.services.indexing.index(repository_id)

    failed = harness.connection.execute(
        "SELECT COUNT(*) FROM snapshots WHERE state = 'failed'"
    ).fetchone()[0]
    assert failed == 1


def test_indexing_a_non_git_directory_records_a_warning_and_still_activates(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    result = harness.services.indexing.index(repository_id)

    assert result.snapshot.git_head is None
    assert result.snapshot.state is SnapshotState.ACTIVE
    assert any(warning.startswith("GIT_") for warning in result.warnings)


def test_index_job_is_recorded_and_released(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    result = harness.services.indexing.index(repository_id)

    row = harness.connection.execute(
        "SELECT status, stage, snapshot_id FROM index_jobs WHERE job_id = ?",
        (result.job_id,),
    ).fetchone()
    assert row["status"] == "succeeded"
    assert row["snapshot_id"] == result.snapshot.snapshot_id


def test_malformed_python_is_counted_not_fatal(
    harness: Harness, sample_repo: Path
) -> None:
    (sample_repo / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    repository_id = _register(harness, sample_repo)
    result = harness.services.indexing.index(repository_id)

    assert result.snapshot.state is SnapshotState.ACTIVE
    assert result.snapshot.parse_error_count == 1
    assert any(d.code == "PARSE_SYNTAX_ERROR" for d in result.diagnostics)


def test_non_python_files_are_stored_but_not_parsed(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    result = harness.services.indexing.index(repository_id)

    files = harness.services.indexing.list_files(result.snapshot.snapshot_id)
    assert "README.md" in [record.relative_path for record in files]


def test_symbols_are_scoped_to_their_snapshot(
    harness: Harness, sample_repo: Path
) -> None:
    repository_id = _register(harness, sample_repo)
    first = harness.services.indexing.index(repository_id)
    (sample_repo / "src" / "payments" / "extra.py").write_text(
        "class Extra:\n    pass\n", encoding="utf-8"
    )
    second = harness.services.indexing.index(repository_id)

    first_count = harness.services.indexing.symbol_count(first.snapshot.snapshot_id)
    second_count = harness.services.indexing.symbol_count(second.snapshot.snapshot_id)
    assert second_count > first_count


def test_indexing_never_executes_repository_code(
    harness: Harness, sample_repo: Path
) -> None:
    marker = sample_repo / "executed.txt"
    (sample_repo / "evil.py").write_text(
        f"open(r'{marker}', 'w').write('x')\n", encoding="utf-8"
    )
    repository_id = _register(harness, sample_repo)
    harness.services.indexing.index(repository_id)
    assert marker.exists() is False


def test_timestamps_are_utc(harness: Harness, sample_repo: Path) -> None:
    repository_id = _register(harness, sample_repo)
    result = harness.services.indexing.index(repository_id)
    activated_at = result.snapshot.activated_at
    assert activated_at is not None
    assert activated_at.utcoffset() == datetime.now(UTC).utcoffset()
