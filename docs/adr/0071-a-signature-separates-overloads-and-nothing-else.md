# ADR-0071 — A signature separates overloads, and nothing else

- Status: accepted
- Date: 2026-08-31
- Approval: the user, 2026-08-31, instructing that Task 6 of the post-ADR-0069
  program be done
- Extends: ADR-0069 (symbol identity), ADR-0065 (the query-backed engine)

## Context

ADR-0069 disambiguates a colliding `symbol_id` by **signature first, ordinal
second**. The query-backed engine reported `signature is None` for all four of
its languages, so there the ordinal carried it alone — and an ordinal is
positional, so inserting a same-named sibling above another shifts the later
one's id and over-reports a change.

ADR-0069's follow-up recorded the remedy as:

> Teach the query-backed engine to emit `signature`. **It is the one change that
> converts the ordinal fallback into stable identity for four languages.**

**That claim is wrong, and measuring it was the substance of this decision.**

Probed against the four grammars, a signature separates only what *overloading*
produces:

| Construct | Signatures observed | Separated? |
| --- | --- | --- |
| Java method overloads | `(String s)` vs `(int i)` | **yes** |
| Scala method overloads | `(s: String)` vs `(i: Int)` | **yes** |
| Scala companion `trait`/`object` | both absent | no |
| Go function-local `type` | both absent | no |
| Rust one method, two traits | **byte-identical** `(&self, f: &mut fmt::Formatter)` | no |

Go and Rust have **no overloading at all**, so a signature cannot separate any
collision they produce. Rust's is the sharpest case: `Display::fmt` and
`Debug::fmt` differ only by the trait, and a trait is not a parameter.

Measured over the five real repositories of `scripts/check_real_repos.py`:

| Repository | Collision groups | Separated by signature | Still ordinal |
| --- | ---: | ---: | ---: |
| gson (Java) | 99 | **52 (52.5%)** | 47 |
| scalaz (Scala) | 1077 | 169 (15.7%) | 908 |
| ripgrep (Rust) | 21 | **0** | 21 |
| gin (Go) | 4 | **0** | 4 |
| cobra (Go) | 1 | **0** | 1 |
| **Total** | **1202** | **221 (18.4%)** | **981** |

**18.4%, not four languages.** scalaz's share is low because its collisions are
overwhelmingly companion pairs, which declare no parameters.

## Decision

**Java and Scala emit a signature. Go and Rust deliberately emit `None`.**

1. **`LanguageAdapter` gains `signature(node, source) -> str | None`.** Java
   reads the `type` field of each `formal_parameter`; Scala reads each
   `parameter`'s `type` and collects **every** parameter list, because
   `def f(a: Int)(b: Int)` declares two and taking only the first would make
   the halves of a curried overload pair look identical.

2. **Types only, never parameter names.** `(String,int)`, not `(String s,int i)`.
   A rename must not change identity; including names would make a renamed
   parameter look like a deleted symbol and a new one — trading one instability
   for another.

3. **Go and Rust return `None`, and the reason is in the code.** Neither
   language overloads, so a signature is not merely unhelpful there, it is
   inapplicable. Returning an empty string would be worse than `None`: it would
   claim a discriminator exists.

4. **This is landed as a strict improvement, not a fix.** 221 real collision
   groups gain identity that survives insertion, including gson's public API.
   **981 do not**, and remain positional.

## Consequences

- **`PARSER_BUNDLE_VERSION` 1.7.0 → 1.8.0. Every snapshot is stale; users must
  reindex.** `signature` is a stored column and query-backed rows carried `NULL`.
  `RESOLVER_VERSION` stays 1.5.0 on the ADR-0067 precedent — resolution draws
  the same conclusions from a reference as before.
- **The reindex is marginal in practice.** ADR-0070 bumped to 1.7.0 hours
  earlier, so anyone who has not yet reindexed pays once for both. Anyone who
  reindexed at 1.7.0 pays a second time, and that is the honest cost of
  landing two identity changes on one day rather than one.
- **No schema, contract, or migration change.** `SCHEMA_VERSION` stays 14,
  `contract_version` stays `1.1`. `signature` has been a `SymbolRecord` field
  since Phase 1; this populates it where it was null.
- Ids move only for the **second and later** members of a separated collision
  group. A non-colliding symbol's `symbol_id` never contained a signature and
  does not now.
- `signature` is useful beyond identity: it is the field an overload list is
  rendered from, and query-backed languages were the only ones leaving it empty.

## What this does not fix, and what would

Stated because the follow-up note that produced this ADR overstated its reach,
and the same overstatement should not be inherited again.

- **Scala companion pairs** (908 of the 981 remaining) need identity to consider
  the *declaration form* — a `trait` and its `object` are different things
  sharing a name — not a signature.
- **Go function-local types** need the **enclosing scope**: `type key struct{}`
  inside `func A` and inside `func B` are distinguished by their function, which
  is a lexical ancestor the engine already walks for other purposes.
- **Rust two-trait impls** need the **trait**, which is available on the
  enclosing `impl` node and is not a parameter.

Each is a separate change with its own reindex, and none is started here.

## Alternatives rejected

- **Include parameter names.** Separates strictly more, and breaks identity on a
  rename. Rejected in §2.
- **Emit a synthetic discriminator for Go and Rust** (enclosing scope or trait)
  inside this change. Rejected: they are different mechanisms with different
  risks, and bundling them would hide which one moved which ids — the reason
  ADR-0069 deliberately did not bundle this work with its own fix.
- **Do nothing, because 18.4% is small.** Rejected: the reindex is already
  being paid, the change is additive, and gson's overloads are the most
  user-visible collision measured.
