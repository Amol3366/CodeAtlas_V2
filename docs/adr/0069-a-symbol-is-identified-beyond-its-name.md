# ADR-0069 — A symbol is identified beyond its name

- Status: accepted
- Date: 2026-08-22
- Approval: the user, 2026-08-22, on the recommendation to run the product
  against real repositories and fix what that found
- Supersedes: nothing. Extends the identity rules of ADR-0002

## Context

`symbol_id` was `hash(repository_id, relative_path, qualified_name, kind)`, and
`symbols` is keyed `(snapshot_id, symbol_id)`. Two symbols in one file that
share a qualified name and a kind therefore collapsed onto one row, and
indexing ended in `sqlite3.IntegrityError: UNIQUE constraint failed` inside
`_stage`. That is not a degraded answer — **no snapshot was produced**, so the
repository could not be indexed by any surface.

The same shape existed at two more layers:
`logical_chunk_id(repository_id, relative_path, qualified_name, chunk_role)`,
and `relation_id(source_symbol_id, kind, target_hint, start_line, part)`.

**It was found by indexing real repositories rather than fixtures**, which is
also how ADR-0041 through ADR-0045 and ADR-0064 were found. Every one of five
real repositories failed:

| Repository | Language | Collisions |
| --- | --- | ---: |
| `scalaz` | Scala | **270 files, 2204 symbols** — companion `trait`/`object` pairs |
| `google/gson` | Java | 55 files, 264 symbols — `Gson.fromJson` ×11, `Gson.toJson` ×8 |
| `ripgrep` | Rust | 14 files, 32 symbols — `Glob.fmt`, and `cfg`-gated pairs |
| `gin-gonic/gin` | Go | 3 files, 4 symbols |
| `spf13/cobra` | Go | one file — `type key struct{}` in four test functions |

**This was not an ADR-0065 defect.** `python_parser.py` and the query-backed
engine construct the id with the identical call, so it had been latent **since
Phase 1 in the flagship language**: an eight-line Python file containing a
property and its setter could not be indexed. Six of seven languages were
affected, each for its own reason — Python properties and redefinition, Java
and Scala overloads, Scala companions, Go function-local types, Rust methods
implemented for two traits or gated by two `cfg` attributes.

Seven phases of gates passed because every fixture is a two-file toy and this
repository uses none of those constructs: a probe over `src/codeatlas` and
`apps/web/src` finds zero collisions. **A corpus that cannot express a defect
reads as coverage** — the same shape ADR-0062 recorded when a generated corpus
with no Markdown hid a quadratic.

## Decision

**1. Identity is disambiguated; the name is not.**

`ensure_unique_symbol_ids` and `ensure_unique_chunk_ids` run once per file,
after every symbol or chunk for that file exists. Where several share an id,
the **first keeps the id it already had** and later members are re-identified
from that id plus a discriminator.

`qualified_name` is **left untouched**. This is the load-bearing half of the
decision, and it is where this parts company with the prior art:
`tsjs_parser._disambiguate_repeated_symbols` solves a neighbouring problem by
appending `#L103` to the *name*. That is right for an anonymous union member,
whose position genuinely is its only local identity, and wrong here —
`Gson.fromJson#L850` is not a name any caller would type, so every overload
would become unfindable by `codeatlas symbol`. The TS behaviour is unchanged
and its case is still its own.

**2. The discriminator is the best information available, degrading to an
ordinal.**

A symbol uses its `signature`, then its ordinal *within that signature*. A
chunk uses its `symbol_id` — unique once step 1 has run — then its ordinal.
Where a parser knows more, identity is more stable: Python distinguishes a
property from its setter by `(self)` against `(self, v)`, so those two survive
a third method being inserted between them. The query-backed tier reports
`signature is None` for all four languages, so there the ordinal carries it
alone, and inserting a same-named sibling above another shifts the later one's
id.

**That instability is accepted, and named.** It over-reports a change among
same-named siblings in one file. A repository that cannot be indexed at all is
strictly worse, and the remedy — teaching the query-backed engine to emit
signatures — improves this later without changing the scheme.

**3. No reference is attributed to an invented owner.**

`extract_query_references` minted `module_{file_id}` when a file yielded no
definitions — an id that is never stored. Every reference attributed to it
became a relation with a dangling endpoint, and snapshot validation refused the
snapshot. A Java repository containing one `package-info.java` could not index.
It now emits nothing, which is what §4.1 requires: a reference the parser
cannot attribute is not one it may invent an owner for.

**4. A grouped import cites its own line.**

Go and Rust attributed every path in a grouped `import (…)` / `use a::{b, c}`
to the *declaration's* line. That cited a line which does not contain the
import, and made two paths with the same bound name collide on `relation_id` —
`crypto/rand` and `math/rand` in `gin`, both bound `rand`, both reported at the
`import (` line. Each path now carries its own line. Scala was checked and
**does not have this defect** (it yields once per statement); Java has one
import per statement and is unaffected. Neither was changed.

## Consequences

- **No reindex is required, and that is deliberate.** Because the first member
  of a colliding group keeps its id, no id that can be stored today moves. Only
  ids that could never have been stored — their file could not be indexed — are
  new. `PARSER_BUNDLE_VERSION` and `CHUNKER_VERSION` are therefore **unchanged**
  at `1.6.0` and `1.1.0`, and existing snapshots stay valid.
- **No contract, schema, or migration change.** `SCHEMA_VERSION` stays 14 and
  `contract_version` stays `1.1`.
- Repositories that previously failed now index: gson 312 files / 4135 symbols,
  scalaz 590 / 17226, ripgrep 229 / 4210, gin 130 / 1946, cobra 65 / 818.
  `Gson.fromJson` resolves to all its overloads, each with its own line range,
  under the name a caller would type.
- A file that defines nothing now contributes no import edges. By construction
  no relation could have pointed at them, since the owner did not exist.
- Import evidence in Go and Rust moves from the declaration line to the spec
  line. That is a correction: the old line did not contain the import.

## Alternatives rejected

- **Suffix `qualified_name`, as TS/JS does.** Rejected in §1: it makes named
  overloads unfindable by name. The two problems only look alike.
- **Include the signature in `qualified_name`.** Java's own disambiguator, but
  it changes every name a user searches and would move the evaluation corpus's
  expectations — the cost that made the `IMPORTS` prototype fail its gate.
- **Ordinal alone, everywhere.** Simpler, and discards the stability Python's
  signature already provides for free.
- **Include `symbol_id` in `logical_chunk_id` unconditionally.** Correct and
  stable, but changes every code chunk's id and forces a `CHUNKER_VERSION` bump
  and a full reindex for a defect that does not affect anyone whose repository
  currently indexes.
- **Deduplicate by dropping later members.** Rejected outright: it erases real
  symbols, which is what §4.1 forbids.

## Follow-up

- **Teach the query-backed engine to emit `signature`.** It is the one change
  that converts the ordinal fallback into stable identity for four languages.
  Not done here: it is a parser feature, not a defect fix, and bundling it would
  have hidden which change restored indexing.
- **The fixtures still cannot express this defect.** The regression test uses
  synthetic sources per language; no evaluation fixture contains an overload, a
  property setter, a companion object, or a function-local type. Until one does,
  the corpus will keep reading as coverage it does not provide.
