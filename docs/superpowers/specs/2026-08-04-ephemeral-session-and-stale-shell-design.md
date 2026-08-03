# Ephemeral session mode, and the stale application shell

Date: 2026-08-04
Status: approved by the user 2026-08-04, pending spec review
Policy authority: `AGENTS.md`; live status: `docs/plans/PLAN.md`

Two user-reported problems. They are unrelated in cause and are specified
separately, because one is understood and one is not.

- **A — Fresh storage per run.** Every start should begin with empty indexing,
  embeddings, and storage; history should behave normally *within* a session.
  Understood, designed below, ready to plan.
- **B — Stale Settings view.** Starting the app shows the old Settings UI until
  a manual reload. **Root cause not yet established.** This spec deliberately
  specifies a diagnosis, not a fix.

---

## Part A — Ephemeral session mode

### Problem

Every run should start with fresh indexing, embeddings, and storage, while
conversation history continues to work normally for the duration of that run.

### Constraint this collides with

`AGENTS.md` §8.2 and the Phase 5 completion gate require chat history to
survive a **backend restart**. §9 requires indexing to be incremental and
idempotent, reusing unchanged content hashes. Wiping on every start inverts
both.

Therefore the default behavior does not change. This is a separate, explicitly
selected operating mode. Selecting it is a user decision; inheriting it
silently is not.

### Design

**Activation.** `codeatlas serve --ephemeral`, with or without `--web`; or
`CODEATLAS_EPHEMERAL=1`. Absent both, nothing changes anywhere.

**Session storage.** On start, create:

```text
%LOCALAPPDATA%/CodeAtlas/sessions/<pid>-<utc-timestamp>/
    codeatlas.db
    vectors/
```

The database path is the only thing that has to be injected. `api/app.py:127`
already derives the vector directory as `resolved_path.parent / "vectors"`, so
a fresh database directory yields a fresh LanceDB tree with no new plumbing.
Repositories, snapshots, files, symbols, relations, chunks, FTS projections,
conversations, the embedding cache, and the vectors are all consequently empty.

Migrations run against the new file exactly as they do on any first open. There
is no special-case schema path, and no startup schema mutation — `AGENTS.md`
§15 still holds.

**Bootstrap.** `CODEATLAS_EPHEMERAL_REPOSITORIES`, a semicolon-separated list
of absolute paths, read from the **project** `.env` — never the working
directory, and never the indexed repository. A repository being indexed must
not be able to configure the tool indexing it.

At startup, in order:

1. Each configured path is **registered synchronously**. Registration is cheap
   and its failures (missing path, not a repository, path escaping its root)
   are worth reporting before the server binds.
2. Each registered repository is then **indexed as a normal background
   `IndexJob`**. Indexing is *not* awaited. The server binds immediately and
   the existing onboarding UI reports real stage, progress, and diagnostics, as
   §14.2 already requires. No progress is faked and no canned result is shown.

An unusable configured path is reported and skipped; it does not prevent the
server from starting or block the other repositories.

**Cleanup.** A clean shutdown deletes the session directory. A crash does not,
so at each start a sweeper removes session directories whose owning pid is dead
or whose age exceeds 24 hours. Without the sweeper every crashed run leaks a
vector tree, which is measured in hundreds of megabytes once embeddings are on.

The sweeper reuses the liveness check that crash recovery already uses, and
therefore inherits its **known pid-reuse limitation**: a reassigned pid can make
a dead session look alive, leaving one directory behind until the 24-hour age
rule collects it. This is recorded rather than silently accepted, consistent with how
the same limitation is handled in `docs/operations/crash-recovery.md`.

**What is unchanged inside a session.** History, streaming, cancel, retry,
reconnect, evidence validation, and snapshot-bound citations behave exactly as
they do today. Nothing in the retrieval, evidence, or freshness path is touched.

### Rejected alternatives

- **Wipe tables in the real database at startup.** Irreversible, races the
  watcher, and makes `codeatlas backup` / `codeatlas restore` meaningless. A bug
  in it destroys real user data; a bug in the design above cannot, because the
  real database is never opened.
