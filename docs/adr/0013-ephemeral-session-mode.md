# ADR-0013: Ephemeral sessions are an opt-in mode, never the default

Status: accepted
Date: 2026-08-04
Phase: none (post-gate; Phases 0–7 are complete)
Amends: `AGENTS.md` §8.2's persistence requirement, by scoping it to default mode
Design: `docs/superpowers/specs/2026-08-04-ephemeral-session-and-stale-shell-design.md`

## Context

The user asked for every run of the application to begin with fresh indexing,
fresh embeddings, and fresh storage, while conversation history continues to
work normally *within* a run.

That request collides with two standing requirements:

- **`AGENTS.md` §8.2** lists "history survives browser restart and backend
  restart" as required behavior, and it is a Phase 5 completion-gate condition
  approved by the user on 2026-07-28.
- **`AGENTS.md` §9** requires indexing to be incremental and idempotent, reusing
  chunk and embedding records whose content hashes are unchanged.

Wiping storage on every start inverts both. Making that the default would
silently regress a gate condition, which is the failure mode §20's "do not use
this file for live task status" discipline exists to prevent: a contract is not
amended by an implementation quietly disagreeing with it.

The request is nevertheless legitimate. Working *on* CodeAtlas — as opposed to
working *with* it — a session that inherits the previous run's repositories,
snapshots, and conversations makes it hard to tell new behavior from residue.

## Decision

**Add an opt-in ephemeral session mode. Do not change the default.**

1. `codeatlas serve --ephemeral`, or `CODEATLAS_EPHEMERAL=1`, serves from a
   session-scoped database under
   `%LOCALAPPDATA%/CodeAtlas/sessions/<pid>-<utc timestamp>/`.
2. **One path is injected; everything else follows.** `create_app` and
   `build_services` already derive the vector directory as
   `<database>.parent / "vectors"`, so a fresh database directory yields a fresh
   LanceDB tree with no new plumbing. Repositories, snapshots, files, symbols,
   relations, chunks, FTS projections, conversations, the embedding cache, and
   the vectors are consequently all empty.
3. **The real database is never opened in this mode.** This is what makes the
   feature safe: a defect in it cannot destroy user data, because it has no
   handle on any.
4. **An explicit `--database` outranks `--ephemeral`.** Naming a database is a
   deliberate instruction; substituting a throwaway one would discard the
   user's choice without saying so.
5. **Configured repositories are registered before the bind and indexed after
   it.** `CODEATLAS_EPHEMERAL_REPOSITORIES` holds semicolon-separated absolute
   paths, read from the project `.env` — never the working directory, so a
   repository being indexed still cannot configure the tool indexing it.
   Registration is synchronous because a bad path is worth reporting before the
   browser opens; indexing runs on one sequential background thread so a first
   run against a large repository does not look hung.
6. **A sweeper reclaims what a crash leaves.** At each ephemeral start, session
   directories whose owning process is dead, or which are older than 24 hours,
   are removed.

Within a session, history, streaming, cancel, retry, reconnect, evidence
validation, and snapshot-bound citations behave exactly as in default mode.
Nothing in the retrieval, evidence, or freshness path is touched.

## Consequences

- **Every ephemeral run pays a full index.** That is inherent to the request,
  not a defect. Background indexing keeps the application usable meanwhile, and
  the existing status surfaces report real progress rather than a fake bar.
- **`AGENTS.md` §8.2 needs amending** to scope its persistence requirement to
  default mode. Under ephemeral mode a backend restart *is* a new session by
  definition, so the requirement cannot be met and must not silently appear to
  be. The amendment is recorded rather than assumed.
- **The sweeper inherits crash recovery's pid-reuse limitation.** A reassigned
  pid can make a dead session look alive; the 24-hour age rule collects it
  anyway. This is the same limitation `docs/operations/crash-recovery.md`
  documents rather than pretends to solve, and it is bounded here rather than
  open-ended.
- **A crashed run leaves a directory until the next ephemeral start.** A user
  who crashes and never uses the mode again keeps one directory until they do.
  Deleting it is safe at any time; it holds no repository truth.
- Default-mode behavior, tests, and gates are unchanged. The regression boundary
  for this change is that the existing persistence and restart tests pass
  **unmodified**.

## Alternatives rejected

**Wipe tables in the real database at startup.** Irreversible; races the
watcher, which may be mid-index when the wipe runs; and makes `codeatlas backup`
and `codeatlas restore` meaningless, since the thing they protect is discarded
on the next start. Worst of all, a defect in it destroys real user data — the
opposite of the property decision 3 above buys.

**A full named-profile system.** More machinery than the request needs. An
ephemeral session is one profile whose lifetime happens to be the process, and
generalizing before a second profile is actually wanted is the premature
abstraction `AGENTS.md` §21 warns against.

**Clearing only conversations, keeping the index.** Faster to start, and it was
offered. It does not match the request — "indexing, embedding or storage should
be fresh" — so choosing it would have been answering an easier question than the
one asked.
