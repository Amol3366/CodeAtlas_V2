# Ephemeral sessions

CodeAtlas normally keeps everything: repositories, snapshots, embeddings, and
conversations survive a restart, because "how current is that evidence?" is one
of the five questions the product exists to answer and an index rebuilt from
nothing every morning answers it slowly.

Ephemeral mode is the deliberate exception. It starts from empty storage and
throws it away when the server stops. It is for working *on* CodeAtlas, where a
session that inherits the last run's repositories and conversations makes new
behavior hard to tell from residue.

**It is never the default, and it never opens your real database.** See
ADR-0013.

## Turning it on

```powershell
uv run codeatlas serve --web --ephemeral --open
```

Or, for a shell where every run should be ephemeral:

```powershell
$env:CODEATLAS_EPHEMERAL = "1"
uv run codeatlas serve --web --open
```

Accepted values for the variable are `1`, `true`, `yes`, and `on`, case
insensitive. Anything else — including `0` — means off.

The server prints one line so the mode is never a surprise:

```text
Ephemeral session: storage is empty and will be discarded.
```

## `--database` wins

If you pass `--db`, you get that database, ephemeral flag or not. Naming a
database is a deliberate instruction, and silently serving a throwaway one
instead would discard your choice without telling you.

## Opening on the repositories you care about

An empty session has no repositories, so by default you would re-add yours every
run. `CODEATLAS_EPHEMERAL_REPOSITORIES` avoids that. It holds semicolon-
separated absolute paths, and lives in the project `.env`:

```bash
CODEATLAS_EPHEMERAL_REPOSITORIES=C:\work\my-service;C:\work\my-web-app
```

Semicolons, because a Windows path contains a colon and may contain spaces.
Blank entries are dropped and duplicates removed, so a trailing `;` is harmless.

The file is read from **the CodeAtlas project folder, never the working
directory**. That is not a convenience — a repository you merely index must
never be able to configure the tool that indexes it.

At startup:

1. Each path is **registered synchronously**, before the server binds. A path
   that does not exist, is not a repository, or escapes its root is reported on
   stderr and skipped. One bad entry never stops the session from starting.
2. The registered repositories are then **indexed on a background thread**, one
   after another. The server binds immediately, so the application opens right
   away and reports real indexing progress through the usual status surfaces.

Indexing is sequential on purpose: SQLite takes one writer, so parallel indexing
would serialize on the write lock anyway while making progress harder to read.

## What a run costs

Every ephemeral run indexes from scratch. There is no incremental reuse, because
there is nothing to reuse — that is the point of the mode, not a defect. On a
large repository with embeddings enabled, expect the first minutes of a session
to be spent indexing. The application is usable throughout; answers simply
improve as coverage rises.

## Where the files go, and when they leave

```text
%LOCALAPPDATA%\CodeAtlas\sessions\<pid>-<utc timestamp>\
    codeatlas.db
    vectors\
```

Sessions sit beside the real data directory rather than inside it, so deleting
the whole `sessions` tree can never take your real database with it.

A clean stop — including Ctrl-C, which is the ordinary way this mode ends —
deletes the directory. A crash cannot, so the next ephemeral start sweeps any
session directory whose owning process is dead, or which is older than 24 hours.

The sweep uses the same process-liveness check as crash recovery, and inherits
its known limitation: a reused pid can make a dead session look alive. The age
rule collects it regardless, which bounds the leak rather than leaving it open.
See `docs/operations/crash-recovery.md`.

Deleting a session directory by hand is safe at any time. It holds no repository
truth — only derived data whose cost is re-indexing time.

## What does not change

Inside a session, everything behaves as it always does. History persists for the
run, streaming is cancellable and reconnect-safe, citations stay bound to the
snapshot that answered them, and evidence validation is untouched. Ephemeral
mode changes *where storage lives and how long it lasts* — nothing about what
CodeAtlas will claim or how it proves it.
