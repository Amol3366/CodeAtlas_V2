"""Parse diagnostics are persisted, not just logged (Phase 3 build item)."""

from __future__ import annotations

from datetime import UTC, datetime

from codeatlas.domain.entities import Repository
from codeatlas.domain.enums import Language, SnapshotType
from codeatlas.parsing.contracts import ParseRequest
from codeatlas.parsing.python.parser import PythonParser
from codeatlas.repositories.snapshot_manager import SnapshotManager
from codeatlas.storage.sqlite.database import Database
from codeatlas.storage.sqlite.repositories import DiagnosticStore, RepositoryStore

_MALFORMED = b"def broken(:\n    return 1\n"


async def test_diagnostics_persisted_and_retrievable(database: Database) -> None:
    repo = Repository(
        id="repo_x",
        name="x",
        root_path="/x",
        normalized_root_path="/x",
        is_git_repository=False,
        created_at=datetime.now(UTC),
    )
    async with database.writer.transaction() as session:
        await RepositoryStore(session).upsert(repo)
    snapshot = await SnapshotManager(database.writer).create_staging(
        repo.id, snapshot_type=SnapshotType.DIRECTORY
    )

    result = PythonParser().parse(ParseRequest(repo.id, "broken.py", Language.PYTHON, _MALFORMED))
    assert result.diagnostics  # sanity

    async with database.writer.transaction() as session:
        await DiagnosticStore(session).add_for_file(
            repository_id=repo.id,
            snapshot_id=snapshot.id,
            relative_path="broken.py",
            diagnostics=list(result.diagnostics),
        )

    async with database.writer.read_session() as session:
        stored = await DiagnosticStore(session).list_for_snapshot(snapshot.id)

    assert len(stored) == len(result.diagnostics)
    assert stored[0].severity == "error"
    assert stored[0].relative_path == "broken.py"
    assert stored[0].message
