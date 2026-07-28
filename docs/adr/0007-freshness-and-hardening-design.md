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

### The upgrade path, as built (P6-07)

No decision above covers upgrading, which is the one operation in this phase
that touches a database the user already has something in. Four choices were
made and approved on 2026-07-28.

1. **The checkpoint is unconditional.** The Phase 6 constraint says a migration
   that *can* lose data must be preceded by a checkpoint. Deciding which
   migration qualifies makes safety depend on someone correctly labelling a
   future one, and an unmarked mistake is unrecoverable — so any pending
   migration against a database that already holds something is preceded by a
   verified copy. If the checkpoint cannot be written, **the migration does not
   run**: proceeding would satisfy the letter of an upgrade and none of its
   purpose. A database at version 0 is exempted, because a checkpoint of an
   empty file is not a way back, it only looks like one.

2. **A sixth error code, `SCHEMA_VERSION_UNSUPPORTED`.** Decision 7 declared
   four and P6-05 added a fifth; this one exists because an older build opening
   a *newer* database silently succeeded. `apply_migrations` saw a higher
   recorded version, had nothing to apply, and returned — after which the
   tables opened, the queries mostly worked, and writes would land in columns
   whose meaning had changed. That is the silent corruption this ADR's context
   names, reachable by the ordinary act of running yesterday's build. The guard
   lives in `apply_migrations` rather than only in the upgrade path, so no call
   site can bypass it by opening a connection directly. 409, CLI exit 3, not
   retryable — the remedy is to run the newer build or restore its checkpoint,
   and neither happens by trying again.

   `restore` already refused a newer *backup*. What was missing was the same
   refusal for the database the product opens every time it starts.

3. **Implicit on open, plus an explicit command.** Opening still upgrades, so a
   packaged upgrade simply works; `codeatlas upgrade` reports the version found,
   the migrations applied, the checkpoint path, and the rows preserved, for an
   upgrade worth looking at before it happens. Both go through one function —
   a second path that migrated would be a second set of rules about when to
   checkpoint. `doctor` plans *before* opening, so it reports the version it
   found rather than the one it caused.

4. **The prior-version database is real, and committed.** It was produced by
   checking out the commit before migration `0009` and running that code;
   `scripts/make_upgrade_fixture.py` does it and refuses to run against the
   current tree, because a fixture written by today's code would pass every test
   and prove nothing. Committing the artifact keeps the suite fast and free of a
   git dependency at test time. The manifest beside it declares its row counts,
   so "no snapshot and no conversation was lost" is measured.

No migration and no contract change: `SCHEMA_VERSION` stays 9 and
`contract_version` stays `"1.1"`. The new error code is additive.

### What validating on the artifact found (P6-08)

The consequences section predicted that "the packaged artifact becomes the thing
under test for performance and security, which means the gate gets slower and
more environment-dependent. That is the cost of testing what users actually
run." The cost was as expected. What was not expected is that measuring it would
find the phase's own decisions incomplete.

1. **Decision 1 made an old omission dangerous.** `prune` had existed since
   Phase 2, documented the retention policy, and **was never called by
   anything** — every index left its predecessor behind permanently. That was
   survivable while a human decided when to reindex. A watcher reindexes all
   day, which is decision 1 working exactly as designed, and it turned an
   unbounded database from a slow leak into the thing that pushed refresh
   *through* its 2 s target and stepped preflight from 4.6 s to 10.6 s.
   Retention now runs where snapshots are made, so the bound holds for every
   caller rather than depending on each one remembering.

   Worth stating as a general lesson: a policy that exists, is documented, and
   is tested can still be dead code. Its tests passed because they called it
   directly.

2. **The packaging rule needed the artifact to prove it.** ADR-0007 decision 6
   says packaging changes no runtime contract, and P6-06 asserted an unknown
   `/v1` path "stays a JSON 404". It stayed a 404 and was never JSON — a bare
   status with an empty body. The in-process test asserted only the absence of
   HTML, so it passed. The packaged security suite asserted the envelope, and
   failed.

3. **The server could stop answering under sustained change analysis.**
   Originally recorded here as an unfixed memory-fault crash; diagnosed properly
   and fixed on 2026-07-29.

   It was **uvicorn's access log**, written one line per request on the
   event-loop thread. A server launched with a pipe for stdout that nobody reads
   — a shortcut, a wrapper script, a test harness — fills that pipe within a few
   dozen lines, and the write that fills it blocks forever. Every request stops,
   not just the one in flight. `serve` now runs with `access_log=False`, which
   Section 17 asked for independently: this product writes no logs by default,
   and an access log records a request path per request.

   The lesson is about instrumentation rather than about logging. The original
   diagnosis rested on a stack captured under
   `faulthandler.dump_traceback_later(repeat=True)`, which walks frames from
   another thread while the interpreter runs — **the instrumentation faulted,
   and its fault looked like the bug**. It was the only observation that
   appeared to explain the others, so it displaced them. The observation that
   actually mattered was there the whole time: the failure moved with how much
   had been *logged*, not with how many requests had been made, which is a
   fixed-size buffer's fingerprint. `py-spy dump` against the live process named
   it in one line, without perturbing it.

## Alternatives considered

- **Trusting filesystem events as truth.** Rejected: silent event loss on
  Windows makes this unsound, and the failure is invisible.
- **Polling instead of watching.** Rejected: on a large repository it burns CPU
  continuously to detect nothing, and the reconcile scan already provides the
  same guarantee at a far lower duty cycle.
- **File-copy backup.** Rejected: unsafe against an open WAL database.
- **A synthetic prior-version database.** Rejected: it would test the migration
  against a reading of the old schema rather than against what the old code
  wrote, which is the one thing an upgrade test exists to check.
- **Warning instead of refusing when the database is newer.** Rejected: a
  warning does not stop the write that corrupts.
- **An MSI installer.** Deferred: it adds an installer framework and elevated
  privilege for a tool that needs neither.