- **A full named-profile system.** More machinery than the request needs.
  Ephemeral mode is one profile whose lifetime happens to be the process.

### Contract work

- **ADR-0013** recording the new operating mode and its rationale.
- An **`AGENTS.md` §8.2 amendment** scoping "history survives backend restart"
  to default mode, since under ephemeral mode a restart *is* a new session by
  definition. This edits the contract and is the user's decision to approve.

### Acceptance criteria

- A session start creates a fresh database and a fresh vectors directory.
- Two consecutive ephemeral runs share no repository, snapshot, conversation,
  cached embedding, or vector.
- Within one session, a conversation's history, its citations, and its snapshot
  label behave identically to default mode.
- A clean exit removes the session directory.
- A session directory left by a killed process is swept on a later start.
- Configured repositories are registered before bind and indexed in the
  background, with real progress visible.
- An unusable configured path is reported and skipped without blocking startup.
- **Default mode is unaffected: the existing persistence and restart tests pass
  unmodified.** This is the regression boundary for the whole change.

---

## Part B — Stale Settings view

### Symptom

Starting the app with `uv run codeatlas serve --web --open` shows the previous
Settings UI. A manual browser reload shows the current one. It recurs on every
run.

### Established by inspection

- `apps/web/dist/assets/index-Bb6-9dKZ.js` **contains the current Settings UI**
  (verified against four distinctive strings from `SemanticSettings.tsx`), and
  `dist` is newer than the Settings sources. The build on disk is not stale.
- The shell is served with `Cache-Control: no-store, max-age=0,
  must-revalidate` from `_application_shell_response`.
- `SettingsRoute` is a child of `Shell` in `App.tsx`, so `useReloadOnNewBuild`
  **does** run on the Settings route, on mount as well as on route change.
- A prior probe recorded in `docs/plans/PLAN.md` (2026-08-04) confirmed the
  running server returns non-cacheable shell responses and serves the new
  bundle.

The server is serving the correct UI. The staleness is browser-side.

### Why no fix is specified here

Three mitigations for this exact symptom already exist and all three failed:

1. `no-store` shell headers — `src/codeatlas/api/web.py`
2. `useReloadOnNewBuild` — `apps/web/src/app/buildFreshness.ts`
3. `reloadDocument` on the Settings `NavLink` — `apps/web/src/app/Shell.tsx:99`

Each was a plausible fix for an unconfirmed cause. Adding a fourth without
establishing the cause would most likely repeat the pattern, and would leave
four overlapping workarounds whose interactions nobody can reason about.

### Leading hypothesis

**Browser session restore.** `--open` hands the URL to the default browser. A
browser reopened with a previous CodeAtlas tab restores that tab from a
serialized snapshot rather than refetching, so `no-store` never applies and the
old bundle executes. Session restore also restores `sessionStorage`, which is
where `useReloadOnNewBuild` keeps its loop guard
(`codeatlas.reloadedBuildSignature`) — so a restored stale guard could suppress
the very reload the hook exists to perform.

This is a hypothesis. It is consistent with every observation, and it is not
confirmed.

### Diagnosis before fix

The first step is one observation the user can make in under a minute, which
discriminates cleanly:

> Start the server as usual, then ignore the tab that opened. Open a **new tab
> or a private window** and enter `http://127.0.0.1:8000/settings` by hand.

- **Current UI appears** — the served response is correct and the restored tab
  is the cause. The fix is then scoped to the client's build-identity check and
  its `sessionStorage` guard, and should *replace* rather than accumulate on the
  existing workarounds.
- **Stale UI appears** — the hypothesis is dead. The next step is instrumenting
  the actual response the browser receives (status, headers, asset hashes) and
  the hook's own decision path, before anything is changed.

Only after this observation does Part B get an implementation plan. Any fix must
also state which of the three existing workarounds it makes redundant, so the
count goes down rather than up.

### Acceptance criteria (to be finalized after diagnosis)

- Starting the app shows the current UI without a manual reload, reproducibly
  across restarts.
- The net number of staleness workarounds does not increase.
- The mechanism is covered by a test that fails against the current code.
