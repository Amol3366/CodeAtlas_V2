# ADR-0065: Query-backed language support for Java, Go, Rust, and Scala

- Status: **accepted** 2026-08-19 — **Java implemented the same day**; Go, Rust and Scala approved and not yet built
- Date: 2026-08-19
- Decision owners: user/product and implementing agent
- Supersedes: none

Design: `docs/superpowers/specs/2026-08-19-query-backed-language-support-design.md`

## Context

CodeAtlas classifies eight languages and produces symbols for seven, but builds
a relation graph for only three — Python, TypeScript, and JavaScript. A
repository in any other language yields **zero symbols and zero relations**,
measured on the live index of this repository: 14 `.sql` files and 21
unrecognised files produced 0 symbols each. Such a repository gets file listing,
full-text search, and a Git diff. The product's own five questions cannot be
answered for it.

The request was to support Go, Java, C#, Rust, Ruby, PHP, C/C++, Kotlin, Swift,
and Scala — eleven languages. That is a program rather than a task: the existing
implementations measure **1,087 lines for Python** (`python_parser.py` plus
`python_relations.py`) and **1,014 for TypeScript and JavaScript together**,
before fixtures, evaluation cases, and the required test layers. Eleven
hand-written parsers is on the order of 11,000 source lines and roughly 25,000
test lines.

### Discovery evidence

A spike on 2026-08-19 measured what Tree-sitter's shipped `tags.scm` query files
actually yield, rather than assuming.

**All eleven grammar packages install cleanly.** **Nine of eleven ship a
`tags.scm`**; `tree-sitter-c-sharp` and `tree-sitter-kotlin` ship no `.scm`
files at all. The nine that do are **9 lines (C) to 66 (Scala)** — ctags-grade
navigation aids.

Yield on matched ~25-line samples:

| Language | Definitions | References | Verdict |
| --- | --- | --- | --- |
| Java | 5 | call 4, class 2, implementation 1 | strong both |
| Go | 5 | call 5, type 17 | strong both |
| Rust | 8 | call 7, implementation 2 | strong both |
| Scala | 8 | call 3, class 1, interface 1 | strong defs, adequate refs |
| Ruby | 5 | call 31 in 22 lines | strong defs, very noisy refs |
| PHP | 8 | call 2 | strong defs, sparse refs |
| Swift | 9 | 0 | definitions only |
| C++ | 6 | 0 | definitions only |
| C | 3 | 0 | definitions only, thin |
| C# / Kotlin | — | — | no `tags.scm` |

**No `tags.scm` captures an import.** Every capture name across all nine was
checked; `definition.module` marks module *declarations*, never `import` / `use`
/ `require`. This is decisive, because resolution is built on the import graph —
4,839 `IMPORTS` edges on this repository — and without imports, cross-file
resolution degrades to name matching, which yields `ambiguous` rather than
`resolved`.

A purely declarative design was therefore disproven before being specified, and
a second time independently: **Go's method receiver is a field of the method
node, not a lexical ancestor**, so a generic scope-walker emits a *wrong*
qualified name rather than a missing one.

## Decision

**Adopt a shared query-backed parser engine with thin per-language adapters, and
apply it to Java, Go, Rust, and Scala only.**

A `TagsBackedParser` engine owns query execution, scope walking, and
`SymbolRecord` assembly. Each language contributes its shipped `tags.scm`, an
`imports.scm` authored in this repository, and an adapter of roughly 150 lines
implementing five methods: `module_path`, `qualified_name`, `owner_hint`,
`imports`, and `visibility`.

Scope delivered: symbols with qualified names and line ranges; `IMPORTS`,
`CALLS`, `INHERITS`, and `IMPLEMENTS` edges; exact symbol lookup, lexical and
symbol search, evidence, and **changed-symbol detection**.

**Explicitly not delivered:** test edges, route detection, configuration and
schema edges, C#, Kotlin, and the remaining five languages. Change preflight on
these languages will be materially thinner than on Python, and no surface may
imply otherwise.

The four languages are chosen because they are the four that measured well on
both axes. Ruby and PHP are deferred on reference quality, Swift/C++/C on the
absence of references, and C#/Kotlin on the absence of the query file itself.

## Alternatives

**Eleven hand-written parsers, mirroring `python_parser.py`.** Highest fidelity
per language and perfectly consistent with the existing codebase. Rejected for
this sub-project: roughly four times the cost per language, and language N+1
costs full price again, so it demonstrates nothing about extensibility.

**A purely declarative design — query files and configuration only, no
per-language Python.** Rejected on measurement, not on taste: no query can
compute Go's `receiver → OrderService.Capture`, and no `tags.scm` supplies
imports.

**`tags.scm` alone, symbols without a relation graph, across all nine
languages.** Broadest reach per unit of work. Rejected because it ships a
CodeAtlas that cannot answer its own second question — "what may be affected?" —
for those languages, while appearing to support them.

**Do nothing.** Rejected: the language boundary excludes most of the market and
is the single largest limit on the product's applicability.

## Consequences

