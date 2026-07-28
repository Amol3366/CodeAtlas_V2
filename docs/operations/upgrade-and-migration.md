# Upgrade and migration

Installing a new build is the easy part. The part that decides whether an
upgrade is trustworthy is what happens to the database that was already there —
a snapshot and a conversation history the user did not ask to risk.

Three rules govern it (ADR-0007, P6-07).

| Rule | Why |
| --- | --- |
| A pending migration is preceded by a checkpoint | A migration that can lose data must have a way back. The checkpoint is written and *verified* before any migration runs |
| A first run is not an upgrade | A database at version 0 has nothing to lose; checkpointing it would leave an empty file that looks like a way back |
| A newer database is refused, not used | Migrations are forward-only. A build that opened a schema from the future would answer plausibly right up until it wrote into a column whose meaning had changed |

## Upgrading

Nothing to do. Every command upgrades the database when it opens it, so the
first thing you run after installing a new build performs the upgrade.

The explicit command exists for when you would rather watch:

```powershell
codeatlas upgrade
codeatlas upgrade --json
```

It reports the version found, the version reached, which migrations ran, where
the checkpoint went, and what survived:

```text
Upgraded C:\Users\you\AppData\Local\CodeAtlas\data\codeatlas.db from schema 8 to 9.
The database as it was is kept at ...\codeatlas.db.pre-upgrade-v8.
Preserved: 3 conversations, 3 files, 4 messages, 1 repositories, 1 snapshots, 5 symbols.
```

Both paths are the same code. A second path that migrated would be a second set
of rules about when to checkpoint, and the two would drift.

`codeatlas doctor` reports the schema version it **found**, before the upgrade
its own database open performed — reporting the version it caused would answer a
question nobody asked.

## The checkpoint

Named for the version it preserves, not the one it upgrades to, because a user
hunting for a way back is looking for *the database as it was*:

```text
codeatlas.db.pre-upgrade-v8
```

It is a real database, taken through SQLite's online backup API and verified
before the migration proceeds — so `codeatlas restore` takes it, and the tests
prove that by restoring it rather than by asserting it exists.

It is not deleted afterwards. Disk is cheaper than a history you cannot get
back, and the file names its own version so an old one is obvious.

## When CodeAtlas refuses

```text
SCHEMA_VERSION_UNSUPPORTED: This database was written by a newer version of CodeAtlas.
```

You are running an older build against a database a newer one already upgraded.
Migrations are forward-only, so there is no honest way to read it. Two remedies,
both yours to choose:

- run the newer build again, or
- `codeatlas restore` the checkpoint that newer build wrote before upgrading.

The refusal is CLI exit code 3 and HTTP 409. Not retryable: trying again fails
identically, because the fix is a decision rather than a repeat.

## Installing over an existing installation

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1
```

Re-running the installer replaces the application folder and leaves the data
folder alone — the two are separate for exactly this reason. It **refuses while
CodeAtlas is running** from that folder: removing the folder under a live
process fails partway and leaves a half-replaced install, which is worse than
the old one it was fixing.

The installer names the database and says it will be upgraded on first run. It
does not upgrade it for you; an installer is not the place to be modifying data
a user has not been told about yet.

## How the upgrade path is tested

From a database written by a **real earlier build**, never a hand-written one.
`tests/fixtures/upgrade/schema_0008.db` was produced by checking out the commit
before migration `0009` and running that code — registering a repository,
indexing it, holding a conversation, archiving one thread and deleting another.
`scripts/make_upgrade_fixture.py` does this and refuses to run against the
current tree, because a fixture written by today's code would pass every test
and prove nothing.

A synthetic database would test the migration against someone's *reading* of the
old schema. The gate condition is about what the old code actually wrote.

The manifest beside the fixture declares its row counts, so "no snapshot and no
conversation was lost" is measured rather than asserted, and
`tests/end_to_end/test_packaged_build.py` runs the same upgrade through the
**packaged binary** — which is also what proves the bundled migrations are the
ones being applied.

To regenerate after a new migration lands, see `tests/fixtures/upgrade/README.md`.
