# ADR-0067: A language profile may author a second query, and Scala does

- Status: **accepted** 2026-08-19
- Date: 2026-08-19
- Decision owners: user/product and implementing agent
- Supersedes: none. Closes the second of the two limits ADR-0065 left open.

## Context

ADR-0065 shipped Scala on the shared query-backed engine with a recorded limit:
**Scala captures only calls to a bare identifier.**

Its shipped `tags.scm` carries one call pattern:

```scheme
(call_expression (identifier) @name) @reference.call
```

That matches `log(x)`. It does not match `payments.charge(id)`, whose
`function` is a `field_expression` — and that is **most real Scala code**. Java,
Go and Rust all ship a member-call pattern; Scala is the only one of the four
that does not.

ADR-0065 declined to fix it at the time for a stated reason: the profile
contract carried exactly one authored query slot, `imports_query`, and widening
a contract mid-slice is the scope creep this project forbids. The gap was
recorded as a `strict` xfail carrying its own diagnosis.

Measured on the real grammar before deciding: a member call's `function` is a
`field_expression` with fields `value` and `field`, and the method name is the
**`field`**. A chained `a.b.c(x)` matches once, on `c`, because the inner `a.b`
is the `value` of the outer expression rather than the `function` of a call.

## Decision

**`LanguageProfile` gains an optional `references_query`, and Scala supplies
one.**

It is authored in this repository as `queries/scala.references.scm`, beside the
`*.imports.scm` files, and uses the **same `reference.*` / `@name` convention**
as a grammar's `tags.scm`. `extract_query_references` runs the shipped query and
then the supplementary one through one loop, so neither query knows the other
exists.

**Optional by design.** Java, Go and Rust supply nothing and run exactly as
before — verified, not assumed: their profiles report `references_query=None`
and their suites are unchanged.

## Alternatives

**Leave it as a permanent declared limit**, as ADR-0066 does for Go's imports.
Rejected because the two cases are not alike. Go's missing information *is not
in any file the parser reads*; Scala's is right there in the syntax tree, and
the only thing missing was a query. Declaring a limit that a nine-line query
closes would be recording an absence of work as a property of the language.

**Patch the grammar's shipped `tags.scm`.** Rejected: it is vendored third-party
data, a rewrite would be silently discarded on the next dependency bump, and it
would put this repository's opinions inside a file it does not own.

**Special-case Scala in the engine.** Rejected for the reason ADR-0065 gives for
the whole design: the engine stays language-agnostic, and a language contributes
data plus a thin adapter. A branch on `language == "scala"` inside the extractor
would be the first crack in that.

**Widen `tags_query` to accept a list.** Equivalent in effect and worse in
naming: `tags_query` means "the query the grammar ships", and making it
sometimes mean "ours too" would blur the one distinction the module exists to
keep.

## Consequences

**Positive.** Scala emits `CALLS` edges for member calls, so impact analysis,
`callers`, and changed-symbol blast radius all work on ordinary Scala rather
than only on bare-identifier calls. The seam generalises: any future language
whose shipped query is thin can supply one without touching the engine.

**Negative, and stated.** More references means more candidates for resolution
to be wrong about; a member call resolves by name and the receiver's *type* is
still unknown, so `a.charge(x)` and `b.charge(x)` are indistinguishable to the
resolver. Those become `MAY_CALL` or stay unresolved rather than becoming false
`CALLS` edges — the derivation ladder is what absorbs this — but the volume of
edges on a Scala repository rises.

**Two guards were added with it**, because the failure modes are specific: a
supplementary query that *shadows* the shipped one (both a bare call and a
member call must survive — asserted together, since separately each passes while
the other is broken), and one that *duplicates* an edge (a call captured by both
queries must be stored once, because a doubled `CALLS` edge inflates impact
analysis, which is the product's core claim).

## Security and Privacy

None. A query is data evaluated by Tree-sitter against an in-memory tree;
nothing is read from disk beyond the query file, nothing is executed, and no
new dependency is added.

## Migration and Rollback

| Item | Change |
| --- | --- |
| `PARSER_BUNDLE_VERSION` | **1.5.0 → 1.6.0** — a Scala file now yields references it did not before, so every snapshot derived by 1.5.0 is stale |
| `RESOLVER_VERSION` | **unchanged, deliberately.** Resolution draws the same conclusions from a reference as it always did; only the *set* of references changed |
| `SCHEMA_VERSION` | 14, unchanged — no migration |
| `contract_version` | `1.1`, unchanged — no new field crosses an adapter boundary |

**Every user reindexes once.** This is the second forced reindex in a day, after
ADR-0065's `1.4.0 → 1.5.0`; they were not combined because the ruling that
produced this one came after that change had shipped and merged.

**Rollback:** remove `references_query` from the Scala profile and restore
`PARSER_BUNDLE_VERSION` to `1.5.0`. Snapshots built under 1.6.0 then read as
version-mismatched and are reindexed. No data is lost and no migration reverses.

## Approval

**Ruled by the user on 2026-08-19**, choosing to widen the profile contract over
declaring a permanent limit, on the grounds that the mechanism already supports
authored queries and this is a missing query rather than a missing capability.
