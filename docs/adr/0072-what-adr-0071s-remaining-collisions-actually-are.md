# ADR-0072: What ADR-0071's 981 remaining collisions actually are

- Status: accepted
- Date: 2026-09-01
- Decision owners: user/product (approved the Deferred Register program) and
  implementing agent
- **Corrects: ADR-0071**, in its account of *which* Scala pair collides and in
  its claim that gson's 47 Java groups have no named remedy. **Its measurements
  are reproduced here exactly and stand.**
- Related: ADR-0069 (the collision defect and its fix), ADR-0070, ADR-0071 (the
  signature), ADR-0064 (the precedent: a correct number read through a wrong
  attribution)

## Context

ADR-0071 measured that a signature separates 221 of 1202 collision groups and
left 981 on the ordinal, then named three mechanisms for the remainder: the
declaration form for Scala companions, the enclosing scope for Go, the trait for
Rust. It stated those account for 908, 5 and 21 — 934 — and that gson's
remaining 47 have no named remedy.

The numbers came from a probe that was never committed, so nothing could
reproduce them and nothing could contradict them. `scripts/report_symbol_collisions.py`
is that probe, committed.

## The measurements reproduce exactly

| Repository | Groups | Separated | Ordinal |
| --- | ---: | ---: | ---: |
| gson (Java) | 99 | 52 | 47 |
| cobra (Go) | 1 | 0 | 1 |
| gin (Go) | 4 | 0 | 4 |
| ripgrep (Rust) | 21 | 0 | 21 |
| scalaz (Scala) | 1077 | 169 | 908 |
| **Total** | **1202** | **221** | **981** |

**ADR-0071 measured correctly.** What follows corrects only what it concluded
those numbers were made of — the same shape of error as ADR-0064, where three
records read a correct 635 s through a mis-named timer.

## A Scala `trait`/`object` companion pair never collided

ADR-0071 says a companion pair collides and needs the declaration form to
separate it, because "a `trait` and its `object` are different things sharing a
name". They do share a name. They do not share a `symbol_id`.

`languages/scala.py:_KIND_BY_CAPTURE` maps `definition.interface` to
`INTERFACE` and `definition.object` to `CLASS`. Parsed:

```text
trait Thing   -> qualified_name 'Thing'  kind=INTERFACE
object Thing  -> qualified_name 'Thing'  kind=CLASS
```

`symbol_id` is `hash(repository_id, relative_path, qualified_name, kind)`, and
the kinds differ, so the two ids differ before any disambiguation runs. The pair
was never in a collision group at all.

**What collides is their members.** A trait and its object render the same
qualified-name prefix, so every member declared in both collapses:

```text
trait Align  { type F[_] ; def max: Int = 1 }
object Align { type F[_] ; def max: Int = 2 }

  'Align'      INTERFACE     <- parents do not collide
  'Align.F'    TYPE_ALIAS
  'Align.max'  FUNCTION
  'Align'      CLASS
  'Align.F'    TYPE_ALIAS    <- members do
  'Align.max'  FUNCTION
```

## What the 908 are

| Kind | Groups | What separates them |
| --- | ---: | --- |
| `FUNCTION` | 432 | the **enclosing** declaration's form |
| `FIELD` | 272 | the **enclosing** declaration's form |
| `CLASS` | 135 | the symbol's **own** declaration form |
| `TYPE_ALIAS` | 68 | the **enclosing** declaration's form |
| `INTERFACE` | 1 | **not characterised** |

Only the **135** are the parents ADR-0071 described — `abstract class X` beside
`object X`, both `CLASS`. The **772 members** are untouched by the mechanism it
proposed: the declaration form of a `def` is `def` under either parent, and
separates nothing. They need the form of the declaration they sit *inside*.

## gson's 47 have a remedy, and it is one already planned

ADR-0071 names none. Measured, they are:

| Kind | Groups | Construct |
| --- | ---: | --- |
| `METHOD` | 43 | one method overridden in several **enum-constant bodies** or anonymous classes — `FieldNamingPolicy.translateName` ×7, every one `(Field)` |
| `CLASS` | 4 | a class declared **inside a method** — `ObjectTest.Local` ×3 |

Reproduced minimally: an `enum` with two constant bodies each overriding
`translate(Field)` yields `E.translate` three times with an identical signature.

**A signature cannot separate these** — they are overrides, so the signature is
required to match. The enclosing scope separates all 47, which is the mechanism
ADR-0071 named for Go.

## Consequence: two mechanisms, not three

| Mechanism | Covers | Groups |
| --- | --- | ---: |
| **Enclosing declaration** (form for Scala members, function for Go, enum constant / anonymous class / method for Java, `impl` trait for Rust) | scalaz 772, gson 47, ripgrep 21, gin+cobra 5 | **845** |
| **Own declaration form** | scalaz `CLASS` parents | **135** |
| Not characterised | scalaz `INTERFACE` | 1 |

**980 of 981**, against the 934 ADR-0071's three mechanisms would have reached,
and gson's 47 stop being an unremedied gap.

Rust's trait is not a special case under this reading: an `impl` block *is* the
enclosing declaration, and the trait is how that declaration is named.

## What is decided here, and what is not

**Decided:** the characterisation above, and that
`scripts/report_symbol_collisions.py` is the instrument any later claim about
collision counts must be made with.

**Not decided:** whether the two mechanisms ship as one change or two. ADR-0071's
reason for keeping mechanisms apart — bundling hides which one moved which ids —
applies with equal force to these two, and the census now makes per-language
attribution measurable either way. That choice belongs to the task that
implements them, with a user ruling if it changes the number of reindexes.

**Not done:** the lone `INTERFACE` group is uncharacterised. It is one group of
981 and is recorded rather than guessed at.

## Consequences

- No code changed. `PARSER_BUNDLE_VERSION` stays 1.8.0 and **no reindex is
  caused by this record.**
- ADR-0071's follow-up section should be read through this one. Its three
  mechanisms are not wrong so much as mis-sized: the Scala one covers 135 of the
  908 it claims, and a fourth language it excluded is covered by one it names.
- **Third time in two weeks that an inherited claim was the defect** — ADR-0071
  itself disproved ADR-0069's follow-up, and the 2026-08-21 audit found five
  stale register rows. The lesson is now mechanical rather than cultural: a
  claim about counts is checked by running the census, which exists for that.