**Positive.** Four languages gain symbols, search, evidence, and changed-symbol
detection. Adding language N+1 costs roughly a quarter of a hand-written parser,
and that claim becomes measurable rather than asserted. `SymbolKind` already
carries every value these produce, so no contract change is needed for symbols.

**Negative, and stated rather than discovered.** `tags.scm`'s `reference.call`
is a pattern match with **no receiver context**, where `python_relations.py`
walks a real `ast` and knows what a call was invoked on. These four languages
will therefore resolve calls **less completely than Python does**. This is
declared as a language limitation in the same form `tsjs_parser.py` already uses
for the absence of `tsc`: what the mechanism cannot see, it does not claim to
know. An edge that cannot be established is absent or `ambiguous`, never
fabricated.

**Evaluation metrics will move, and a drop is not automatically a regression.**
Four new fixtures and their cases change every denominator;
`exact_symbol_resolution`, currently 1.0000, will be measured over a larger and
harder set. Recorded in advance so that a wider measurement is not misread as a
defect, and so that nobody is tempted to trim the corpus to protect a figure.

**One assumption is not backed by measurement.** The design assumes
`resolution.py` generalizes to these languages' module semantics without change
— that Java's `com.shop.orders` ↔ `com/shop/orders/` and Go's package ↔
directory fall out of the `module_suffix_to_file` index ADR-0064 built. That
comes from reading the resolver, not running it. **The implementation plan
verifies it in slice one, before three more languages are built on it.** If
per-language rules are required, `RESOLVER_VERSION` bumps too and the cost
estimate rises.

## Security and Privacy

No data movement changes. Tree-sitter executes nothing, so §4.4's no-execution
invariant holds by construction: no import, build, test, or tooling invocation
is added, and a module specifier remains untrusted text that is recorded and
never followed.

Four new extensions must be added to the `malicious_unsupported` fixture and the
path-safety suites, so traversal, symlink, junction, reserved-name, long-path,
oversized-file, and invalid-Unicode handling is exercised for them as for the
existing languages. Rust needs specific parse-timeout coverage: macro-heavy
source can produce pathological trees, and the timeout is the declared defence.

Four grammar packages are added as pinned dependencies in `uv.lock`. They are
pure grammars with no heavy transitive dependencies, and they are **required**
rather than optional — unlike the semantic extras, deterministic behaviour
depends on them.

## Migration and Rollback

| Item | Change |
| --- | --- |
| `PARSER_BUNDLE_VERSION` | **1.4.0 → 1.5.0**; every snapshot goes stale and every user reindexes |
| `RESOLVER_VERSION` | 1.4.0 unchanged, conditional on the assumption above |
| `SCHEMA_VERSION` | **14, unchanged — no migration.** Every `SymbolKind` value exists; `language` is a free-text column |
| `contract_version` | **1.1, unchanged** — purely additive |
| `classification.py` | Four suffix entries: `.java`, `.go`, `.rs`, `.scala` |

**The forced reindex is the largest operational cost, and it recently became
affordable.** A cold index of this 706-file repository was ~343 s before
ADR-0064 and is **32.6 s** after it. This bump is a reasonable thing to ask of
users now in a way it was not a week ago.

**Rollback:** restore `PARSER_BUNDLE_VERSION` to `1.4.0` and remove the parsers.
Snapshots built under `1.5.0` then read as version-mismatched and are reindexed.
Rollback loses no data and reverses no migration, but costs a second reindex.

## Approval

**Approved by the user on 2026-08-19**, in two stages recorded separately
because they are two different gates.

1. **The design** — the linked spec was reviewed and accepted.
2. **The §25 scope change and the dependencies** — approved explicitly
   afterwards, which is what moves this record from `proposed` to `accepted`.

**Exact scope approved:**

- New programming-language support for **Java, Go, Rust, and Scala** — and only
  those four — through the shared query-backed engine described above.
- Four **required** (not optional) dependencies: `tree-sitter-java`,
  `tree-sitter-go`, `tree-sitter-rust`, `tree-sitter-scala`, pinned in
  `uv.lock` like every other dependency.
- The `PARSER_BUNDLE_VERSION` bump **1.4.0 → 1.5.0** and the full reindex it
  forces on every existing user.

**Explicitly not approved, and still out of scope:** test edges, route
detection, configuration and schema edges, C#, Kotlin, and the remaining five
languages. Each needs its own record.

**Java implemented 2026-08-19**, the same day; Go, Rust and Scala remain
approved and unbuilt. No surface may claim a language is supported until its
implementation lands with verification recorded.

### What implementation found, recorded against this ADR rather than buried

**Section 7's assumption was false.** `resolution.py` did not generalize: it
gated its module index on `record.language == "python"` and derived the module
from the file path, so Java's declared `com.shop.payments` never matched the
path-derived `src.main.java.com.shop.payments` and every cross-package import
resolved `external`. Fixed by indexing a declared `module_path` for languages
that declare one, which is the conditional `RESOLVER_VERSION` bump this record
scoped: **1.4.0 -> 1.5.0**, landed alongside `PARSER_BUNDLE_VERSION` 1.4.0 ->
1.5.0 so users reindex once rather than twice.

Planning Java alone is what made this cheap. The assumption cost one
integration test to disprove instead of four languages of rework.
