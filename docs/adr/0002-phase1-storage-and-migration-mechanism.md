# ADR-0002: Phase 1 Storage, Migration Mechanism, and Indexing Execution Model

- Status: accepted
- Date: 2026-07-25
- Decision owners: CodeAtlas product contract
- Supersedes: none
- Refines: ADR-0001

## Context

Phase 1 introduces the first persistent storage in CodeAtlas: repositories,
snapshots, files, symbols, and indexing jobs. `CLAUDE.md` Section 6.1 requires
SQLite with WAL and "Alembic or an equivalent explicit migration mechanism", and
Section 15 forbids ad hoc schema mutation at application startup. The Phase 1
plan needs a decision that is fixed before P1-04 so that storage, application
services, and adapters do not diverge.

The Phase 1 profile is one local single-user workstation, one database file, one
writer, no ORM, and no data backfill. Snapshot activation must be atomic, and
interrupted indexing must leave the previous active snapshot usable.

## Decision

1. **SQLite with a numbered forward-only SQL migration runner**, not Alembic.
   Migrations are plain `.sql` files under
   `src/codeatlas/storage/sqlite/migrations/`, named `NNNN_<slug>.sql`, applied
   in ascending numeric order by `codeatlas.storage.sqlite.migrations`. Applied
   versions are recorded in a `schema_migrations` table; re-running is a no-op.
   `SCHEMA_VERSION` is the highest version the code requires. The first file is
   `0001_phase1_repository_truth.sql`.
2. **Database location** `%LOCALAPPDATA%\CodeAtlas\data\codeatlas.db`,
   overridable by the `CODEATLAS_DB_PATH` environment variable and by the CLI
   `--db` flag. Tests always pass an explicit temporary path.
3. **Connection pragmas** on every connection: `journal_mode=WAL`,
   `foreign_keys=ON`, `synchronous=NORMAL`, `busy_timeout=5000`.
4. **Phase 1 indexing is synchronous and in-process.** No job queue, worker
   pool, or background scheduler is introduced. `index_jobs` records stage,
   status, attempts, and diagnostics so that an interrupted run is observable
   and so a later phase can move execution to a background worker without a
   schema change.

## Alternatives

- **Alembic.** Adds a dependency, a migration environment, and autogenerate
  machinery whose value depends on SQLAlchemy models. Phase 1 has no ORM and
  hand-writes SQL, so autogenerate would be unused while the runtime and review
  surface would grow. Rejected for now, not forever: if migrations gain
  branching, data backfill, or downgrade requirements, a new ADR may adopt it.
- **`CREATE TABLE IF NOT EXISTS` at startup.** Explicitly forbidden by
  `CLAUDE.md` Section 15 because it cannot represent or verify schema history.
- **Storing the database inside the indexed repository.** Would write into
  untrusted user source trees and pollute their Git status. Rejected.
- **A background job queue in Phase 1.** Premature; the Phase 1 gate is a
  correct vertical slice, and in-process execution keeps failure and recovery
  paths directly testable.

## Consequences

- Migration tests can assert idempotency and recorded version directly against
  real SQLite, satisfying `CLAUDE.md` Section 19.1.
- The migration directory must ship inside the wheel; the build configuration
  force-includes it and the runner resolves it through `importlib.resources`.
- Downgrades are not supported. A destructive schema change requires a new ADR
  plus a documented backup/checkpoint step.
- A long index run blocks its caller in Phase 1. The REST `index` endpoint is
  therefore synchronous; moving it to a job-polling contract in a later phase is
  an additive API change and must be planned as one.

## Security and Privacy

The database lives outside the indexed repository, under the user's local
profile. It stores paths, hashes, symbol names, and line ranges, and it does not
store file contents or excerpts. All SQL is parameterized. Indexing reads
repository bytes as data and never executes repository code.

## Migration and Rollback

`0001_phase1_repository_truth.sql` creates the initial schema; there is no
earlier state to migrate from and rollback is deletion of the database file.
Later phases add new numbered files and never edit an applied one. Before any
destructive migration, the operator checkpoints or copies the database file.

## Approval

Accepted by the user together with the Phase 1 execution plan
(`docs/plans/phases/phase-01-repository-truth-vertical-slice.md`) on
2026-07-25.
