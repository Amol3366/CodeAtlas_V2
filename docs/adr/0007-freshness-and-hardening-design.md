# ADR-0007 — Continuous Freshness and Hardening

Status: accepted
Date: 2026-07-28
Deciders: user (approved the Phase 6 plan and its defaults on 2026-07-28)
Related: ADR-0002 (indexing), ADR-0006 (web application),
`docs/plans/phases/phase-06-freshness-and-hardening.md`

## Context

Phases 0–5 built a product that works when a developer runs it from source and
tells it when to index. Phase 6 has to make it work when nobody is telling it
anything: files change while the app is idle, processes get killed, disks fill,
databases get restored from last week, and the thing is launched from an
installed executable rather than `uv run`.

Three failure modes drive every decision here. **Silent staleness** — answering
from an index that no longer matches the disk, with no warning. **Silent
corruption** — answering from a database that is damaged. **Silent loss** — an
upgrade or a restore that discards a snapshot or a conversation without saying
so. All three share the word that makes them dangerous.

## Decision

### 1. The watcher is a trigger, never an authority

```text
filesystem events ──▶ debounce ──▶ scan affected subtree ──▶ hash compare
                                                          ──▶ incremental index
periodic reconcile ─────────────▶ full scan compare
```

An event says "look here". A scan and a content hash decide what actually
changed. This is not defensive pedantry: filesystem event delivery is lossy,
duplicated, and reordered on every platform, and on Windows a `ReadDirectoryChangesW`
buffer overflow drops events **silently** — the API reports success while
telling you nothing happened. A watcher trusted as truth would therefore produce
exactly the silent staleness this phase exists to prevent.

The periodic reconciling scan is the only defense against that overflow, so it
is not optional and not configurable to zero.

### 2. Watcher on by default, disableable per repository

The product's third question is "how current is that evidence?". A watcher that
is off until asked answers it with "stale, and you were not told". The debounce
plus reconcile design is what bounds the cost, so the friendlier default is also
the affordable one.

A repository can disable it individually — a network share or a
multi-gigabyte monorepo is a legitimate reason to want manual control.

### 3. Recovery reports what it recovered

Startup recovery already exists (Phase 2) and is silent. Phase 6 makes it
speak: a repository whose last index was interrupted says so in its
diagnostics, rather than looking identical to one that was never indexed. The
distinction matters because the remedies differ.

### 4. Backup uses the online backup API; restore validates before replacing

SQLite in WAL mode cannot be safely copied while open — a file copy can capture
a torn page and produce a backup that restores into corruption. Backup
therefore uses SQLite's online backup API.

Restore validates the schema version and runs an integrity check **before**
replacing anything, and refuses rather than half-restoring. A backup a user
believes in but cannot restore from is worse than no backup, because it
displaces the caution they would otherwise have.

A database written by a newer schema version is refused outright:
`RESTORE_INCOMPATIBLE`. Migrations are forward-only, so there is no honest way
to accept it.

### 5. Retention: an explicit purge plus a 30-day sweep

Phase 5 left soft-deleted conversations recoverable forever. Phase 6 adds both
a purge action (a user who wants it gone now can say so) and a time-based sweep
defaulting to 30 days (an unattended install does not accumulate deletions
forever). Neither touches an undeleted conversation.

### 6. Packaging: PyInstaller, one executable, loopback only

A single executable serves the API on loopback and the built SPA from
`StaticFiles`. No installer framework and no elevated privilege: this is a
single-user local tool that writes only to its own data directory, and an MSI
would add both for no benefit the product needs.

`codeatlas serve --web` — deferred in Phase 5 — lands here, because packaging
is what makes it meaningful.

**Packaging changes no runtime contract.** A packaged build must answer exactly
what a source checkout answers; a difference is a defect, not a packaging
detail.

### 7. Four error codes

| Code | HTTP | CLI | Retryable |
| --- | --- | --- | --- |
| `WATCHER_UNAVAILABLE` | 409 | 3 | yes |
| `BACKUP_FAILED` | 409 | 6 | yes |
| `RESTORE_INCOMPATIBLE` | 422 | 2 | no |
| `INTEGRITY_CHECK_FAILED` | 409 | 3 | no |

The retryable ones are the transient ones. Marking a corrupted database or an
incompatible backup retryable would send a user in a circle.

### 8. Playwright covers the three deferred suites

Restart persistence, stream reconnection, and the onboard-to-citation workflow
— the three Phase 5 gate conditions that were approved as only partly met. The
wider Section 14 workflow set is worth having but is not the debt Phase 5
incurred; P6-08 may propose it once the harness exists.

## Consequences

- A background thread now exists in a product that had none, so its failure
  modes (exhausted handles, a vanished directory, an overflowed buffer) become
  user-visible states rather than crashes.
- The packaged artifact becomes the thing under test for performance and
  security, which means the gate gets slower and more environment-dependent.
  That is the cost of testing what users actually run.
- Retention becomes a policy with a default, which is a user-visible behavior
  change: deletions that were permanent-but-recoverable now expire.

## Outcome

Recorded as implementation proceeds. The decisions above are unchanged; this
section says what building them added.

