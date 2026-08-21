# ADR-0049: A fixture re-includes a directory that an ignore default excludes

- Status: **accepted** 2026-08-16. **Recorded 2026-08-21**, five days after the
  fact — see "Why this record is late".
- Date of decision: 2026-08-16
- Decision owners: user (ruling), implementing agent (record)
- Supersedes: none. This is "Ruling 2" of the four taken on 2026-08-16.

## Why this record is late

**ADR-0047 cites this record by number and it did not exist.** Line 39 reads
"the neighbouring finding (the `target/` ignore collision, ADR-0049) *is* a
faulty instrument", contrasting it against ADR-0047's own *absent decision* —
the two needed different fixes and the sentence turns on that difference.

Ruling 2 shipped as a fixture-local `.codeatlasignore` carrying its reasoning in
a comment, and no ADR was written. ADR-0050 then **deliberately skipped 0049**
rather than take the free number, because hijacking it would have made
ADR-0047's sentence point at an unrelated record. So 0049 sat reserved and
empty, and the dangling citation went into the Deferred Register with the
trigger "someone writes the `target/` ignore-collision record as 0049".

This is that record. Nothing here is a new decision: it is the one made on
2026-08-16, written down where ADR-0047 already says it is.

## Context

The `git_changes` fixture has two sides, `base/` and `target/`, and those names
are load-bearing rather than cosmetic: `_resolve_side` treats the literal refs
`base` and `target` as selecting that subdirectory as the state root, which is
how change cases c020–c023 compare the two states.

`target/` is also a **build-output ignore default** — it is where Rust and Maven
put artifacts — so the scanner excludes it from every index.

Those two facts collide, and only for *query* cases. A change case names a side
and indexes that subdirectory as its root, so the ignore default sits above it
and is never consulted. A query case indexes the **fixture root**, so half the
fixture was invisible. q034 asks where `process` is in the target tree and could
only ever be answered from `base/`; **its recall was structurally 0 and always
had been.**

This is the shape ADR-0047 calls a *faulty instrument*: nothing about the
product was wrong, and the corpus was not measuring what it claimed to.

## Decision

**Re-include `target/` for this fixture only, with a fixture-local
`.codeatlasignore` holding `!target/`.**

`.codeatlasignore` is compiled with `overrides=True`, so it beats the builtin
default. **The default itself is untouched and still applies to every other
repository** — which is the property that makes this safe: no real user's build
output enters an index because a test fixture needed to be visible.

The file carries its full reasoning as a comment, because the next person to see
`!target/` in an ignore file will reasonably assume it is a mistake.

## Alternatives

**Rename the directory.** The obvious fix, and it breaks the ref grammar:
`_resolve_side` matches the literal names `base` and `target`, so renaming would
silently change what c020–c023 compare. Rejected — trading a query-case defect
for a change-case one.

**Mark the affected query cases unmeasured.** ADR-0024 gave the corpus a way to
say "the adapter declined to run this", and it would apply here syntactically.
Rejected because it would make that signal mean two different things: "this
capability is deliberately out of scope" and "this fixture is misconfigured".
A signal that means two things is one nobody can act on.

**Change the builtin ignore default.** Rejected outright: it would pull build
output and dependency trees into every real repository's index to fix one
fixture.

**Leave it.** Rejected — a case whose recall is structurally zero is not
measuring the engine, and it had been quietly lowering aggregate metrics for as
long as it existed.

## Consequences

**q034 now passes.** It could not have before, under any engine.

**q035 broke, and that was not anticipated.** Re-including `target/` put a
*second* symbol named `process` into the index, so q035's trace subject became
ambiguous and the answer correctly abstained. Four metrics regressed, all from
that single case. That is not a defect in this ruling — the engine did the right
thing with a genuinely ambiguous name — but it is the cost, and it was paid
immediately. **ADR-0050 settled q035** by declaring its subject and its
reference site.

**Change cases are unaffected, and this was verified rather than assumed:**
c020–c023 were captured before and after and are byte-identical.

**Corpus scope.** The corpus was not edited to move a number (ADR-0003). No
expectation, question, intent, evidence range, or forbidden claim was touched —
the change makes a file *visible to indexing* that the corpus always assumed was
visible.

## Security and Privacy

None. `.codeatlasignore` is read as data by the scanner, the override applies to
one fixture directory inside the repository, and the builtin defaults that
protect real repositories are unchanged.

## Migration and Rollback

| Item | Change |
| --- | --- |
| `PARSER_BUNDLE_VERSION` | unchanged |
| `RESOLVER_VERSION` | unchanged |
| `CHUNKER_VERSION` | unchanged |
| `SCHEMA_VERSION` | unchanged — no migration |
| `contract_version` | unchanged |

No stored data changes; a corpus fixture becomes indexable. **Rollback:** delete
the fixture's `.codeatlasignore`. q034 returns to a structural zero and q035
stops being ambiguous, which would also strand ADR-0050.

## Approval

**Ruled by the user on 2026-08-16** as Ruling 2 of four, recorded in the
`docs/plans/PLAN.md` handoff of that date. The scope approved was the
fixture-local re-inclusion described above, explicitly not a change to the
builtin ignore defaults.
