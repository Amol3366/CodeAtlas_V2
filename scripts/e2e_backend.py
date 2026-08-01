"""Backend harness for the Playwright end-to-end suites.

This is test infrastructure, not the shipping entry point. The packaged
`codeatlas serve --web` command is P6-06's deliverable; building it here would
mean the end-to-end suites exercise a launcher invented for them rather than
the one users run. What this script provides instead is the smallest thing the
browser tests need: a database seeded with a real indexed repository, and a
server that can be stopped and started again against it.

The split into two subcommands is the whole point. `seed` creates state once;
`serve` is disposable and restartable. A restart-persistence test needs to kill
the process and bring it back up against the *same* database, which is only
possible if seeding is not part of starting.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import uvicorn

from codeatlas.api.app import create_app
from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.semantic import EmbeddingProviderKind
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

# The fixture repository. Small enough to index in well under a second, and
# shaped so that one exact-symbol question produces a citation with a caller
# relation behind it — which is what the onboard-to-citation workflow asserts.
SERVICE_SOURCE = '''"""Payment capture."""

from .idempotency import IdempotencyStore


class PaymentService:
    """Captures payments exactly once."""

    def __init__(self, store: IdempotencyStore) -> None:
        self.store = store

    def capture(self, key: str) -> str:
        """Capture a payment, guarded by an idempotency key."""
        return self.store.claim(key)
'''

IDEMPOTENCY_SOURCE = '''"""Idempotency keys."""


class IdempotencyStore:
    """Claims a key exactly once."""

    def claim(self, key: str) -> str:
        return key
'''

TEST_SOURCE = '''from payments.service import PaymentService


def test_capture_is_idempotent() -> None:
    assert PaymentService is not None
'''

README_SOURCE = """# Payments fixture

`PaymentService.capture` delegates to `IdempotencyStore.claim`.
"""


def _write_fixture_repository(root: Path) -> None:
    """Create the fixture repository on disk and commit it.

    Git is initialized because change analysis needs a repository with real Git
    state; identity is passed per command so the harness never depends on the
    developer's global Git configuration.
    """
    (root / "src" / "payments").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "src" / "payments" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "payments" / "service.py").write_text(
        SERVICE_SOURCE, encoding="utf-8"
    )
    (root / "src" / "payments" / "idempotency.py").write_text(
        IDEMPOTENCY_SOURCE, encoding="utf-8"
    )
    (root / "tests" / "test_service.py").write_text(TEST_SOURCE, encoding="utf-8")
    (root / "README.md").write_text(README_SOURCE, encoding="utf-8")

    identity = ("-c", "user.email=e2e@example.invalid", "-c", "user.name=E2E")

    def run(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

    run("init", "--initial-branch", "main")
    run(*identity, "add", ".")
    run(*identity, "commit", "-m", "initial")


def seed(workdir: Path) -> dict[str, str | int]:
    """Create the fixture repository, index it, and describe the result."""
    workdir.mkdir(parents=True, exist_ok=True)
    # Absolute throughout: the Node harness resolves these from a different
    # working directory, and a relative path would silently point elsewhere.
    workdir = workdir.resolve()
    repository_root = workdir / "fixture-repo"
    database = workdir / "codeatlas.db"

    # A second copy, deliberately left unregistered. The onboarding suite adds
    # and indexes it through the UI, which is the workflow being tested; adding
    # an already-registered path would only prove the duplicate check works.
    onboarding_root = workdir / "fixture-repo-onboarding"

    # A third repository whose provider policy already transmits. Nothing is
    # sent and no provider is constructed — the policy is a row, and setting one
    # for a provider whose extra is absent is a state a user can genuinely reach
    # (embedding then reports SEMANTIC_PROVIDER_UNAVAILABLE and deterministic
    # retrieval is unaffected). It exists so the settings suite can exercise the
    # transmitting disclosure without adding a gigabyte of torch to the gate.
    #
    # The display name is load-bearing: repositories list by display_name and
    # the shell defaults to the first, so a name sorting after
    # "payments-fixture" leaves every existing suite's default unchanged.
    transmitting_root = workdir / "fixture-repo-transmitting"

    if not repository_root.exists():
        _write_fixture_repository(repository_root)
    if not onboarding_root.exists():
        _write_fixture_repository(onboarding_root)
    if not transmitting_root.exists():
        _write_fixture_repository(transmitting_root)

    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(
                path=str(repository_root), display_name="payments-fixture"
            )
        )
        result = services.indexing.index(repository.repository_id)

        transmitting = services.registration.register(
            RegisterRepositoryRequest(
                path=str(transmitting_root), display_name="transmitting-fixture"
            )
        )
        # Indexed before the policy is set, so the snapshot exists and coverage
        # is a real fraction of real chunks rather than an empty answer.
        services.indexing.index(transmitting.repository_id)
        services.settings.update(
            transmitting.repository_id,
            embedding_provider=EmbeddingProviderKind.OPENAI,
            monthly_token_budget=1000,
        )

    return {
        "database": str(database),
        "repository_id": repository.repository_id,
        "repository_path": str(repository_root),
        "onboarding_repository_path": str(onboarding_root),
        "transmitting_repository_id": transmitting.repository_id,
        "transmitting_repository_path": str(transmitting_root),
        "snapshot_id": result.snapshot.snapshot_id,
        "file_count": result.snapshot.file_count,
        "symbol_count": result.snapshot.parsed_file_count,
    }


def serve(database: Path, port: int) -> None:
    """Run the API against one database on loopback.

    Loopback only, exactly as the product ships. A harness that bound to all
    interfaces to make itself easier to reach would be testing a different
    server from the one users run.
    """
    # Access logs are on and captured to a file by the Node harness. When a
    # browser test fails, the first question is always "what did the page
    # actually ask for, and what did it get" — and answering it from a log
    # beats re-running with instrumentation added by hand.
    uvicorn.run(
        create_app(database),
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    seed_parser = subcommands.add_parser("seed", help="Create and index the fixture.")
    seed_parser.add_argument("--workdir", type=Path, required=True)

    serve_parser = subcommands.add_parser("serve", help="Serve one database.")
    serve_parser.add_argument("--database", type=Path, required=True)
    serve_parser.add_argument("--port", type=int, required=True)

    arguments = parser.parse_args(argv)

    if arguments.command == "seed":
        workdir: Path = arguments.workdir
        print(json.dumps(seed(workdir), indent=2))
        return 0

    database: Path = arguments.database
    port: int = arguments.port
    serve(database, port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
