"""Repository registration.

Registration is the only place a user-supplied filesystem path enters the
system, so it is where canonicalization and the approved-root decision happen.
Everything downstream works from the stored canonical root.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from codeatlas.domain.errors import (
    RepositoryAlreadyRegisteredError,
    RepositoryNotFoundError,
)
from codeatlas.domain.ids import repository_id
from codeatlas.domain.paths import canonicalize_root
from codeatlas.domain.repository import Repository
from codeatlas.storage.sqlite.stores import RepositoryStore


@dataclass(frozen=True)
class RegisterRepositoryRequest:
    """A request to register a local repository root."""

    path: str
    display_name: str | None = None


class RegisterRepositoryService:
    """Registers and looks up local repositories."""

    def __init__(
        self,
        repositories: RepositoryStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repositories = repositories
        self._clock = clock or (lambda: datetime.now(UTC))

    def register(self, request: RegisterRepositoryRequest) -> Repository:
        """Canonicalize, validate, and store a new repository root."""
        root = canonicalize_root(request.path)
        canonical_root = root.as_posix()

        if self._repositories.get_by_root(canonical_root) is not None:
            raise RepositoryAlreadyRegisteredError(
                "This repository is already registered."
            )

        repository = Repository(
            repository_id=repository_id(canonical_root),
            display_name=request.display_name or root.name or canonical_root,
            canonical_root=canonical_root,
            created_at=self._clock(),
        )
        self._repositories.add(repository)
        return repository

    def get(self, repository_id_value: str) -> Repository:
        """Return a registered repository or raise if it is unknown."""
        repository = self._repositories.get(repository_id_value)
        if repository is None:
            raise RepositoryNotFoundError("The repository is not registered.")
        return repository

    def list_all(self) -> tuple[Repository, ...]:
        """Return every registered repository."""
        return self._repositories.list_all()
