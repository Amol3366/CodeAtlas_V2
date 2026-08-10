# ADR-0040: Ephemeral scope is the server, and that is the decision

- Status: accepted
- Date: 2026-08-10
- Decision owners: user/product and implementing agent
- Supersedes: none (amends the scope statement of ADR-0013 by making it
  explicit; it does not change any ADR-0013 decision)

## Context

`CODEATLAS_EPHEMERAL` and `--ephemeral` (ADR-0013) start `serve` from empty
storage and discard it on exit. `_ephemeral_requested` is read at exactly one
call site, inside `serve` (`cli/main.py`). Every other command goes through
`_services`, which resolves `database or default_database_path()` and writes
the real database whatever the variable says.

This was raised on 2026-08-09 as an open scope question — *should the variable
cover CLI commands too?* — and has been carried since as undecided.

The complaint that produced it was real and has already been fixed. Nothing
stated which database was in play, so a user running with
`CODEATLAS_EPHEMERAL=1` was right about the web application and wrong about
the CLI, and discovered it only by finding data that should not exist. Both
surfaces now announce `Using database: <path>` on stderr.

What remained was only whether the *scope* should change.

## Decision

**It should not. `CODEATLAS_EPHEMERAL` governs `serve` and nothing else.**

The reason is structural rather than a preference. Ephemeral means *storage
discarded when the process exits*, and **a CLI command exits immediately.**
Extending the variable would mean:

- `codeatlas repo add <path>` creates a session database, registers the
  repository, and destroys it on exit;
- `codeatlas index <repository_id>` starts a *different* session database and
  fails, because that repository was never registered in *this* one;
- every command would be an island, and the documented CLI workflow in
  `README.md` — add, index, symbol, search, impact — would be structurally
  impossible.

The mode is coherent only for a process that lives long enough for the storage
to be worth having. That is `serve`.

This is recorded as an ADR rather than closed silently because the item has
been carried as an open question, and "we looked and the current behaviour is
correct" is a decision that deserves a record as much as a change does.

## Alternatives

**Extend it to every command.** Rejected for the reason above: it produces a
CLI where no two commands can see each other's work.

**Extend it with a shared session database keyed by something stable** — an
environment variable naming the session, say. Rejected: this is not ephemeral
mode, it is a second database path, which `--database` already provides. It
would also need a lifecycle owner to decide when the session ends, and there
is no process to hang that on — which is the original problem restated.

**Make the CLI refuse to run when the variable is set.** Rejected: it breaks a
user who exports the variable in their shell profile for `serve` and then runs
an unrelated `codeatlas doctor`. Refusing to work is worse than working
correctly on the real database and saying so, which is what happens now.

**Close it silently as "working as intended".** Rejected: the item was carried
as an open question across sessions, and leaving no record invites the next
agent to re-derive the same analysis.

## Consequences

No behaviour change. The scope is as it was; it is now stated at the decision
point and enforced by tests.

Two tests pin the boundary, both mutation-checked:

- `test_a_cli_command_ignores_the_ephemeral_variable` — with the variable set
  and readable (asserted, so the test cannot pass because the variable went
  missing), a CLI command opens the real database. Mutating `_services` to
  route through `_ephemeral_requested` **fails it**, with the captured stderr
  showing a session path, which is the evidence the mutation took effect.
- `test_serve_still_honours_the_ephemeral_variable` — the other side. Without
  it, this ADR could be "satisfied" by the variable ceasing to work anywhere,
  which is a different decision entirely.

The first test's docstring records that it asserts a *decision*: if a future
change makes the CLI ephemeral, the test must be deleted deliberately
alongside this record, not quietly adjusted.

Known and unchanged: a repository indexed through the CLI while a `serve
--ephemeral` session is running is invisible to that session, and vice versa.
That is what the two storages mean. `documentation/memory.md` records the
practical trap for an agent — re-indexing through the CLI produces work
invisible to a `serve`-based workflow, the same shape as the 2026-08-05 stale
package incident — and that note stands.

No contract, schema, or migration change.

## Security and Privacy

None, and one property worth stating: because ephemeral mode **never opens the
real database** (ADR-0013 decision 3), it cannot delete or modify persistent
data. That is what makes the mode safe, and it is exactly the property that
would have to be traded away to give the CLI a shared session. Not worth it.

## Migration and Rollback

No migration. Rollback is deleting the two tests and this record.

## Approval

The ruling was put to the user on 2026-08-10 with the alternatives and their
consequences stated, and the user selected won't-fix. Recorded by the
implementing agent. No Section 25 item is triggered.
