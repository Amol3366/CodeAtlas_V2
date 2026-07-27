# Continuous freshness

CodeAtlas watches each registered repository and refreshes its index when files
change, so the answer to "how current is this evidence?" stays "current" without
anyone running a command.

## The rule that shapes everything

**A filesystem event is a trigger, never an authority.** An event says *look
here*. A scan and a content hash decide what actually changed.

This is not caution for its own sake. Event delivery is lossy, duplicated, and
reordered on every platform, and on Windows a `ReadDirectoryChangesW` buffer
overflow drops events **silently** — the API reports success while telling you
nothing happened. Anything that treated the event stream as truth would produce
exactly the silent staleness the watcher exists to prevent.

So the watcher never concludes that a file changed. It decides only which paths
are worth looking at, and a full rescan decides the rest. That rescan is cheap
because unchanged content hashes reuse their existing chunks.

## What happens when you save a file

1. The observer reports paths under the repository root.
2. Paths outside the root, ignored paths, and the root itself are dropped.
3. Surviving paths enter a debounce window.
4. When the window closes, the repository is rescanned and reindexed.
5. Unchanged files reuse their chunks; changed ones are reparsed.

### The two windows

| Window | Default | Why it exists |
| --- | --- | --- |
| Quiet period | 0.75 s | One save is several events. This makes it one refresh. |
| Maximum delay | 5 s | A tree changing faster than the quiet period would otherwise postpone the batch forever — while the index goes stale fastest. |

The maximum delay is the one people forget. Without it a running build, or a
long checkout, starves the refresh at exactly the worst moment.

## Turning it off for one repository

On by default, because a watcher that stays off until asked answers the
freshness question with "stale, and you were not told". A network share or a
multi-gigabyte monorepo is a legitimate reason to want manual control.

```powershell
codeatlas repo watch <repository_id>            # report
codeatlas repo watch <repository_id> --disable
codeatlas repo watch <repository_id> --enable
```

Over HTTP:

```text
GET /v1/repositories/{repository_id}/watch
PUT /v1/repositories/{repository_id}/watch      {"enabled": false}
```

The setting is **persisted**, so it survives a restart: turning the watcher off
is a decision about the repository, not about the process that happened to be
running.

## Reading the status

```json
{
  "repository_id": "repo_...",
  "enabled": true,
  "running": true,
  "pending": false,
  "failure_count": 0,
  "last_error": null
}
```

`enabled` is the stored decision. `running` is the observed reality. **They
disagree when a watcher could not start** — a directory that vanished, exhausted
handles — and that is the case worth seeing. Reporting only the switch would
say "on" about a watcher that is not running.

`failure_count` and `last_error` accumulate when a triggered reindex fails. The
watcher deliberately survives those failures: dying on the first error would
leave the index silently stale, which is worse than retrying and reporting.

## What it does not cover yet

The watcher only reacts to events it receives. Events that were never delivered
— the silent buffer overflow above, or anything that changed while the process
was not running — need the periodic reconciling scan, which is **P6-03**. Until
that lands, a change missed by the event stream stays missed until something
else touches the repository.

Turning the watcher off does not make the index stale on its own; it makes it
stale *silently*, which is why the status endpoint reports the switch.
