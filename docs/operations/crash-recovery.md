# Crash recovery

A process that is killed mid-index — power loss, `taskkill /F`, an OOM kill —
leaves work half done. CodeAtlas heals it on the next start, and **says what it
healed**, because a repository whose last index was interrupted must not look
identical to one that was never indexed. The remedies differ, and a user who
cannot tell them apart cannot act on either.

## What a kill actually leaves behind

An exception is not a kill. When `index()` raises, its `except` block runs and
closes the job. A killed process runs no Python at all: no `except`, no
`finally`, no `atexit`. Three things survive it.

| Left behind | Consequence if nothing heals it |
| --- | --- |
| A snapshot stuck mid-build | Never activated, but never cleaned up either |
| An `index_jobs` row stuck at `running` | **Indexing is blocked forever.** `active_job_for` keeps reporting a run in progress, so every reindex — manual, watcher-triggered, or from the reconciling scan — raises `INDEX_IN_PROGRESS`. The repository goes silently stale for good. |
| The dead snapshot's derived rows | Unreachable through snapshot membership, but present — and the FTS projections are reachable by search, because no foreign key cascades to a virtual table |

Recovery runs during service construction and fixes all three. The snapshot row
itself is kept, in state `failed`: it is the record of what happened, and the
thing diagnostics names.

## Recovery never heals a run that is still alive

This is the part that is easy to get wrong. Recovery runs inside
`build_services`, which is **per request**, while the watcher indexes on a
background thread. "Fail everything unfinished" would therefore abort the index
running in the next thread over — and the periodic reconciling scan makes that
collision routine rather than rare.

So every run records an owner when it starts, and recovery heals only runs whose
owner is gone.

| Signal | Meaning |
| --- | --- |
| The owner's token is this process's | A thread in this very process owns it. Alive by construction — no system call, no ambiguity. |
| A different token, owner process exists | Another CodeAtlas process, e.g. a `codeatlas index` run in a terminal while the API serves. Left alone. |
| A different token, owner process is gone | Abandoned. Healed. |
| No owner recorded | Unowned, therefore healed. This is what lets a database written before ownership existed be repaired on upgrade rather than staying blocked. |

The owner lives in the job's existing `diagnostics` JSON rather than a new
column: it is transient — `finish` overwrites it, and a finished job is never a
recovery candidate — so it needs no schema of its own. **No migration was added
for any of this**; `SCHEMA_VERSION` stays 9.

On Windows the liveness check calls `OpenProcess` through `ctypes`. It cannot
use the POSIX idiom `os.kill(pid, 0)`, because Python implements `os.kill` on
Windows with `TerminateProcess` for any signal other than the console control
events — the idiom for *asking whether a process exists* would **kill it**.

### The limitation, stated plainly

**Pid reuse is not detected.** If the operating system reassigns a dead owner's
pid before CodeAtlas next starts, its run looks alive and is left alone —
meaning that repository stays blocked. The failure is visible rather than
silent: `codeatlas doctor` reports the blocking run and the pid it belongs to.
Closing it properly needs the owner's process start time, which has no portable
source without a new dependency.

## Reading the report

```powershell
codeatlas diagnostics <repository_id>
```

```json
{
  "interrupted_run": {
    "snapshot_id": "snap_...",
    "stage": "chunking",
    "started_at": "2026-07-28T13:40:11Z",
    "recovered_at": "2026-07-28T13:52:03Z"
  },
  "warnings": ["INDEX_RUN_INTERRUPTED"]
}
```

Also on `GET /v1/repositories/{repository_id}/diagnostics`, where
`interrupted_run` and `open_jobs` were added as optional fields — an existing
client that ignores them sees exactly the response it already knew, which is why
`contract_version` did not move.

The report describes a **live condition, not a permanent scar**. Once the
repository has been indexed successfully, its last index was not interrupted,
and the report stops — saying otherwise would be false.

## `codeatlas doctor`

One command for the whole installation: the product's fifth question — "what
does CodeAtlas not know?" — asked about the install rather than about a query.

```powershell
codeatlas doctor                       # every registered repository
codeatlas doctor <repository_id>       # just one
codeatlas doctor --json                # for scripts and issue reports
```

```text
CodeAtlas doctor

payments  [repo_4f2a...]
  snapshot: snap_9c1e...  files: 128  symbols: 902
  watching: on
  last index was interrupted during chunking (recovered 2026-07-28T13:52:03Z); reindex to refresh
  problems: INDEX_RUN_INTERRUPTED

Problems were found.
```

| Problem | Meaning |
| --- | --- |
| `NEVER_INDEXED` | No active snapshot. Index it. |
| `INDEX_RUN_INTERRUPTED` | The last run was killed and has been healed. Reindex to refresh. |
| `INDEX_RUN_IN_PROGRESS` | A run is open. Either genuinely in flight, or owned by a pid that cannot be verified — the owner is printed so the two can be told apart. |
| `ROOT_MISSING` | The repository directory is gone. Diagnosis does not require the thing being diagnosed to be healthy. |
| `PARSE_ERRORS` | Files that could not be parsed. Coverage is partial, not wrong. |

**Exit code 4 means problems were found**, which is a different fact from the
command failing (non-zero for the usual reasons). A script needs to tell them
apart.

The JSON output deliberately omits the absolute repository root. The CLI is
local, but its JSON is what gets pasted into a bug report, and the absolute path
is the part that carries a username.
