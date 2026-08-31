"""Index five real repositories and assert each produces an active snapshot.

**Deliberately not part of any gate.** It needs the network and takes minutes;
a gate that requires the internet is not trustworthy offline, and this product
is local-first. Run it before a release, and after any change to parsing,
symbol identity, or chunk identity.

The five are not an arbitrary sample. **Every one of them failed to index
before ADR-0069**, each for a different language reason -- Java and Scala
overloads, Scala companions, Go function-local types, Rust methods implemented
for two traits -- so this is the smallest set that covers the defect class.

The reason this script exists at all is that the evaluation corpus could not
express the defect: every fixture is a two-file toy, so a probe over
``src/codeatlas`` finds zero collisions and seven phases of gates passed while
an eight-line Python file using a property could not be indexed. ADR-0041
through ADR-0045, ADR-0064 and ADR-0069 were all found by running the product
on real code. **A corpus that cannot express a defect reads as coverage.**

Usage::

    uv run python scripts/check_real_repos.py
    uv run python scripts/check_real_repos.py --only gson
    uv run python scripts/check_real_repos.py --workspace C:\\scratch\\repos
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.snapshot import SnapshotState
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import SymbolStore


@dataclass(frozen=True)
class Target:
    """One pinned repository and the floor its index must clear."""

    name: str
    url: str
    sha: str
    language: str
    min_files: int
    min_symbols: int


# SHAs resolved 2026-08-31. **Pinning is not optional**: an unpinned check that
# starts failing cannot tell you whether CodeAtlas changed or upstream did.
#
# The floors are set below the figures ADR-0069 measured, so that a parser
# improvement does not fail the check. A *drop* is the signal -- gson silently
# indexing half its API is the failure this guards, and a check asserting only
# "did not crash" would have passed on the day that happened.
TARGETS: tuple[Target, ...] = (
    Target(
        name="gson",
        url="https://github.com/google/gson",
        sha="b3f4ca20087f9066de4c340522ff84e0558e1ad1",
        language="java",
        min_files=300,
        min_symbols=4000,
    ),
    Target(
        name="cobra",
        url="https://github.com/spf13/cobra",
        sha="adbc8813901bba65827259daa8e22ff94ec1f30e",
        language="go",
        min_files=60,
        min_symbols=800,
    ),
    Target(
        name="gin",
        url="https://github.com/gin-gonic/gin",
        sha="dcaa4296d111981ffb31ac3eba90bb63e1eb5ab9",
        language="go",
        min_files=125,
        min_symbols=1900,
    ),
    Target(
        name="ripgrep",
        url="https://github.com/BurntSushi/ripgrep",
        sha="3fce3b5bb0236da2df6d99672afb8a719642eca7",
        language="rust",
        min_files=220,
        min_symbols=4100,
    ),
    Target(
        name="scalaz",
        url="https://github.com/scalaz/scalaz",
        sha="401c04c31d8cdd5a3b56fbb5795fd27c7d0732bf",
        language="scala",
        min_files=580,
        min_symbols=17000,
    ),
)


def fetch(target: Target, into: Path) -> Path:
    """Materialise the pinned commit, shallowly.

    A shallow fetch of the SHA itself rather than ``clone`` then ``checkout``:
    it moves one commit instead of the whole history, and it stays correct as
    upstream advances, where ``clone --depth 1`` would silently take whatever
    HEAD happens to be.

    Git is invoked as an argument array with ``shell=False``, the same rule the
    product's own Git adapter follows. An import path or a URL is untrusted
    text.
    """
    root = into / target.name
    root.mkdir(parents=True, exist_ok=True)

    # Already materialised at the pin: nothing to do. This is what makes
    # `--workspace` worth having, and it is checked against the SHA rather
    # than against the directory merely existing -- a half-fetched directory
    # must not read as a hit.
    if (root / ".git").exists():
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
        if head.returncode == 0 and head.stdout.strip() == target.sha:
            return root
    else:
        subprocess.run(
            ["git", "-C", str(root), "init", "--quiet"], check=True, shell=False
        )

    # Fetched from the URL directly rather than through a named remote. Adding
    # a remote is not idempotent -- `git remote add` exits 3 when one already
    # exists, which broke `--workspace` on its second run -- and the remote
    # served no purpose, because nothing here ever pushes or re-fetches.
    fetch_pinned_commit = [
        "git",
        "-C",
        str(root),
        "fetch",
        "--quiet",
        "--depth",
        "1",
        target.url,
        target.sha,
    ]
    subprocess.run(fetch_pinned_commit, check=True, shell=False)
    subprocess.run(
        ["git", "-C", str(root), "checkout", "--quiet", "FETCH_HEAD"],
        check=True,
        shell=False,
    )
    return root


def check(target: Target, root: Path, db: Path) -> str | None:
    """Return ``None`` when the repository indexes, else the reason it did not."""
    with connect(db) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        try:
            result = services.indexing.index(repository.repository_id)
        # Broad on purpose: any exception at all means this repository cannot
        # be indexed, which is exactly what the check exists to report. It is
        # returned as a reason rather than raised, so one bad repository does
        # not hide the other four.
        except Exception as error:
            return f"indexing raised {type(error).__name__}: {error}"

        if result.snapshot.state is not SnapshotState.ACTIVE:
            return f"snapshot state is {result.snapshot.state}, not ACTIVE"
        if result.snapshot.file_count < target.min_files:
            return (
                f"{result.snapshot.file_count} files, below the "
                f"{target.min_files} floor"
            )
        # `Snapshot` carries file counts but no symbol count -- verified
        # 2026-08-31 -- so the symbol floor is read from the store.
        symbols = SymbolStore(connection).count_for_snapshot(
            result.snapshot.snapshot_id
        )
        if symbols < target.min_symbols:
            return f"{symbols} symbols, below the {target.min_symbols} floor"
        print(
            f"    {result.snapshot.file_count} files, {symbols} symbols",
            flush=True,
        )
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Index pinned real repositories and report which fail."
    )
    parser.add_argument("--only", default=None, help="check one target by name")
    parser.add_argument(
        "--workspace",
        default=None,
        help="reuse this directory instead of a temporary one, so a rerun "
        "does not refetch",
    )
    args = parser.parse_args()

    targets = TARGETS
    if args.only:
        targets = tuple(item for item in TARGETS if item.name == args.only)
        if not targets:
            names = ", ".join(item.name for item in TARGETS)
            print(f"no target named {args.only!r}; have: {names}", file=sys.stderr)
            return 2

    # Two directories, on purpose. Clones are expensive and may be reused via
    # `--workspace`; **databases are always fresh**, because the thing being
    # measured is a cold index of a repository this database has never seen.
    # Reusing one made the second run fail with RepositoryAlreadyRegisteredError
    # -- caught 2026-08-31 by running `--workspace` twice, which is the only
    # way that flag's promise can be checked.
    #
    # `ignore_cleanup_errors` because Git leaves pack files read-only on
    # Windows and the automatic rmtree would otherwise raise on the way out --
    # failing the script for a housekeeping reason after the real work passed.
    clone_context = (
        nullcontext(args.workspace)
        if args.workspace
        else tempfile.TemporaryDirectory(
            prefix="codeatlas-real-", ignore_cleanup_errors=True
        )
    )
    database_context = tempfile.TemporaryDirectory(
        prefix="codeatlas-real-db-", ignore_cleanup_errors=True
    )

    failures: list[str] = []
    with clone_context as scratch, database_context as database_root:
        workspace = Path(scratch)
        workspace.mkdir(parents=True, exist_ok=True)
        databases = Path(database_root)
        for target in targets:
            started = time.monotonic()
            print(f"[{target.name}] fetching {target.sha[:8]}...", flush=True)
            try:
                root = fetch(target, workspace)
            except subprocess.CalledProcessError as error:
                print(f"[{target.name}] FETCH FAILED: {error}", flush=True)
                failures.append(f"{target.name}: fetch failed ({error})")
                continue
            print(f"[{target.name}] indexing...", flush=True)
            reason = check(target, root, databases / f"{target.name}.sqlite")
            elapsed = time.monotonic() - started
            if reason is None:
                print(f"[{target.name}] OK ({elapsed:.1f}s)", flush=True)
            else:
                print(f"[{target.name}] FAILED: {reason}", flush=True)
                failures.append(f"{target.name} ({target.language}): {reason}")

    if failures:
        print("\nFailures:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"\nAll {len(targets)} repositories indexed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
