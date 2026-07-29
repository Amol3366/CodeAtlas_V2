"""Shared fixtures for the CodeAtlas test suite."""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import pytest

PRIOR_VERSION_DATABASE = (
    Path(__file__).resolve().parent / "fixtures" / "upgrade" / "schema_0008.db"
)


def _is_installed(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except (ImportError, ValueError):
        return False


# `tests/semantic/` drives a real embedding model and therefore needs the
# optional `semantic-local` extra. Skipping the directory when the extra is
# absent — rather than excluding it in `norecursedirs` — keeps the tests
# *visible*: `pytest -q` still names them, so a suite that stopped covering
# the provider says so instead of quietly shrinking.
#
# `check_phase7.ps1 -Semantic` installs the extra, at which point these run for
# real. The gating lives here, in the one conftest this suite has, because a
# second conftest module collides with this one under mypy.
collect_ignore_glob: list[str] = []
if not _is_installed("sentence_transformers"):
    collect_ignore_glob.append("semantic/*")


@pytest.fixture(scope="session")
def local_provider() -> Any:
    """A real, pinned local embedding model.

    Session-scoped because loading it takes seconds and downloading it takes
    considerably longer. Per-test construction would make the suite slow enough
    that it stopped being run, which is the first step towards it not working.
    """
    from codeatlas.semantic.providers import LocalSentenceTransformerProvider

    return LocalSentenceTransformerProvider()

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
def prior_version_database(tmp_path: Path) -> Path:
    """A writable copy of a database written by a real earlier build.

    Produced by `scripts/make_upgrade_fixture.py` against a checkout of the
    commit before migration `0009`. The committed file is never modified —
    every test works on its own copy — and the manifest beside it declares what
    it contains, so "nothing was lost" can be measured rather than assumed.
    """
    target = tmp_path / "codeatlas.db"
    shutil.copy2(PRIOR_VERSION_DATABASE, target)
    return target


@pytest.fixture()
def prior_version_manifest() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        PRIOR_VERSION_DATABASE.with_suffix(".json").read_text(encoding="utf-8")
    )
    return loaded


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


@pytest.fixture()
def git_repo_with_history(git_repo: Path) -> Path:
    """The git repo after a second commit with add/modify/delete/rename."""

    def run(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=git_repo,
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

    # Rename a file while preserving its content (pure rename).
    (git_repo / "src" / "payments" / "service_renamed.py").write_bytes(
        (git_repo / "src" / "payments" / "service.py").read_bytes()
    )
    run("rm", "src/payments/service.py")
    (git_repo / "src" / "payments" / "new_file.py").write_text(
        "NEW_VALUE = 1\n", encoding="utf-8"
    )
    (git_repo / "README.md").write_text("# Renamed\n", encoding="utf-8")
    (git_repo / "src" / "payments" / "idempotency.py").unlink()
    run(*identity, "add", ".")
    run(*identity, "commit", "-m", "second: rename, modify, add, delete")
    return git_repo


@pytest.fixture()
def git_repo_with_edited_rename(git_repo: Path) -> Path:
    """The git repo after a second commit that renames and edits in one step.

    Because the renamed file's content changes in the same commit, the content
    hashes differ and the change engine must treat it as a delete plus an add
    rather than a deterministic rename.
    """

    def run(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=git_repo,
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

    (git_repo / "src" / "payments" / "service_renamed.py").write_text(
        "class PaymentService:\n    pass\n", encoding="utf-8"
    )
    run("rm", "src/payments/service.py")
    run(*identity, "add", ".")
    run(*identity, "commit", "-m", "second: rename and edit")
    return git_repo
