# Post-ADR-0069 Program

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: proposed. **Supersedes `2026-08-20-remaining-work.md`**, whose "What is
left" paragraph names three items that were closed or retracted later the same
day inside that same file. One authoritative plan, not two disagreeing ones.

Date: 2026-08-31
Authority: `AGENTS.md` is the contract. Live status is `docs/plans/PLAN.md`.

**Goal:** Land the ADR-0069 fix that is sitting uncommitted, then close the one
systematic gap it exposed — that the evaluation corpus cannot express the
defects that actually break real repositories.

**Architecture:** Five workstreams. One is bookkeeping the records already
claim is done (P0). Two build the instrument that would have caught ADR-0069
(P1-B, P2-B). One converts a measured-but-unsettled row into a ruling backed by
an adjusted number (P2-A). One is a parser feature that ADR-0069 deliberately
deferred, and it costs more than its follow-up note implies (P1-A).

**Tech Stack:** Python 3.12, pytest, Tree-sitter + `tags.scm`, SQLite, PowerShell
gate scripts, `uv`.

**Spec:** None, deliberately. In this repository specs pair with *feature
slices* (`docs/superpowers/specs/`); program plans — `2026-08-10-project-closeout`,
`2026-08-19-post-adr-0065-program`, `2026-08-20-remaining-work` — carry none.
Adding one here would create the second disagreeing document this plan exists to
remove. The design was agreed in session on 2026-08-31; the standing authorities
are `AGENTS.md`, ADR-0069, and the Deferred Register.

## Global Constraints

- `AGENTS.md` is release-blocking and overrides this plan.
- `SCHEMA_VERSION` **14**, `contract_version` **1.1**, `PARSER_BUNDLE_VERSION`
  **1.6.0**, `CHUNKER_VERSION` **1.1.0**, `RESOLVER_VERSION` **1.5.0**. Task 6
  is the only task permitted to change any of these, and only with an ADR.
- **The evaluation corpus is never edited to move a number** (ADR-0003). No task
  here adds a case to `tests/evaluation/cases/` except Task 5, which adds
  *expectations* for symbols an engine change creates.
- Handoff entries are **appended, never rewritten** (PLAN.md rule 8). A wrong
  earlier entry is corrected by a later one.
- No test is "passing" unless it was executed in this environment, with the
  command and exit code recorded.
- Repository code is never executed during indexing. Git is called through an
  argument-array subprocess, never a shell.

## Premises, checked rather than assumed

A stale premise is this project's most-recorded planning failure. Every row was
verified on 2026-08-31 before this plan was written.

| Premise | Checked by | Result |
| --- | --- | --- |
| ADR-0069 is committed | `git status` | **No.** 16 modified, 1 untracked ADR |
| How long it has been dirty | `git log -1`, file mtimes | Last commit **2026-08-22 22:30**, tree touched **23:47**; **9 days** |
| The records agree | reading register / README / memory vs. handoff log | **They do not.** Three say CLOSED; the newest handoff says "No fix applied" |
| A full gate has run since | README Tests row | **No.** Last complete run exited 0 at 2386; ADR-0069's 6 tests were verified stage-by-stage |
| Query-backed languages emit a signature | `grep signature engine.py` | **No.** `engine.py:172` hardcodes `signature=None` |
| Signature emission is free | reading `domain/symbols.py` | **No.** The discriminator hashes the signature, so emitting one moves storable ids. See Task 6 |
| The six constructs are covered | reading `test_symbol_identity_collisions.py` | **At parser level only.** Nothing indexes them end to end |

---

## Urgency

| Level | Meaning |
| --- | --- |
| **P0 — now** | The repository's records contradict themselves |
| **P1 — next** | Real risk or real capability, nothing blocks it |
| **P2 — scheduled** | Worth doing, no clock |
| **P3 — deferred** | Named trigger reopens it; do not start |

---

## File Structure

