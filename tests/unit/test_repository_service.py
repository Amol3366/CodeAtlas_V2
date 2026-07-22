"""Tests for RepositoryService registration + scan orchestration (Blueprint §4.3.1)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from codeatlas.repositories.service import RepositoryService, repository_id_for


def test_registration_is_idempotent(copy_fixture: Callable[[str], Path]) -> None:
    root = copy_fixture("python_repo")
    service = RepositoryService()
    first = service.register(str(root))
    second = service.register(str(root))
    assert first.id == second.id
    assert first.id == repository_id_for(first.normalized_root_path)


def test_registration_records_fields(copy_fixture: Callable[[str], Path]) -> None:
    root = copy_fixture("python_repo")
    repo = RepositoryService().register(str(root), name="payments")
    assert repo.name == "payments"
    assert Path(repo.root_path) == root
    assert repo.normalized_root_path
    assert isinstance(repo.created_at, datetime)
    # A tmp copy is not a git repository.
    assert repo.is_git_repository is False


def test_scan_returns_manifest(copy_fixture: Callable[[str], Path]) -> None:
    root = copy_fixture("python_repo")
    service = RepositoryService()
    repo = service.register(str(root))
    result = service.scan(repo)
    assert result.manifest.entries
    # Deterministic across service scans too.
    assert result.manifest.to_json() == service.scan(repo).manifest.to_json()
