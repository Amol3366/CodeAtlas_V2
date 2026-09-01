# The 783 collision groups left on the ordinal, classified

Measured 2026-09-02 by `scripts/report_symbol_collisions.py --residual-detail`
(RW-05) over the five pinned repositories in `scripts/check_real_repos.py`. Raw
output in `collision-residual.txt`.

**No mechanism is proposed here.** The register's open question is whether these
are an identity defect at all; this answers *what they are* and stops.

## It reconciles with ADR-0074 exactly

| Repository | Groups | Separated | On the ordinal |
| --- | ---: | ---: | ---: |
| gson (java) | 99 | 76 | 23 |
| cobra (go) | 1 | 1 | 0 |
| gin (go) | 4 | 4 | 0 |
| ripgrep (rust) | 21 | 4 | 17 |
| scalaz (scala) | 1077 | 334 | 743 |
| **Total** | **1202** | **419** | **783** |

ADR-0074 recorded 1202 / 419 / 783. **To the digit**, on a tool that did not
exist when those numbers were taken.

## One correction to the register

The register says *"~718 of scalaz's remaining 743 are two declarations sharing
a name, a kind and one enclosing scope."* Measured: **700 of 743** share a
discriminator, and **730 of 783** corpus-wide. The shape of the claim survives;
the figure was approximate and is now exact.

## What they actually are

The largest residual groups are not pairs. They are **one qualified name
standing for many distinct declarations**:

| Repository | Qualified name | Kind | Members |
| --- | --- | --- | ---: |
| gson | `TypeAdapters.read` | METHOD | **28** |
| gson | `TypeAdapters.write` | METHOD | **28** |
| gson | `ReflectionAccessFilterTest.check` | METHOD | 11 |
| scalaz | `TupleInstances3._1` | FUNCTION | **31** |
| scalaz | `TupleInstances3._2` | FUNCTION | 27 |
| scalaz | `MapTest.f` | FIELD | 26 |
| scalaz | `Liskov.l` | TYPE_ALIAS | 16 |
| ripgrep | `imp` | FUNCTION | 8 |
| ripgrep | `DirEntryRaw.from_path` | METHOD | 3 |

Three recognisable patterns:

1. **Anonymous implementations flattened onto their holder.** gson's
   `TypeAdapters` declares 28 anonymous `TypeAdapter` subclasses, each with its
   own `read` and `write`. All 28 render as `TypeAdapters.read`. The enclosing
   declaration is genuinely identical, so a discriminator cannot separate them —
   the thing that distinguishes them is the anonymous member itself, and the
   qualified name drops it.
2. **Generated or repeated instance families.** scalaz's `TupleInstances3._1`
   covers 31 accessor definitions across a generated instance hierarchy.
3. **Platform-gated duplicates.** ripgrep's `imp` appears 8 times: `cfg`-gated
   modules that are alternatives, never simultaneously live.

## What this supports, and what it does not

**It supports the register's own hypothesis.** The row says: *"it may not be an
identity defect at all — if `Align.F` renders one qualified name for two members
a reader would call distinct, the qualified name is what is wrong."* That is
precisely what `TypeAdapters.read` x28 shows. A reader would call those 28
distinct; the naming scheme would not.

**It does not support building anything yet**, and three things say so:

- Pattern 3 (`imp` x8) is not a collision in any live configuration. Counting
  `cfg`-gated alternatives as colliding identities overstates the problem, and
  no proposed mechanism should be measured against a number that includes them.
- Changing qualified-name construction changes what a caller types to find a
  symbol. ADR-0069 refused exactly that for `Gson.fromJson`: TS/JS appends
  `#L103` to disambiguate, which is right for an anonymous union member and
  wrong for a name a caller looks up.
- 730 of 783 share a discriminator, so **no refinement of the existing
  `(signature, discriminator)` pair reaches them.** Any mechanism here is a new
  input to identity, which is a bundle bump and a forced reindex for every user.

The honest state: the residual is now described, its largest class is explained,
and the case for acting on it is weaker than the raw 783 made it look.
