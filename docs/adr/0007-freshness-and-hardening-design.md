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

## Alternatives considered

- **Trusting filesystem events as truth.** Rejected: silent event loss on
  Windows makes this unsound, and the failure is invisible.
- **Polling instead of watching.** Rejected: on a large repository it burns CPU
  continuously to detect nothing, and the reconcile scan already provides the
  same guarantee at a far lower duty cycle.
- **File-copy backup.** Rejected: unsafe against an open WAL database.
- **An MSI installer.** Deferred: it adds an installer framework and elevated
  privilege for a tool that needs neither.