| File | Responsibility |
| --- | --- |
| `docs/plans/PLAN.md` | Handoff entries + Active Work stamps. Modified by Tasks 1, 7 |
| `tests/integration/test_colliding_constructs_index.py` | **Create.** End-to-end: a repository containing every known collision construct produces an active snapshot |
| `scripts/check_real_repos.py` | **Create.** Clones five pinned repositories and asserts each indexes |
| `scripts/check_real_repos.ps1` | **Create.** Windows entry point; deliberately outside the gate |
| `scripts/measure_phase7_perf.py` | **Modify.** Add a quiescence check before measuring |
| `docs/operations/release-validation.md` | **Modify.** Record the perf measurement protocol |
| `docs/adr/0070-*.md` | **Create, Task 6 only.** Signature emission and its reindex |
| `src/codeatlas/parsing/query_backed/profile.py` | **Modify, Task 6 only.** `signature_for` on the adapter |
| `src/codeatlas/parsing/query_backed/engine.py:172` | **Modify, Task 6 only.** Replace `signature=None` |

Task 5 is an investigation and is scoped to a throwaway branch; its file list is
inside the task.

---

# P0 — The records disagree with the code

## Task 1: Land ADR-0069

**Why this is first.** Three documents say the collision is CLOSED. The newest
handoff entry says *"No fix applied."* The fix is real and uncommitted. This is
the exact shape of the 2026-08-22T14:00Z failure — a prototype left uncommitted
in `engine.py` produced a handoff claiming a revert that never happened, and a
gate run on the dirty tree reported a regression in code `git log` said was
unchanged. That was one day. This is nine.

**Files:**
- Modify: `docs/plans/PLAN.md` (append handoff; update Active Work)
- Commit: the 16 modified files + `docs/adr/0069-a-symbol-is-identified-beyond-its-name.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a clean tree at a known commit. Every later task assumes this.

- [ ] **Step 1: Confirm what is actually uncommitted**

```bash
git status --short
git diff --stat
```

Expected: 16 ` M` entries and one `??` for the ADR. If anything else appears,
**stop and report** — an extra file means someone worked here since 2026-08-22
and this plan's premises need re-checking.

- [ ] **Step 2: Run the complete gate, in the background**

```bash
powershell -ExecutionPolicy Bypass -File scripts/check_phase4.ps1 -SkipSync
```

Run this with `run_in_background: true`. Two previous full runs were killed on
duration rather than failing, which is why the README's test count is stitched
together from stage runs. Do not kill it. Do not infer the result.

- [ ] **Step 3: Record the real outcome**

Capture the exit code and the pytest summary line verbatim. If it is non-zero,
**stop** — the fix does not land on a red gate, and a failure here is a finding
worth its own handoff, not something to work around.

- [ ] **Step 4: Append the handoff entry**

At the top of `## Handoff Log` in `docs/plans/PLAN.md` (entries are
newest-first). **Do not edit the 2026-08-22T18:00:00Z entry** — rule 8 forbids
it, and the 14:00Z entry is the precedent for correcting by appending.

The entry must carry: the ADR-0069 decision in one line; that it took three
fixes because two defects were hiding behind it (chunks, then the invented
`module_{file_id}` owner, then `relations.relation_id` on grouped Go/Rust
imports); that no version bumped and no reindex is needed; the exact gate
command and exit code from Step 3; and — explicitly — that the 18:00Z entry's
"No fix applied" was true when written and is superseded by this one.

- [ ] **Step 5: Update the Active Work table**

`docs/plans/PLAN.md` lines 50–59. Refresh `Task status` with the gate's real
test count, and `Git state` to say the tree is clean at the new commit. Leave
the version stamps at 14 / 1.1 / 1.6.0 / 1.1.0 / 1.5.0 — ADR-0069 moved none of
them, which is the point of its design.

- [ ] **Step 6: Commit and push**

```bash
git add -A
git commit -m "fix(identity): a symbol is identified beyond its name (ADR-0069)"
git push
```

- [ ] **Step 7: Verify the tree is actually clean**

```bash
git status --short
```

Expected: empty. This step exists because the failure being corrected here was
precisely a claim of cleanliness that `git status` would have disproved in one
command.

---

# P1 — Close the gap that let it ship

## Task 2: Index every colliding construct end to end

**Why the existing test is not enough.** `test_symbol_identity_collisions.py`
asserts at the **parser** level — that `parser.parse()` emits distinct
`symbol_id`s. Every one of the three follow-on defects lived *below* that line:
`logical_chunk_id` collided in the chunker, `query_relations` minted an invented
owner, and `relation_id` collided on grouped imports. The parser test would have
caught none of them. The layer that matters is "does a repository containing
this file produce an active snapshot".

**Files:**
- Create: `tests/integration/test_colliding_constructs_index.py`

