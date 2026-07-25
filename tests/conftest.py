"""Shared fixtures for the CodeAtlas test suite."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SERVICE_SOURCE = (
    "from .idempotency import IdempotencyStore\n"
    "\n"
    "class PaymentService:\n"
    "    def __init__(self, store: IdempotencyStore) -> None:\n"
    "        self.store = store\n"
    "\n"
    "    def capture(self, key: str) -> str:\n"
    "        return self.store.claim(key)\n"
)
IDEMPOTENCY_SOURCE = (
    "class IdempotencyStore:\n"
    "    def claim(self, key: str) -> str:\n"
    "        return key\n"
)


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    """A small, real on-disk repository used across Phase 1 tests.

    Deliberately not a Git repository: registration, scanning, and indexing must
    work without Git, and the Git-backed variant is a separate fixture.
    """
    root = tmp_path / "sample_repo"
    (root / "src" / "payments").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "payments" / "service.py").write_text(
        SERVICE_SOURCE, encoding="utf-8"
    )
    (root / "src" / "payments" / "idempotency.py").write_text(
        IDEMPOTENCY_SOURCE, encoding="utf-8"
    )
    (root / "README.md").write_text("# Sample\n", encoding="utf-8")
    return root


@pytest.fixture()
def git_repo(sample_repo: Path) -> Path:
    """The sample repository, initialized as a real Git repository.

    Identity is passed per command so the test never depends on the developer's
    global Git configuration.
    """

    def run(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=sample_repo,
            check=True,
            capture_output=True,
            text=True,
        )

    identity = (
        "-c",
        "user.email=dev@example.invalid",
        "-c",
        "user.name=Dev",
    )
    run("init", "--initial-branch", "main")
    run(*identity, "add", ".")
    run(*identity, "commit", "-m", "initial")
    return sample_repo
