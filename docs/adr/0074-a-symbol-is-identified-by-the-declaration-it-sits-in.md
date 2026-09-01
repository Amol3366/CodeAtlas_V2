# ADR-0074: A symbol is identified by the declaration it sits in

- Status: accepted
- Date: 2026-09-01
- Decision owners: user/product (ruled that both mechanisms land in **one**
  reindex rather than two) and implementing agent
- **Corrects: ADR-0072**, which sized these two mechanisms at 980 of 981 groups.
  **Measured, they reach 198.**
- Related: ADR-0069 (the collision defect), ADR-0071 (the signature), ADR-0072
  (the census and the corrected characterisation)

## What was built

A second identity input beside `signature`: `LanguageAdapter.discriminator`,
returning **the declaration a symbol sits inside, or its own form where it has
one**. Java, Scala, Go and Rust supply one; Python and TypeScript are untouched.

It is **not stored**. A discriminator is an id-construction input like the
ordinal, not evidence like the signature, so `SCHEMA_VERSION` stays 14 and there
is no migration.

Two details carry the design:

- **The discriminator is appended to the id hash only when non-empty.** A group
  whose members return `None` produces byte-identical ids to the 1.8.0 bundle,
  so each language's ids move for its own reason and nothing else moves with
  them.
- **ADR-0069's "the first member of a group keeps its id" shortcut no longer
  applies where a discriminator exists.** That shortcut is itself
  ordinal-dependent: whoever is first in document order keeps the base id, so
  inserting a member above the first one displaces it — the exact instability
  this record exists to remove. Where a discriminator exists the member is
  always hashed, so its id depends on what it is rather than where it sits.

## The measurement, and the correction

`scripts/report_symbol_collisions.py`, over the five repositories pinned in
`scripts/check_real_repos.py`:

| Repository | Separated before | Separated after | Still ordinal |
| --- | ---: | ---: | ---: |
| gson (Java) | 52 | **76** | 23 |
| cobra (Go) | 0 | **1** | **0** |
| gin (Go) | 0 | **4** | **0** |
| ripgrep (Rust) | 0 | **4** | 17 |
| scalaz (Scala) | 169 | **334** | 743 |
| **Total** | **221** | **419** | **783** |

**198 groups gained position-independent identity. ADR-0072 predicted 980.**

**The prediction was wrong for a reason worth naming.** ADR-0072 classified the
981 remaining groups by *sampling* them and inferring a mechanism from what the
samples looked like. It never checked the thing that actually matters: whether
the enclosing declaration **differs between the colliding members**. Usually it
does not.

Measured, scalaz's remaining 743 break down as:

| Why it is still ordinal | Groups |
| --- | ---: |
| Both members inside the **same** declaration | ~718 |
| Partially separated, duplicates remaining inside one parent | 25 |

`TimeInstances.max` is declared twice inside one `trait`; `Adjunction.unit`
twice inside one `class`. **There is only one enclosing scope, so no
enclosing-based mechanism can separate them.** Rust's remaining 17 are likewise
methods sharing a single `impl`, not the two-trait pairs ADR-0071 described.

This is the **third** time in this lineage that a claim about counts was
inherited rather than measured — ADR-0071 disproved ADR-0069's follow-up,
ADR-0072 disproved ADR-0071's, and this record disproves ADR-0072's. The
instrument that catches it now exists and is committed; the discipline that was
missing is running it *before* writing the estimate, not after.

## One reindex, not two

ADR-0071 kept mechanisms apart so that bundling would not hide which one moved
which ids. **The user ruled to bundle these two**, and the reason ADR-0071's
objection no longer binds is that the census attributes per language and per
mechanism directly — the attribution no longer depends on separating the
releases. One reindex is paid instead of two.

`PARSER_BUNDLE_VERSION` 1.8.0 -> **1.9.0**. `SCHEMA_VERSION` 14,
`contract_version` 1.1, `CHUNKER_VERSION` 1.1.0 and `RESOLVER_VERSION` 1.5.0 are
all unchanged; resolution draws the same conclusions from a reference as before.

**Users must reindex.**

## What is left, and not claimed

**783 groups remain on the ordinal**, and the largest class — roughly 718 — is
**two declarations sharing a name, a kind, and one enclosing scope**. No
mechanism in this record can reach them, and none is proposed here. It may not
even be an identity defect: if `Align.F` renders the same qualified name for two
members that a reader would consider distinct, the qualified name is the thing
that is wrong. **That is a separate investigation and it is not started.**

The single scalaz `INTERFACE` group ADR-0072 left uncharacterised is still
uncharacterised.

## Consequences

- Go is now fully stable in both measured repositories: zero ordinal groups.
- The census measures `(signature, discriminator)` rather than the signature
  alone. Before this change it could not have observed the mechanism working —
  an instrument that agrees with any fix is not evidence, which is the same
  trap `ensure_unique_symbol_ids` sets for a census built on `parse` output.
- `TagsBackedParser.definitions_with_discriminators` is public for that census.
  It returns **pre-disambiguation** records deliberately.