### Decision 3, as built (P6-04)

The decision said recovery should speak. Implementation found that it first had
to become **safe**, and that two of the three things a kill leaves behind were
not being healed at all.

1. **A killed process left its `index_jobs` row at `running`, and nothing ever
   cleared it.** Only `finish` does, and it runs in `index()`'s `except` block —
   which a raised exception reaches and a kill never does. While that row
   survived, `active_job_for` reported an index in progress forever, so every
   reindex was refused: manual, watcher-triggered, and reconciling-scan alike.
   A repository killed once could never be indexed again, and went silently
   stale for good — the exact failure this ADR's context names. The existing
   crash tests missed it because all of them simulate the crash by raising
   inside `index()`, which closes the job.

2. **Recovery could kill a live index.** It failed *every* non-terminal
   snapshot, and it runs inside `build_services`, which is per request and also
   runs on the watcher's background thread. A request arriving mid-index marked
   the live snapshot `FAILED` underneath the thread still building it. Decision
   1's periodic reconciling scan (P6-03) turned that from rare into routine.
   Fixed by recording an owner on every run and healing only runs whose owner
   is gone; `codeatlas.indexing.ownership` holds the reasoning, and the pid-reuse
   limitation is stated there rather than hidden.

3. **Derived rows and FTS projections** of a dead snapshot are now cleared,
   while the snapshot row is kept as the record of what failed. The tables are
   discovered from the schema's foreign keys rather than listed, so a later
   migration adding a snapshot-scoped table is covered without anyone
   remembering.

4. **`codeatlas doctor`** — required by blueprint section 6.2 and never built —
   landed here, because what it most needs to report is what recovery found.

None of this needed a migration: the owner lives in the job's existing
`diagnostics` JSON, and `SCHEMA_VERSION` stays 9. The REST additions are
optional fields, so `contract_version` stays `"1.1"`.

### Decisions 4 and 5, as built (P6-05)

Both decisions held. Implementation added three things worth recording.

1. **A fifth error code, `REPOSITORY_HAS_CONVERSATIONS`.** Decision 7 declared
   four; this one is beyond them, and it exists because the schema cascades
   `conversations` from `repositories`. A plain repository deletion therefore
   takes chat history silently — the "silent loss" this ADR's context names —
   so deletion refuses while conversations exist unless the caller explicitly
   cascades. 409, CLI exit 2, not retryable: retrying deletes nothing extra,
   because the fix is a decision rather than a repeat.

2. **Repository deletion did not exist at all.** `CLAUDE.md` Section 12.1
   specifies `DELETE /v1/repositories/{id}` and blueprint 3.1 requires removing
   a repository without deleting its source files, but neither the endpoint nor
   a CLI equivalent had ever been built. Gate condition 6 measures deletion, so
   it was built here rather than left to make the gate unprovable.

3. **The retention sweep runs once at startup**, never on the request path. The
   decision fixed the 30-day window but not the trigger; P6-04 had just shown
   what per-request work costs. An unattended install is covered by its next
   restart, which is the trade taken knowingly.

Restore is **CLI-only**, matching Section 12, which specifies no endpoint for
it: validating and swapping the database file underneath a serving process is
the corruption this phase exists to prevent. It refuses while the target is in
use, keeps the database it replaced, and clears stale WAL side files — one left
beside a restored database can resurrect the pages the restore just replaced.

### Decision 6, as built (P6-06) — with one approved deviation

**The build is onedir, not `--onefile`.** The decision says "a single
executable", and `--onefile` matches that wording most literally. It was
rejected on measurement rather than taste: `--onefile` re-extracts the whole
~44 MB bundle to `%TEMP%` on *every* launch, which costs seconds of startup for
a command-line tool and is a well-known trigger for Windows antivirus
heuristics. onedir starts immediately and loads the native tree-sitter
extensions from disk. It remains one command the user runs, which is what the
decision was asking for. **Approved by the user on 2026-07-28**, recorded here
rather than as a new ADR because the intent of decision 6 is unchanged.

Two things had to be bundled explicitly, and both would have failed late rather
than at build time:

- the built web application, or `serve --web` has nothing to serve;
- the SQL migrations, which are read through `importlib.resources`. A frozen
  build without them fails on a user's **first run against a fresh database** —
  the worst possible moment to discover a packaging omission.

`--host` on `serve` refuses anything but a loopback address. The decision said
"loopback only"; making that a refusal rather than a default means the property
cannot be lost by a flag.

Packaging enters the gate through an opt-in `-Package` switch, and the packaged
smoke tests **skip with their reason stated** when no artifact exists. A gate
that never built the artifact must not read as one that verified it.

## Alternatives considered

- **Trusting filesystem events as truth.** Rejected: silent event loss on
  Windows makes this unsound, and the failure is invisible.
- **Polling instead of watching.** Rejected: on a large repository it burns CPU
  continuously to detect nothing, and the reconcile scan already provides the
  same guarantee at a far lower duty cycle.
- **File-copy backup.** Rejected: unsafe against an open WAL database.
- **An MSI installer.** Deferred: it adds an installer framework and elevated
  privilege for a tool that needs neither.
