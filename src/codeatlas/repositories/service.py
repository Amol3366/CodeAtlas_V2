"""Repository registration and scan orchestration (Blueprint §4.3.1, Phase 1).

Composes path security, Git detection, and the scanner into the two operations
the rest of the system needs: register a local directory as a ``Repository``, and
scan it into a deterministic manifest. Registration is idempotent — the same
directory always yields the same ``Repository.id`` (CLAUDE.md §2.9).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from codeatlas.domain.entities import Repository
from codeatlas.logging.setup import get_logger
from codeatlas.repositories import path_security as ps
from codeatlas.repositories.git_service import GitService, GitState
from codeatlas.repositories.scanner import RepositoryScanner, ScanResult
from codeatlas.settings.config import LanguageIndex, ScanConfig, default_language_index


def repository_id_for(normalized_root_path: str) -> str:
    """Deterministic repository id from the normalized root (idempotent registration)."""
    digest = hashlib.sha256(normalized_root_path.encode("utf-8")).hexdigest()
    return f"repo_{digest[:16]}"


class RepositoryService:
    """Registers and scans local repositories."""

    def __init__(
        self,
        *,
        config: ScanConfig | None = None,
        language_index: LanguageIndex | None = None,
        git_service: GitService | None = None,
    ) -> None:
        self._config = config or ScanConfig()
        self._language_index = language_index or default_language_index()
        self._git = git_service or GitService()
        self._scanner = RepositoryScanner(self._config, self._language_index)

    def register(
        self, path: str, *, name: str | None = None, now: datetime | None = None
    ) -> Repository:
        """Validate and register a local directory as a repository."""
        root = ps.normalize_root(path, allow_unc=self._config.allow_unc_paths)
        state = self._git.get_state(root.display_path)
        created = now or datetime.now(UTC)
        repo = Repository(
            id=repository_id_for(root.normalized_path),
            name=name or root.path.name,
            root_path=root.display_path,
            normalized_root_path=root.normalized_path,
            is_git_repository=state.is_git_repository,
            default_branch=state.branch,
            created_at=created,
        )
        get_logger(repository_id=repo.id).info(
            "repository.registered",
            root_path=repo.root_path,
            is_git_repository=repo.is_git_repository,
            branch=repo.default_branch,
        )
        return repo

    def scan(self, repository: Repository) -> ScanResult:
        """Scan a registered repository into a deterministic manifest."""
        root = ps.normalize_root(repository.root_path, allow_unc=self._config.allow_unc_paths)
        return self._scanner.scan(root, repository_id=repository.id)

    def git_state(self, repository: Repository) -> GitState:
        """Return the current Git state of a registered repository."""
        return self._git.get_state(repository.root_path)