**Interfaces:**
- Consumes: `build_services`, `RegisterRepositoryRequest`, `SnapshotState` — the
  same harness shape as `tests/integration/test_incremental_indexing.py:33-46`.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the failing test**

```python
"""A repository containing every known collision construct still indexes.

``test_symbol_identity_collisions.py`` asserts at the parser level, and every
defect ADR-0069 found *behind* the first one lived below that line: chunk
identity, an invented relation owner, and grouped-import relation ids. Only an
end-to-end index exercises those. Six of seven languages are represented; the
constructs are the ones measured on real repositories in ADR-0069.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.snapshot import SnapshotState
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

_SOURCES: dict[str, str] = {
    # Python: a property and its setter share qualified name and kind.
    "thing.py": (
        "class Thing:\n"
        "    @property\n"
        "    def value(self) -> int:\n"
        "        return self._v\n"
        "\n"
        "    @value.setter\n"
        "    def value(self, v: int) -> None:\n"
        "        self._v = v\n"
    ),
    # Java: method overloads -- gson collided in 55 files this way.
    "Codec.java": (
        "package app;\n"
        "\n"
        "public class Codec {\n"
        "    public String encode(String s) { return s; }\n"
        "    public String encode(int i) { return String.valueOf(i); }\n"
        "}\n"
    ),
    # Java: a file that defines nothing. This is what minted the invented
    # owner id `module_{file_id}` and made snapshot validation refuse.
    "package-info.java": "package app;\n",
    # Go: function-local type declarations -- cobra collided this way.
    "local.go": (
        "package app\n"
        "\n"
        "import (\n"
        "\tcrand \"crypto/rand\"\n"
        "\tmrand \"math/rand\"\n"
        ")\n"
        "\n"
        "func A() { type key struct{}; _ = key{}; _ = crand.Reader }\n"
        "func B() { type key struct{}; _ = key{}; _ = mrand.Int }\n"
    ),
    # Rust: one method name implemented for two traits.
    "s.rs": (
        "use std::fmt::{self, Display, Debug};\n"
        "pub struct S;\n"
        "impl Display for S {\n"
        "    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result { write!(f, \"s\") }\n"
        "}\n"
        "impl Debug for S {\n"
        "    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result { write!(f, \"S\") }\n"
        "}\n"
    ),
    # Scala: overloads, plus a companion trait/object pair -- scalaz collided
    # in 270 files on companions.
    "Codec.scala": (
        "package app\n"
        "\n"
        "trait Codec { def encode(s: String): String = s }\n"
        "object Codec { def encode(i: Int): String = i.toString }\n"
    ),
    # TypeScript: the passing control. It has its own disambiguator and must
    # keep working unchanged.
    "codec.ts": (
        "export function encode(s: string): string;\n"
        "export function encode(i: number): string;\n"
        "export function encode(v: string | number): string { return String(v); }\n"
    ),
}


@pytest.fixture()
def colliding_repo(tmp_path: Path) -> Path:
    root = tmp_path / "colliding"
    root.mkdir()
    for name, source in _SOURCES.items():
        (root / name).write_text(source, encoding="utf-8", newline="\n")
    return root


def test_a_repository_of_colliding_constructs_produces_an_active_snapshot(
    tmp_path: Path, colliding_repo: Path
) -> None:
    """Indexing succeeds and activates.

    Before ADR-0069 this raised ``sqlite3.IntegrityError: UNIQUE constraint
    failed`` inside ``_stage`` and produced **no snapshot at all**, so the
    repository could not be reached by any surface.
    """
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(colliding_repo))
        )

        result = services.indexing.index(repository.repository_id)

        assert result.snapshot.state is SnapshotState.ACTIVE, (
            f"indexing did not activate: state={result.snapshot.state}, "
            f"warnings={result.warnings}"
        )
```

- [ ] **Step 2: Run it and confirm it passes on the landed fix**

```bash
uv run pytest tests/integration/test_colliding_constructs_index.py -v
```

Expected: PASS. **This is a regression test for a fix that already landed, so a
first-run pass proves nothing yet.** Step 3 is what gives it teeth.

- [ ] **Step 3: Mutation-check it — required, not optional**

Temporarily neuter the fix and confirm the test fails:

