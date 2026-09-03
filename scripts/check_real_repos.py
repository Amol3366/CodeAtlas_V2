"""Index five real repositories and assert each produces an active snapshot.

**In the gate since 2026-09-04, and the objection that kept it out was half
right.** This docstring used to read "deliberately not part of any gate -- it
needs the network and takes minutes". The network half stands and is now
designed around; the *minutes* half was never measured and is wrong. Timed
2026-09-04: **46.6 s wall for all five** in `--require-cached` mode, which is
what a gate runs, against a suite that takes twenty minutes. The cache is
**16 MB**.

Two numbers, because they are not the same measurement and quoting the larger
one as the gate's cost would overstate it: the first run, which fetched,
reported per-repository index times summing to ~75 s (gson 17.8, cobra 7.3,
gin 9.4, ripgrep 11.9, scalaz 28.0); the cached re-run finished in 46.6 s wall.

So `check_phase7.ps1` runs this with ``--require-cached``, which **never
fetches**: it checks the pins already materialised in the workspace and reports
the rest as NOT CHECKED without failing. A gate that needs the internet would
not be trustworthy offline for a local-first product; a gate that reads an
already-materialised checkout is just reading the disk.

**Why not an opt-in ``-RealRepos`` flag**, which is the obvious alternative:
this project has already paid for that shape. ``-Package`` was opt-in, four
ADR-0065 slices shipped without it, and `main` got an artifact that could not
start at all. `-Semantic` was opt-in and two tracked baselines sat stale for
two days behind it. **The leg nobody runs is where the defect lives**, so this
one runs by default and degrades to a loud notice instead of hiding behind a
flag.

Populate the cache once, with a network::

    $ws = "$env:LOCALAPPDATA\\CodeAtlas\\real-repos"
    uv run python scripts/check_real_repos.py --workspace $ws

Run it directly too, before a release and after any change to parsing, symbol
identity, or chunk identity.

**This check is the highest-yield thing in the repository's history and it is
worth saying so here.** ADR-0041 to ADR-0045, ADR-0064 and ADR-0069 were all
found by running the product on real code, including one -- indexing failing
outright, latent since Phase 1 -- that 2,400 passing tests could not see.

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


def cached_root(target: Target, into: Path) -> Path | None:
    """The materialised checkout for this pin, or ``None`` if it is not there.

    Checked against the **SHA**, never against the directory merely existing:
    a half-fetched or stale-pin directory must not read as a hit. Pure -- it
    creates nothing, because `--require-cached` calls it on a workspace that
    may legitimately be absent and a probe that mkdirs would leave a trail of
    empty directories that later look like partial checkouts.
    """
    root = into / target.name
    if not (root / ".git").exists():
        return None
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        shell=False,
        check=False,
    )
    if head.returncode == 0 and head.stdout.strip() == target.sha:
        return root
    return None


def fetch(target: Target, into: Path) -> Path:
    """Materialise the pinned commit, shallowly.

    A shallow fetch of the SHA itself rather than ``clone`` then ``checkout``:
    it moves one commit instead of the whole history, and it stays correct as
    upstream advances, where ``clone --depth 1`` would silently take whatever
    HEAD happens to be.

    Git is invoked as an argument array with ``shell=False``, the same rule the
    product's own Git adapter follows. An import path or a URL is untrusted
    text.

    **Never called under ``--require-cached``** -- that mode reads
    `cached_root` and nothing else, which is what lets a gate run this check
    without a network.
    """
    root = into / target.name
    root.mkdir(parents=True, exist_ok=True)

    # Already materialised at the pin: nothing to do. This is what makes
    # `--workspace` worth having.
    if (root / ".git").exists():
        if cached_root(target, into) is not None:
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
    parser.add_argument(
        "--require-cached",
        action="store_true",
        help="never fetch: check only the pins already materialised in "
        "--workspace, and report the rest as not checked. This is the mode a "
        "gate uses, so the gate never needs a network.",
    )
    args = parser.parse_args()

    if args.require_cached and not args.workspace:
        print(
            "--require-cached needs --workspace: without one the clones go to "
            "a fresh temporary directory, which is empty by construction, so "
            "every target would report as not cached and the check would "
            "always pass having measured nothing.",
            file=sys.stderr,
        )
        return 2

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
    uncached: list[str] = []
    with clone_context as scratch, database_context as database_root:
        workspace = Path(scratch)
        workspace.mkdir(parents=True, exist_ok=True)
        databases = Path(database_root)
        for target in targets:
            started = time.monotonic()
            if args.require_cached:
                cached = cached_root(target, workspace)
                if cached is None:
                    print(f"[{target.name}] NOT CACHED, not checked", flush=True)
                    uncached.append(target.name)
                    continue
                root = cached
                print(f"[{target.name}] cached at {target.sha[:8]}", flush=True)
            else:
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

    checked = len(targets) - len(uncached)

    # A gate must stay trustworthy offline, so an absent cache is NOT a
    # failure. It is announced loudly instead, with the exact command that
    # fixes it -- because the alternative this project has already paid for is
    # an opt-in leg nobody runs, which is how `-Package` shipped an artifact
    # that could not start.
    if uncached:
        print(
            f"\nNOT CHECKED: {', '.join(uncached)} "
            f"({len(uncached)} of {len(targets)}) are not cached in "
            f"{workspace}.",
            file=sys.stderr,
        )
        print(
            "  Populate it once, with a network, and every later run checks "
            "them offline:\n"
            f"    uv run python scripts/check_real_repos.py "
            f'--workspace "{workspace}"',
            file=sys.stderr,
        )

    if checked == 0:
        print("\nNo repository was checked.", file=sys.stderr)
        return 0

    print(f"\n{checked} of {len(targets)} repositories indexed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
