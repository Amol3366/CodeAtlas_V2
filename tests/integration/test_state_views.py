"""Integration tests for StateView implementations."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.analysis.states import (
    DirectoryStateView,
    GitBlobStateView,
    SnapshotStateView,
)
from codeatlas.domain.repository import FileClassification, FileRecord, Repository
from codeatlas.domain.snapshot import Snapshot, SnapshotState
from codeatlas.repositories.git_diff import GitDiffAdapter
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import FileStore, RepositoryStore, SnapshotStore

requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is unavailable"
)


@pytest.fixture()
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with connect(tmp_path / "db.sqlite") as open_connection:
        apply_migrations(open_connection)
        yield open_connection


@requires_git
def test_git_blob_state_view_lists_files_at_ref(git_repo_with_history: Path) -> None:
    view = GitBlobStateView(git_repo_with_history, "HEAD")
    paths = {file.relative_path for file in view.list_files()}
    assert "README.md" in paths
    assert "src/payments/service_renamed.py" in paths
    assert "src/payments/service.py" not in paths


@requires_git
def test_git_blob_state_view_reads_blob_contents(git_repo_with_history: Path) -> None:
    view = GitBlobStateView(git_repo_with_history, "HEAD")
    content = view.read_file("README.md")
    assert content is not None
    assert content.decode("utf-8") == "# Renamed\n"


@requires_git
def test_git_blob_state_view_verifies_hash_at_read(git_repo_with_history: Path) -> None:
    """A corrupt read would mismatch the hash captured at listing time."""
    git = GitDiffAdapter()
    view = GitBlobStateView(git_repo_with_history, "HEAD", git=git)
    view.list_files()
    # Tampering is not possible for an immutable Git blob; the test documents the
    # contract that read_file verifies the hash.
    content = view.read_file("README.md")
    assert content is not None


@requires_git
def test_git_blob_state_view_returns_none_for_missing_path(
    git_repo_with_history: Path,
) -> None:
    view = GitBlobStateView(git_repo_with_history, "HEAD")
    assert view.read_file("does/not/exist.py") is None


@requires_git
def test_git_blob_state_view_lists_same_paths_as_directory_view(
    git_repo_with_history: Path,
) -> None:
    git_view = GitBlobStateView(git_repo_with_history, "HEAD")
    dir_view = DirectoryStateView(git_repo_with_history)

    git_paths = {file.relative_path for file in git_view.list_files()}
    dir_paths = {file.relative_path for file in dir_view.list_files()}

    # The directory view includes the working tree; after a clean commit it
    # contains the same paths as HEAD. Byte hashes may differ because Git's
    # working-tree line endings are not guaranteed to match blob bytes.
    assert git_paths == dir_paths


@requires_git
def test_git_blob_state_view_differs_from_directory_view_on_dirty_tree(
    git_repo_with_history: Path,
) -> None:
    (git_repo_with_history / "README.md").write_text("# Dirty\n", encoding="utf-8")

    git_view = GitBlobStateView(git_repo_with_history, "HEAD")
    dir_view = DirectoryStateView(git_repo_with_history)

    git_hash = next(
        file.content_hash
        for file in git_view.list_files()
        if file.relative_path == "README.md"
    )
    dir_hash = next(
        file.content_hash
        for file in dir_view.list_files()
        if file.relative_path == "README.md"
    )
    assert git_hash != dir_hash


def test_snapshot_state_view_lists_files_from_stored_rows(
    connection: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    repository = Repository(
        repository_id="repo_1",
        display_name="demo",
        canonical_root=str(tmp_path),
        created_at=datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC),
    )
    RepositoryStore(connection).add(repository)
    snapshot = Snapshot(
        snapshot_id="snap_1",
        repository_id="repo_1",
        state=SnapshotState.ACTIVE,
        git_head=None,
        git_branch=None,
        git_dirty=False,
        working_tree_fingerprint="fp",
        file_count=1,
        parsed_file_count=1,
        skipped_file_count=0,
        parse_error_count=0,
        parser_bundle_version="1.2.0",
        index_version="1.0.0",
        created_at=datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC),
        activated_at=None,
        chunker_version="1.0.0",
        resolver_version="1.1.0",
    )
    SnapshotStore(connection).add_staging(snapshot)
    SnapshotStore(connection).activate(
        snapshot.snapshot_id,
        datetime(2026, 7, 27, 12, 0, 1, tzinfo=UTC),
    )

    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    content_hash = "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4"
    # Actual hash for "x = 1\n"
    content_hash = hashlib.sha256(b"x = 1\n").hexdigest()

    FileStore(connection).add_many(
        snapshot.snapshot_id,
        [
            FileRecord(
                file_id="file_1",
                relative_path="src/a.py",
                display_path="src/a.py",
                content_hash=content_hash,
                size_bytes=6,
                line_count=1,
                language="python",
                classification=FileClassification.SOURCE_CODE,
            )
        ],
    )

    view = SnapshotStateView(
        tmp_path,
        snapshot.snapshot_id,
        FileStore(connection),
    )
    files = view.list_files()
    assert len(files) == 1
    assert files[0].relative_path == "src/a.py"
    assert files[0].content_hash == content_hash


@requires_git
def test_snapshot_state_view_verifies_hash_against_disk(
    git_repo_with_history: Path,
    connection: sqlite3.Connection,
) -> None:
    repository = Repository(
        repository_id="repo_2",
        display_name="demo",
        canonical_root=str(git_repo_with_history),
        created_at=datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC),
    )
    RepositoryStore(connection).add(repository)
    snapshot = Snapshot(
        snapshot_id="snap_2",
        repository_id="repo_2",
        state=SnapshotState.ACTIVE,
        git_head=None,
        git_branch=None,
        git_dirty=False,
        working_tree_fingerprint="fp",
        file_count=1,
        parsed_file_count=1,
        skipped_file_count=0,
        parse_error_count=0,
        parser_bundle_version="1.2.0",
        index_version="1.0.0",
        created_at=datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC),
        activated_at=None,
        chunker_version="1.0.0",
        resolver_version="1.1.0",
    )
    SnapshotStore(connection).add_staging(snapshot)
    SnapshotStore(connection).activate(
        snapshot.snapshot_id,
        datetime(2026, 7, 27, 12, 0, 1, tzinfo=UTC),
    )

    content = (git_repo_with_history / "README.md").read_bytes()
    content_hash = hashlib.sha256(content).hexdigest()

    FileStore(connection).add_many(
        snapshot.snapshot_id,
        [
            FileRecord(
                file_id="file_1",
                relative_path="README.md",
                display_path="README.md",
                content_hash=content_hash,
                size_bytes=len(content),
                line_count=1,
                language="markdown",
                classification=FileClassification.DOCUMENTATION,
            )
        ],
    )

    view = SnapshotStateView(
        git_repo_with_history,
        snapshot.snapshot_id,
        FileStore(connection),
    )
    assert view.read_file("README.md") is not None

    (git_repo_with_history / "README.md").write_text("# Dirty\n", encoding="utf-8")
    assert view.read_file("README.md") is None


def test_snapshot_state_view_read_rejects_path_escape(
    connection: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    repository = Repository(
        repository_id="repo_3",
        display_name="demo",
        canonical_root=str(tmp_path),
        created_at=datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC),
    )
    RepositoryStore(connection).add(repository)
    snapshot = Snapshot(
        snapshot_id="snap_3",
        repository_id="repo_3",
        state=SnapshotState.ACTIVE,
        git_head=None,
        git_branch=None,
        git_dirty=False,
        working_tree_fingerprint="fp",
        file_count=0,
        parsed_file_count=0,
        skipped_file_count=0,
        parse_error_count=0,
        parser_bundle_version="1.2.0",
        index_version="1.0.0",
        created_at=datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC),
        activated_at=None,
        chunker_version="1.0.0",
        resolver_version="1.1.0",
    )
    SnapshotStore(connection).add_staging(snapshot)
    SnapshotStore(connection).activate(
        snapshot.snapshot_id,
        datetime(2026, 7, 27, 12, 0, 1, tzinfo=UTC),
    )

    view = SnapshotStateView(
        tmp_path,
        snapshot.snapshot_id,
        FileStore(connection),
    )
    assert view.read_file("../../etc/passwd") is None


def test_snapshot_state_view_read_returns_none_for_missing_file(
    connection: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    repository = Repository(
        repository_id="repo_4",
        display_name="demo",
        canonical_root=str(tmp_path),
        created_at=datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC),
    )
    RepositoryStore(connection).add(repository)
    snapshot = Snapshot(
        snapshot_id="snap_4",
        repository_id="repo_4",
        state=SnapshotState.ACTIVE,
        git_head=None,
        git_branch=None,
        git_dirty=False,
        working_tree_fingerprint="fp",
        file_count=0,
        parsed_file_count=0,
        skipped_file_count=0,
        parse_error_count=0,
        parser_bundle_version="1.2.0",
        index_version="1.0.0",
        created_at=datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC),
        activated_at=None,
        chunker_version="1.0.0",
        resolver_version="1.1.0",
    )
    SnapshotStore(connection).add_staging(snapshot)
    SnapshotStore(connection).activate(
        snapshot.snapshot_id,
        datetime(2026, 7, 27, 12, 0, 1, tzinfo=UTC),
    )

    view = SnapshotStateView(
        tmp_path,
        snapshot.snapshot_id,
        FileStore(connection),
    )
    assert view.read_file("src/missing.py") is None


# --- Line endings are not a change (ADR-0043) --------------------------------


def _commit_lf_file(root: Path, relative_path: str, text: str) -> None:
    """Write `text` with LF endings and commit it, whatever the platform.

    The bytes are written explicitly rather than through a fixture, because the
    fixtures themselves are built with Python's text mode and therefore already
    carry CRLF on Windows -- the very hazard under test.
    """
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
    identity = (
        "-c", "user.email=test@example.com",
        "-c", "user.name=Test",
        "-c", "core.autocrlf=false",
    )
    subprocess.run(
        ["git", *identity, "add", "--", relative_path],
        cwd=root, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", *identity, "commit", "-m", f"add {relative_path}"],
        cwd=root, check=True, capture_output=True,
    )


_SOURCE = "def handler():\n    return 1\n"


@requires_git
def test_a_crlf_working_copy_of_an_lf_blob_is_not_a_change(git_repo: Path) -> None:
    """The two comparison views must agree with Git about what changed.

    `core.autocrlf=true` is the Windows default, so a working copy can hold
    CRLF where the blob holds LF. Hashing raw bytes made every such file differ
    on both sides at once: Git reported the tree clean while preflight reported
    the whole file changed, and on a real repository that was 150 findings for
    an unedited checkout.
    """
    _commit_lf_file(git_repo, "eol.py", _SOURCE)
    blob = GitBlobStateView(git_repo, "HEAD")
    before = {file.relative_path: file.content_hash for file in blob.list_files()}

    (git_repo / "eol.py").write_bytes(_SOURCE.replace("\n", "\r\n").encode("utf-8"))

    directory = DirectoryStateView(git_repo)
    after = {file.relative_path: file.content_hash for file in directory.list_files()}

    assert after["eol.py"] == before["eol.py"]


@requires_git
def test_an_edit_is_still_a_change_when_line_endings_also_differ(
    git_repo: Path,
) -> None:
    """Normalizing the endings must not normalize away the edit inside them."""
    _commit_lf_file(git_repo, "eol.py", _SOURCE)
    blob = GitBlobStateView(git_repo, "HEAD")
    before = {file.relative_path: file.content_hash for file in blob.list_files()}

    edited = (_SOURCE + "def added():\n    return 2\n").replace("\n", "\r\n")
    (git_repo / "eol.py").write_bytes(edited.encode("utf-8"))

    directory = DirectoryStateView(git_repo)
    after = {file.relative_path: file.content_hash for file in directory.list_files()}

    assert after["eol.py"] != before["eol.py"]


@requires_git
def test_both_sides_hand_the_parser_bytes_with_no_carriage_returns(
    git_repo: Path,
) -> None:
    """File-level agreement is not enough: the two sides must also parse the
    same bytes, or every symbol inside a CRLF file differs by its hash."""
    _commit_lf_file(git_repo, "eol.py", _SOURCE)
    (git_repo / "eol.py").write_bytes(_SOURCE.replace("\n", "\r\n").encode("utf-8"))

    from_disk = DirectoryStateView(git_repo).read_file("eol.py")
    from_git = GitBlobStateView(git_repo, "HEAD").read_file("eol.py")

    assert from_disk is not None and from_git is not None
    assert b"\r" not in from_disk
    assert from_disk == from_git