```bash
# In src/codeatlas/domain/symbols.py, make ensure_unique_symbol_ids a no-op
# by returning `symbols` unchanged at the top of the function.
uv run pytest tests/integration/test_colliding_constructs_index.py -v
```

Expected: FAIL with an integrity error or a non-active snapshot. Then **revert
the mutation** and re-run to confirm PASS.

Repeat for `ensure_unique_chunk_ids`. If either mutation leaves the test green,
the test is not asserting what it claims and must be strengthened before it is
committed. This project has twice recorded a gap being "closed" by a test that
passed whatever the engine did.

- [ ] **Step 4: Confirm the tree is clean of mutations**

```bash
git diff --stat src/
```

Expected: empty. Step 3 edits source; this proves both edits came back out.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_colliding_constructs_index.py
git commit -m "test(indexing): a repository of colliding constructs must activate"
git push
```

---

## Task 3: A real-repository validation script

**Why a script and not a pytest gate member.** It needs the network and it is
slow — scalaz alone is 590 files / 17226 symbols. A gate that needs the internet
stops being trustworthy offline, which contradicts the product's own
local-first promise. This runs deliberately outside the gate. It is the half
that finds unknown-unknowns: ADR-0041 through ADR-0045, ADR-0064 and ADR-0069
were all found this way, and none was found by the corpus.

**Files:**
- Create: `scripts/check_real_repos.py`
- Create: `scripts/check_real_repos.ps1`

**Interfaces:**
- Consumes: `build_services`, `RegisterRepositoryRequest` (as Task 2).
- Produces: exit 0 when every pinned repository indexes; non-zero naming the
  first that does not.

- [ ] **Step 1: Write the script**

```python
"""Index five real repositories and assert each produces an active snapshot.

Deliberately NOT part of any gate. It needs the network and takes minutes; a
gate that requires the internet is not trustworthy offline, and this product is
local-first. Run it before a release and after any parser or identity change.

The repositories and SHAs are pinned. Every one of them failed to index before
ADR-0069, each for a different language reason, so this is the smallest set
that covers the defect class rather than an arbitrary sample.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
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


# SHAs resolved 2026-08-31. Counts are floors taken from the ADR-0069
# measurement, set below the observed figure so a parser improvement does not
# fail the check. A DROP is the signal.
TARGETS: tuple[Target, ...] = (
    Target(
        "gson",
        "https://github.com/google/gson",
        "b3f4ca20087f9066de4c340522ff84e0558e1ad1",
        "java",
        300,
        4000,
    ),
    Target(
        "cobra",
        "https://github.com/spf13/cobra",
        "adbc8813901bba65827259daa8e22ff94ec1f30e",
        "go",
        60,
        800,
    ),
    Target(
        "gin",
        "https://github.com/gin-gonic/gin",
        "dcaa4296d111981ffb31ac3eba90bb63e1eb5ab9",
        "go",
        125,
        1900,
    ),
    Target(
        "ripgrep",
        "https://github.com/BurntSushi/ripgrep",
        "3fce3b5bb0236da2df6d99672afb8a719642eca7",
        "rust",
        220,
        4100,
    ),
    Target(
        "scalaz",
        "https://github.com/scalaz/scalaz",
        "401c04c31d8cdd5a3b56fbb5795fd27c7d0732bf",
        "scala",
        580,
        17000,
    ),
)


def clone(target: Target, into: Path) -> Path:
    """Clone at a pinned SHA. Argument-array subprocess, never a shell."""
    root = into / target.name
    subprocess.run(
        ["git", "clone", "--quiet", target.url, str(root)],
        check=True,
        shell=False,
    )
    subprocess.run(
        ["git", "-C", str(root), "checkout", "--quiet", target.sha],
        check=True,
        shell=False,
    )
    return root


def check(target: Target, root: Path, db: Path) -> str | None:
    """Return None when the repository indexes, else the reason it did not."""
    with connect(db) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        try:
            result = services.indexing.index(repository.repository_id)
        except Exception as error:  # noqa: BLE001 - the failure is the finding
            return f"indexing raised {type(error).__name__}: {error}"

        if result.snapshot.state is not SnapshotState.ACTIVE:
            return f"snapshot state is {result.snapshot.state}, not ACTIVE"
        if result.snapshot.file_count < target.min_files:
            return (
                f"{result.snapshot.file_count} files, below the "
                f"{target.min_files} floor"
            )
        # Snapshot carries no symbol_count -- verified 2026-08-31, its count
        # fields are files only -- so the symbol floor is read from the store.
        symbols = SymbolStore(connection).count_for_snapshot(
            result.snapshot.snapshot_id
        )
        if symbols < target.min_symbols:
            return f"{symbols} symbols, below the {target.min_symbols} floor"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", help="check one target by name", default=None
    )
    args = parser.parse_args()

    targets = TARGETS
    if args.only:
        targets = tuple(t for t in TARGETS if t.name == args.only)
        if not targets:
            print(f"no target named {args.only}", file=sys.stderr)
            return 2

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="codeatlas-real-") as scratch:
        workspace = Path(scratch)
        for target in targets:
            print(f"[{target.name}] cloning {target.sha[:8]}...", flush=True)
            root = clone(target, workspace)
            print(f"[{target.name}] indexing...", flush=True)
            reason = check(target, root, workspace / f"{target.name}.sqlite")
            if reason is None:
                print(f"[{target.name}] OK", flush=True)
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
```

> **The SHAs above are already resolved** (2026-08-31) and the store APIs are
> already verified: `Snapshot.file_count` exists, `Snapshot.symbol_count` does
> **not**, and `SymbolStore.count_for_snapshot` (`stores.py:553`) is what
> supplies the symbol floor. **Pinning is not optional** — an unpinned check
> that starts failing tells you nothing about whether CodeAtlas changed or the
> upstream repository did. Keep both floors: a check that only asserts "did not
> crash" would have passed on the day gson silently indexed half its API.

- [ ] **Step 2: Write the PowerShell entry point**

```powershell
# Real-repository validation. Deliberately NOT part of any gate: it needs the
# network and takes minutes. Run before a release, and after any change to
# parsing, symbol identity, or chunk identity.
[CmdletBinding()]
param([string]$Only)

$ErrorActionPreference = "Stop"

$arguments = @("run", "python", "scripts/check_real_repos.py")
if ($Only) { $arguments += @("--only", $Only) }

& uv @arguments
exit $LASTEXITCODE
```

- [ ] **Step 3: Run it**

```bash
powershell -ExecutionPolicy Bypass -File scripts/check_real_repos.ps1 -Only gson
```

Expected: `[gson] OK`, exit 0. Then run without `-Only` for all five. Record the
real figures — they become the evidence line in the handoff.

- [ ] **Step 4: Commit**

```bash
git add scripts/check_real_repos.py scripts/check_real_repos.ps1
git commit -m "test(real-repos): five pinned repositories must index"
git push
```

---

# P2 — Scheduled

## Task 4: Give the perf harness a quiescence check

> **HALF OF THIS TASK WAS ALREADY DONE, AND THIS PLAN'S PREMISE WAS STALE.**
> Corrected 2026-08-31 on discovering `measure_phase7_perf.py:41` already
> imports `codeatlas.evaluation.quiescence`. The check landed in `e9952bb` on
> **2026-08-21 at 17:38+0530 — the same day** as the Deferred Register row
> asserting it did not exist, and the row was never updated.
>
> **The premise came from that row and was never checked against the code**,
> despite this plan opening with a "premises, checked rather than assumed"
> table. One `grep quiescence scripts/measure_phase7_perf.py` would have
> disproved it. That is the fourth stale-premise instance in this project's
> record and the first produced by a plan that explicitly guards against them —
> the guard works only on the premises you think to put in it.
>
> **What existed is better than what Steps 1-3 below specify**, which is the
> other reason not to have built it: it calibrates *before and after* so it
> catches a machine that moved mid-run, and it deliberately refuses to enforce
> an absolute speed threshold, because a hardware number with no reference
> would be one chosen to be passed (ADR-0032, ADR-0048). Steps 1-3 are
> therefore **not done and must not be**; they would have replaced a better
> design with a worse one.
>
> **Step 4 was genuinely outstanding** and is now done: the trigger read "a
> quiescence check, **or** a documented protocol", and only the first half had
> fired. The protocol is in `docs/operations/release-validation.md`.


**Why.** `measure_phase7_perf.py` stamps `refresh_target_met` from whatever the
machine can do at that instant. On 2026-08-21 it produced a published
regression claim that was retracted the same day: refresh p95 measured
1.413–2.433 s on one machine, one artifact, one harness — a range straddling the
≤ 2 s target. The loaded pair agreed within 26 ms and the quiet pair within
37 ms, 0.68 s apart. **Within-session agreement is not evidence of validity**,
and that was the load-bearing argument for the whole retracted finding.

**Files:**
- Modify: `scripts/measure_phase7_perf.py`
- Modify: `docs/operations/release-validation.md`

- [ ] **Step 1: Read the script's current entry point**

```bash
grep -n "def main\|refresh_target_met\|argparse" scripts/measure_phase7_perf.py
```

- [ ] **Step 2: Add the quiescence check**

Before measuring, sample idle CPU over a short window and refuse to stamp a
verdict on a loaded machine. Emit `quiescent: false` and leave
`refresh_target_met` **null** rather than false — an unmeasurable result is not
a failed one, and conflating them is what produced the retraction.

Add `--allow-load` for the case where someone deliberately wants a number from a
busy machine; it must set `quiescent: false` in the output so the figure can
never be quoted as a clean measurement later.

- [ ] **Step 3: Prove both branches**

Run once on an idle machine (expect `quiescent: true` and a real verdict), then
once while a full pytest run is in flight (expect the refusal). Record both.

- [ ] **Step 4: Document the protocol**

In `docs/operations/release-validation.md`: idle machine; at least two runs
separated by other work; **a figure within 15% of a threshold is unresolved, not
a pass or a fail**; and never quote a figure whose `quiescent` is false.

- [ ] **Step 5: Commit**

```bash
git add scripts/measure_phase7_perf.py docs/operations/release-validation.md
git commit -m "fix(perf): refuse to stamp a verdict on a loaded machine"
git push
```

---

## Task 5: Measure the `IMPORTS` cost properly, then bring the ruling

**The reframe this task exists for.** The register records: prototype works
(imports land inside their symbol, 4 of 4, one engine change for all four
languages) **but** twelve metrics move and every one moves down, including
`relation_path_recall` 1.0000 → 0.9062 against a target ADR-0058 gates at 1.0
absolutely. Read that way the choice looks like "accept the inconsistency or pay
a corpus update".

**That reading is not safe.** A per-file `MODULE` is a *legitimately real*
symbol. The corpus declares direct results (ADR-0059) and knows nothing about
these new symbols, so a metric drop is exactly what you would see whether the
engine got worse **or** the instrument simply went stale. This repository has run
that experiment six times — ADR-0017, 0018, 0024, 0027, 0038, 0051 — and every
one ended "the engine was right and the measurement was wrong". Ruling "accept"
on an unadjusted number would be the seventh instance, in the same direction.

**This task does not decide anything.** It produces an adjusted number so the
user can.

**Files (throwaway branch only):**
- Branch: `imports-compilation-unit-measurement`
- Modify: `src/codeatlas/parsing/query_backed/engine.py`
- Modify: `tests/evaluation/cases/` expectations, for the new `MODULE` symbols only

- [ ] **Step 1: Branch first — non-negotiable**

```bash
git switch -c imports-compilation-unit-measurement
```

The last time this prototype was applied it sat uncommitted on `main` for a day
and produced a handoff claiming a revert that never happened. A branch makes
that failure mode structurally impossible.

- [ ] **Step 2: Re-apply the prototype**

Emit a compilation-unit `MODULE` symbol per file in the shared engine. Clamp the
range: tree-sitter's root node ends one line past a trailing newline, and a naive
whole-file range **fails snapshot validation** with "a staged symbol has a line
range outside its file". That was measured on 2026-08-22 and is not a prediction.

- [ ] **Step 3: Measure unadjusted, to reproduce the recorded figures**

```bash
uv run python scripts/run_phase4_baseline.py --dataset tests/evaluation/cases --json-output "$SCRATCH/phase4-unadjusted.json"
```

Write to scratch, **never** over the tracked baselines. Confirm the twelve
recorded movements reproduce. If they do not, stop — the premise has changed and
this task needs rewriting.

- [ ] **Step 4: Update the corpus expectations for the new symbols**

This is the step the earlier measurement never ran. Each affected case gains
expectations for the `MODULE` symbols the engine now legitimately emits. Nothing
else changes — **no threshold is touched, and no case is edited to move a
number** (ADR-0003).

- [ ] **Step 5: Re-measure adjusted**

```bash
uv run python scripts/run_phase4_baseline.py --dataset tests/evaluation/cases --json-output "$SCRATCH/phase4-adjusted.json"
```

- [ ] **Step 6: Report all three columns**

Produce a table: metric, unadjusted, adjusted, target. **Do not recommend an
outcome in the same breath as the number** — present what the adjusted
measurement shows, and let the ruling be the user's.

- [ ] **Step 7: Return `main` to clean**

```bash
git switch main
git status --short
```

Expected: empty. Then verify the baselines still check:

```bash
uv run python scripts/run_phase4_baseline.py --dataset tests/evaluation/cases --check
```

Expected: exit 0. The branch is kept, not merged — it is evidence for the
ruling, not a change.

---

# P3 — Needs a ruling before it is work

## Task 6: Emit `signature` in the query-backed engine

**Do not start this without an explicit decision.** ADR-0069 lists it as a
follow-up, and the follow-up note reads as though it were free. Verified against
the code on 2026-08-31, it is not.

`domain/symbols.py` derives a colliding symbol's new id as
`stable_hash(symbol_id, signature, ordinal)`. `engine.py:172` currently hardcodes
`signature=None`, so for all four query-backed languages that hash uses the empty
string. **Emitting real signatures therefore changes the id of every
second-and-later member of every collision group** — and those ids are *storable
today*, because gson, scalaz, ripgrep, gin and cobra all index now. That is
exactly the reindex ADR-0069 was designed to avoid.

So this needs: a `PARSER_BUNDLE_VERSION` bump to 1.7.0, its own ADR, and every
user reindexing. The benefit is real — it converts an ordinal fallback into
stable identity for four languages, so inserting a same-named sibling stops
shifting its neighbours' ids — but it is a priced change, not a tidy-up.

- [ ] **Step 1: Present the trade to the user and get a decision.** Cost: a
  forced reindex for every existing snapshot. Benefit: same-named siblings in
  Java, Go, Rust and Scala stop reporting spurious changes when one is inserted
  above another. **Stop here until the answer comes back.**
- [ ] **Step 2 onward:** written only after the decision. Writing them now would
  be the plan asserting an outcome it has not been given.

---

## Deferred, with triggers

| Item | Why not now | Reopens when |
| --- | --- | --- |
| Unsigned executable | A purchasing decision, not engineering | A certificate is bought |
| Seven Chromium Playwright skips | Upstream renderer defect; Firefox runs all seven | Upstream fixes it |
| 1.05 GB semantic tree | Accepted at the Phase 7 activation gate | A deterministic-only second artifact is wanted |
| `changed_symbol_precision` 0.9531 | Structural; the corpus is not edited to move a number | **Never** |
| `restart-persistence` cross-suite leak; one unattributed `check_phase7` exit 1 | Each observed once, never reproduced | It recurs with output captured |
| `TRACE_FLOW` may be systemically mislabelled | Six cases carry it; three examined all classify as `text` | Someone rules the intent vocabulary |
| Resolution's remaining 3.55 s unprofiled | ADR-0064 declined to claim it optimal; no longer the bottleneck | Preflight becomes slow again |
| The ~8 "stated limit of the instrument" rows | Honest limits of corpus reach, not defects | **Re-read after Task 3** — real-repository coverage plausibly absorbs several, and re-reading is cheaper than closing them one at a time |

## What is deliberately not here

- **New languages beyond the seven.** C# and Kotlin ship no `tags.scm`; Ruby,
  PHP, Swift, C and C++ were measured and deferred. Each needs its own §25
  approval.
- **Test edges and route detection for the query-backed four.** Explicitly not
  approved by ADR-0065.
- **A Phase 8.** Phases 0–7 are complete and closed out. A new phase is a user
  decision, not a consequence of this list.

## Sequencing

```text
Task 1  Land ADR-0069 ─────────── P0, blocks everything (9 days dirty)
Task 2  Colliding constructs ──── P1, cheap, in-gate, needs Task 1
Task 3  Real-repository script ── P1, the half that finds unknown-unknowns
Task 4  Perf quiescence ───────── P2, independent of 2 and 3
Task 5  IMPORTS measurement ───── P2, ends in a ruling, not a change
Task 6  Signature emission ────── P3, BLOCKED on a decision
```

Tasks 2, 3 and 4 are independent of each other once Task 1 lands.
