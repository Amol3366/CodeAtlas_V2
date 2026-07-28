# Prior-version upgrade fixtures

`schema_0008.db` was written by a **real earlier build of CodeAtlas** — the
commit recorded in `produced_by` in `schema_0008.json`, which is the last commit
before migration `0009`. It was not hand-written, and that is the point: the
Phase 6 plan requires the upgrade path to be tested "from a real prior-version
database, not a synthetic one", because a synthetic one tests the migration
against someone's *reading* of the old schema rather than against what the old
code actually wrote.

The `.json` manifest declares what the database contains — row counts, the
repository and snapshot IDs, the conversations, and the exact text of the two
answers. The upgrade tests assert every one of those survives, so "nothing was
lost" is measured rather than assumed.

The database is never modified by a test. Each one works on its own copy
(`prior_version_database` in `tests/conftest.py`).

## Regenerating, or adding a fixture for a newer version

Only necessary when a new migration lands and you want a fixture at the version
before it. The existing file stays valid: an upgrade from 8 is still an upgrade
worth proving.

```powershell
git worktree add ../codeatlas-prior <commit before the new migration>
uv run python scripts/make_upgrade_fixture.py `
    --prior-src ../codeatlas-prior/src `
    --output tests/fixtures/upgrade/schema_00NN.db
git worktree remove ../codeatlas-prior
```

The script places `--prior-src` at the front of `sys.path` and then **checks
which package actually loaded** before doing any work. A fixture accidentally
written by the current code would pass every test in the suite and prove
nothing, so that check is a refusal rather than a warning.

The repository the fixture indexed lived in a temporary directory that no longer
exists. That is deliberate and realistic — the upgrade tests ask only questions
the database can answer on its own.
