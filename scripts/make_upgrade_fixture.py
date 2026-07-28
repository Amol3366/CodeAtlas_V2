"""Produce an upgrade fixture by running a *real* prior version of CodeAtlas.

The Phase 6 plan requires the upgrade path to be tested "from a real
prior-version database, not a synthetic one". Hand-writing schema-8 SQL would
prove the migration against my reading of the old schema rather than against
what the old code actually wrote — which is the one thing an upgrade test exists
to check.

So this script imports an older checkout and drives it: register a repository,
index it, hold a conversation, archive one thread and delete another. The
resulting database file is committed under ``tests/fixtures/upgrade/`` together
with a manifest of what it contains, and the upgrade tests assert that every one
of those rows survives.

Usage (from the repository root, with a worktree at the prior commit):

    git worktree add ../codeatlas-prior <commit>
    uv run python scripts/make_upgrade_fixture.py \
        --prior-src ../codeatlas-prior/src \
        --output tests/fixtures/upgrade/schema_0008.db

The script refuses to import anything from the current tree: ``--prior-src`` is
placed at the front of ``sys.path`` and the loaded package is checked against it
before any work happens. A fixture accidentally written by the *current* code
would pass every test and prove nothing.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_SOURCE_FILES = {
    "src/payments/service.py": (
        '"""Payment capture, used as fixture content."""\n'
        "\n"
        "\n"
        "class PaymentService:\n"
        "    def capture(self, idempotency_key: str) -> str:\n"
        "        return self.settle(idempotency_key)\n"
        "\n"
        "    def settle(self, idempotency_key: str) -> str:\n"
        "        return idempotency_key\n"
    ),
    "src/payments/__init__.py": "",
    "docs/payments.md": "# Payments\n\n`PaymentService.capture` is idempotent.\n",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-src", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()

    prior_source = arguments.prior_src.resolve()
    if not (prior_source / "codeatlas").is_dir():
        print(f"no codeatlas package under {prior_source}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(prior_source))
    import codeatlas

    loaded = Path(codeatlas.__file__ or "").resolve()
    if prior_source not in loaded.parents:
        # The current package was importable first — every fixture this run
        # produced would carry today's schema while claiming to be the old one.
        print(f"codeatlas resolved to {loaded}, not {prior_source}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as scratch:
        manifest = _build(Path(scratch), arguments.output.resolve())

    print(json.dumps(manifest, indent=2))
    return 0


def _build(scratch: Path, output: Path) -> dict[str, Any]:
    from codeatlas.application.container import build_services
    from codeatlas.application.registration import RegisterRepositoryRequest
    from codeatlas.storage.sqlite.connection import connect
    from codeatlas.storage.sqlite.migrations import SCHEMA_VERSION, apply_migrations

    repository_root = _write_repository(scratch / "repository")
    staging = scratch / "fixture.db"

    with connect(staging) as connection:
        version = apply_migrations(connection)
        services = build_services(connection)

        repository = services.registration.register(
            RegisterRepositoryRequest(
                path=str(repository_root), display_name="payments"
            )
        )
        result = services.indexing.index(repository.repository_id)

        answered = services.conversations.create(
            repository.repository_id, title="Capture flow"
        )
        submitted = [
            services.conversations.submit(
                answered.conversation_id, "Where is PaymentService.capture defined?"
            ),
            services.conversations.submit(
                answered.conversation_id, "Who calls PaymentService.settle?"
            ),
        ]

        archived = services.conversations.create(
            repository.repository_id, title="Archived thread"
        )
        services.conversations.archive(archived.conversation_id)

        removed = services.conversations.create(
            repository.repository_id, title="Deleted thread"
        )
        services.conversations.delete(removed.conversation_id)

        manifest: dict[str, Any] = {
            "produced_by": _describe_prior_version(),
            "schema_version": version,
            "declared_schema_version": SCHEMA_VERSION,
            "repository_id": repository.repository_id,
            "repository_display_name": repository.display_name,
            "active_snapshot_id": result.snapshot.snapshot_id,
            "conversations": {
                "answered": answered.conversation_id,
                "archived": archived.conversation_id,
                "deleted": removed.conversation_id,
            },
            "messages": _message_manifest(submitted),
            "row_counts": _row_counts(connection),
        }

        # Fold the WAL back into the main file so the committed fixture is one
        # file. A `-wal` left beside it would be a second, uncommitted half.
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staging, output)
    for suffix in ("-wal", "-shm"):
        Path(f"{output}{suffix}").unlink(missing_ok=True)

    manifest["file"] = output.name
    manifest["size_bytes"] = output.stat().st_size
    (output.with_suffix(".json")).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _write_repository(root: Path) -> Path:
    """Create a small real Git repository for the prior version to index."""
    for relative, content in _SOURCE_FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    for arguments in (
        ["init", "--initial-branch=main"],
        ["config", "user.email", "fixture@codeatlas.invalid"],
        ["config", "user.name", "CodeAtlas Fixture"],
        ["add", "-A"],
        ["commit", "-m", "fixture repository"],
    ):
        # Fixed argv, no shell, inside a directory this script just created.
        subprocess.run(
            ["git", *arguments], cwd=str(root), check=True, capture_output=True,
            timeout=60,
        )
    return root


def _message_manifest(submitted: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "message_id": result.message_id,
            "run_id": result.run_id,
            "status": str(result.status),
            "content": result.content,
            "evidence_count": len(result.evidence),
        }
        for result in submitted
    ]


def _row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """Count every table the upgrade must not empty."""
    counts: dict[str, int] = {}
    for table in (
        "repositories",
        "snapshots",
        "files",
        "symbols",
        "relations",
        "chunks",
        "conversations",
        "messages",
        "message_runs",
        "message_evidence",
    ):
        row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        counts[table] = int(row[0])
    return counts


def _describe_prior_version() -> str:
    """Record which commit wrote the fixture, so it can be reproduced."""
    try:
        # Fixed argv, no shell; the path is this script's own prior source.
        described = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(sys.path[0]).parent),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return described.stdout.strip() if described.returncode == 0 else "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
