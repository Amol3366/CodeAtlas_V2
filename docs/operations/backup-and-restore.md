# Backup, restore, and deletion

A backup a user believes in but cannot restore from is worse than no backup,
because it displaces the caution they would otherwise have. Everything here is
shaped by that (ADR-0007 decisions 4 and 5).

## Backing up

```powershell
codeatlas backup C:\backups\codeatlas-2026-07-28.sqlite
codeatlas backup C:\backups\atlas.sqlite --json
```

**Safe while CodeAtlas is running.** The copy goes through SQLite's online
backup API, not the filesystem. That distinction is the whole reason this
command exists: in WAL mode recent commits may still live in the `-wal` side
file, so copying the main database alone can miss them or capture a torn page —
producing a file that looks like a backup and is not one.

The copy is written beside the destination and moved into place only after it
passes its own integrity check. A failure therefore leaves **no half-written
file**, and never destroys the previous backup at the same path.

## Restoring

```powershell
codeatlas restore C:\backups\codeatlas-2026-07-28.sqlite
```

**Stop CodeAtlas first.** Restore is offline by decision: swapping the database
file underneath a serving process is a reliable way to corrupt it. The command
refuses while the database is in use, and says so.

Everything is checked before anything is written:

| Check | Failure |
| --- | --- |
| The backup exists | `RESTORE_INCOMPATIBLE` |
| It passes `PRAGMA integrity_check` | `INTEGRITY_CHECK_FAILED` |
| Its schema version is not newer than this build's | `RESTORE_INCOMPATIBLE` |
| The target is not in use | `RESTORE_INCOMPATIBLE` |

A **newer** schema is refused outright. Migrations are forward-only, so there is
no honest way to accept a database written by a later build. An **older** schema
restores fine and is upgraded on the next start — after a checkpoint, which is
the one backup nobody has to remember to take. See
`docs/operations/upgrade-and-migration.md`.

The database being replaced is kept beside it as `<name>.replaced`, because
restore is the most destructive operation the product has and a user who
restored the wrong file needs a way back. Stale `-wal` and `-shm` side files are
removed, since one left beside a restored database can resurrect the pages the
restore just replaced.

## Removing a repository

```powershell
codeatlas repo remove <repository_id>
codeatlas repo remove <repository_id> --cascade
```

```text
DELETE /v1/repositories/{repository_id}
DELETE /v1/repositories/{repository_id}?cascade=true
```

**Source files are never touched.** This removes the repository from CodeAtlas —
its snapshots, symbols, relations, and search projections — and nothing else.

It **refuses while conversations exist**, with
`REPOSITORY_HAS_CONVERSATIONS`, unless cascade is given. The schema cascades
`conversations` from `repositories`, so without this guard a user freeing index
space would silently lose chat history and find out only by going to look for
it. Soft-deleted conversations count: they are recoverable until purged, which
makes them data to lose.

## Retention

Deleting a conversation is soft — the row survives so the deletion is
recoverable. Retention is what eventually makes it permanent.

```powershell
codeatlas purge                      # deleted 30+ days ago
codeatlas purge --older-than-days 0  # everything already deleted, gone now
```

The same sweep runs **once when the application starts**, never on the request
path: a policy measured in days does not belong on a hot path, and P6-04's
lesson was that per-request work is where this kind of thing goes wrong. An
unattended install is covered by its next restart.

**An undeleted conversation is never touched**, whatever the window. That is
enforced in the query rather than in a caller, so no caller can widen it.
Messages, runs, and evidence links go with the conversation they belong to.

## What is not covered

- **Backups are not scheduled.** There is no timer and no retention policy for
  backup *files*; `codeatlas backup` runs when something runs it. Wiring it to
  Task Scheduler is a user decision, and the product does not make it.
- **Restore has no REST endpoint.** Deliberate: see above, and `CLAUDE.md`
  Section 12, which specifies none.
- **A repository's index is not portable.** A backup is a database, not an
  export format; restoring it onto a machine where the repository roots do not
  exist leaves repositories that resolve to nothing. `codeatlas doctor` reports
  those as `ROOT_MISSING`.
- **A backup does not contain the OpenAI API key.** The credential lives in the
  Windows Credential Manager, not in the database (ADR-0015), so restoring onto
  a different machine or user account means entering the key again there —
  or supplying it through `.env`.

  This is deliberate rather than an oversight. The database is the file most
  likely to be copied elsewhere or attached to a support request, and a
  credential that travelled with it would be disclosed by the most ordinary
  troubleshooting step there is.
