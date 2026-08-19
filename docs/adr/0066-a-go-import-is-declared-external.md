# ADR-0066: A Go import is declared `external`, permanently

- Status: **accepted** 2026-08-19
- Date: 2026-08-19
- Decision owners: user/product and implementing agent
- Supersedes: none. Closes the first of the two limits ADR-0065 left open.

## Context

ADR-0065 shipped Go on the shared query-backed engine and recorded one limit
rather than choosing a fix for it: **a Go import resolves `external`.**

A Go import path carries the module prefix declared in `go.mod` —
`myapp/internal/payments` — while the indexed module path is the
repository-relative directory, `internal.payments`. `_resolve_module` matches a
specifier against tails of *module paths*, not tails of the *specifier*, so the
longer specifier never matches.

**The prefix is not in any file the parser reads.** A parse is a pure function
of one file, which is the invariant that lets an unchanged file's references be
reused across analyses. `go.mod` is a second file, and external configuration.

The contrast that makes this a language property rather than an oversight:
**Rust's `crate` is a language keyword**, so stripping it from
`use crate::payments::Service` is safe and the suffix index matches. Go's prefix
is a name someone chose. The difference is not effort — it is where the
information lives.

## Decision

**Leave it. A Go import is recorded and classified `external`, and that is the
declared behaviour rather than a deferred fix.**

The `strict` xfail that predicted a future fix is **inverted, not deleted**, on
ADR-0045's precedent: it existed so the behaviour could not change silently, and
it still serves that purpose. It now asserts both halves — the import **is**
recorded, and it is **not** resolved.

## Alternatives

**Trim to a single segment.** Match the last path segment, so
`myapp/internal/payments` finds `payments`. Rejected on the asymmetry of its
cost: a third-party `github.com/foo/payments` would resolve onto a *local*
`payments` package, **inventing a relationship** that does not exist. §4.1
forbids exactly this. A miss is the safe direction; an invention is not.

**Suffix match with a minimum segment count** (e.g. two trailing segments).
Narrower, and it recovers most real imports. Rejected here because it is the
same class of error with a smaller blast radius rather than a different class:
a third-party path ending in the same two segments still resolves onto local
code, and nothing in the specifier says which is which.

**Read `go.mod` and strip the declared prefix.** The only *accurate* option. It
is rejected in this record rather than dismissed — see Consequences.

**Do nothing and leave it as an open xfail.** Rejected because a permanently
open xfail is a decision that nobody has to make. The register's purpose is to
give every item a terminal state.

## Consequences

**Negative, and stated plainly.** Go impact analysis is thinner than Python's:
a cross-package import produces no resolved edge, so "what depends on this"
misses dependencies that a Go developer would consider obvious. Callers reached
through an imported package are found only when the call itself resolves by
another tier — which measurement shows it often does (`Service.Charge` resolves
today), so the loss is narrower than "Go imports do not work", and wider than
nothing.

**Positive.** No relationship is ever invented. Every stored Go `IMPORTS` edge
is a true statement about the source file, carrying `external` — which is a
fact, not a failure. The parser keeps its one-file purity.

**This is a decision, not a verdict on the code.** If a matching policy is ever
wanted, this record is the thing to supersede, and the third alternative above
is where to start: reading `go.mod` is accurate, and its cost is an invariant
change plus its own ADR, not a heuristic that can be wrong.

## Security and Privacy

None. Nothing new is read, transmitted, or executed; `go.mod` is deliberately
*not* read, so the parser's no-second-file property is preserved.

## Migration and Rollback

| Item | Change |
| --- | --- |
| `PARSER_BUNDLE_VERSION` | unchanged |
| `RESOLVER_VERSION` | unchanged |
| `SCHEMA_VERSION` | unchanged — no migration |
| `contract_version` | unchanged |

**No stored data changes and no reindex is required.** The behaviour being
ruled is the behaviour that already ships.

**Rollback:** delete this record and reopen the register row. Nothing to revert
in code.

## Approval

**Ruled by the user on 2026-08-19**, choosing "permanent declared limit" over a
suffix-matching policy and over reading `go.mod`, with the asymmetric cost of a
wrong match stated as the deciding factor.
