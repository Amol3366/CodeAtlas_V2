# Query-backed language support: Java, Go, Rust, and Scala

Status: proposed. Requires an `AGENTS.md` §25 approval and an ADR before
implementation.
Date: 2026-08-19
Authority: `AGENTS.md` is the contract. This spec is subordinate to it.
Related: ADR-0003 (the corpus is never edited to move a number), ADR-0004
(relation model and derivation classes), ADR-0017 (`SUPPORTED_FIXTURES` must not
silently gate a fixture out), ADR-0064 (resolution indexing — which is what makes
the forced reindex affordable).

## 1. Why

CodeAtlas processes eight languages and produces symbols for seven of them, but
a relation graph for only three: Python, TypeScript, and JavaScript. A
repository written in Java, Go, Rust, C#, Ruby, PHP, C/C++, Kotlin, Swift, or
Scala yields **zero symbols and zero relations**. It gets file listing, full-text
search, and a Git diff. The core product — "what changed, what may be affected,
what evidence proves it" — does not function.

That is a hard boundary rather than a coverage gap, and it excludes most of the
market. The request that produced this spec was to support all eleven of those
languages.

Eleven languages is a program, not a task. This spec covers the first
sub-project: **four languages through one shared, query-backed mechanism**,
chosen because measurement showed those four are where the mechanism works
best.

### The governing principle

**A parser declares what its mechanism cannot see.**

`tsjs_parser.py` already sets this precedent: TypeScript gets no `tsc`, because
running it would execute repository tooling, so inferred types and resolved
module graphs are declared as limitations rather than papered over. The
mechanism in this spec sees less than a hand-written parser does, in one
specific way (Section 6), and that limitation is declared in the ADR and carried
in the derivation of every affected edge.

## 2. Scope

**In:** Java, Go, Rust, Scala. Symbols with qualified names and line ranges;
`IMPORTS`, `CALLS`, `INHERITS`, and `IMPLEMENTS` edges; participation in exact
symbol lookup, lexical and symbol search, evidence, and **changed-symbol
detection**.

**Out, and deliberately so:** test edges (JUnit, `go test`, `#[test]`,
ScalaTest); route detection (Spring, gin, actix, Play); configuration and schema
edges; C# and Kotlin; the remaining five languages. Each is a later sub-project
with its own spec.

**Consequence to state plainly:** change preflight has two halves. This
sub-project delivers "what symbols changed" for four new languages. It delivers
"what else is affected" only as far as `IMPORTS` and `CALLS` resolution reaches,
and it delivers no test or route mapping at all. A preflight on a Java
repository will be materially thinner than one on a Python repository, and the
UI must not imply otherwise.

## 3. Discovery evidence

`AGENTS.md` §25 requires discovery evidence for new language support. This was
measured on 2026-08-19, not assumed.

**All eleven grammar packages install cleanly** — including Kotlin and Swift,
which were expected to fail. No build step, no heavy transitive dependencies.

**Nine of eleven ship a `tags.scm` query file.** `tree-sitter-c-sharp` and
`tree-sitter-kotlin` ship no `.scm` files at all. The nine that do range from
**9 lines (C) to 66 (Scala)** — these are ctags-grade navigation aids, and their
size is the first warning against over-relying on them.

Yield, measured on matched ~25-line samples containing an interface, a class, a
constructor, methods, a constant, a field, and cross-file calls:

| Language | Definitions | References | Verdict |
| --- | --- | --- | --- |
| Java | 5 — class, interface, 3 methods | call 4, class 2, implementation 1 | strong both |
| Go | 5 — 2 types, function, 2 methods | call 5, type 17 | strong both |
| Rust | 8 | call 7, implementation 2 | strong both |
| Scala | 8 — incl. object, property, variable | call 3, class 1, interface 1 | strong defs, adequate refs |
| Ruby | 5 | call 31 in a 22-line file | strong defs, very noisy refs |
| PHP | 8 — incl. fields | call 2 | strong defs, sparse refs |
| Swift | 9 — incl. properties | 0 | definitions only |
| C++ | 6 | 0 | definitions only |
| C | 3 | 0 | definitions only, thin |
| C# / Kotlin | — | — | no `tags.scm` |

**The four chosen languages are the four with both strong definitions and usable
references.** Ruby and PHP are deferred on reference quality; Swift, C++, and C
on the total absence of references; C# and Kotlin on the absence of the query
file itself.

### The finding that shaped the architecture

**No `tags.scm` captures an import.** Every capture name across all nine was
checked. The `definition.module` captures are module *declarations*
(`namespace Shop\Orders`, `module Orders`), never `import` / `use` / `require`
statements. There is no `reference.import` anywhere.

This matters more than the yield table, because CodeAtlas's resolution is built
on imports — 4,839 `IMPORTS` edges on this repository, and the import graph is
what lets the resolver turn a bare call name into a definite target. Without
imports, cross-file resolution degrades to name matching, which yields
`ambiguous`, not `resolved`.

A purely declarative design — grammar query files and nothing else — was
proposed and **disproven by measurement** before it was specified:

- **Go**: the receiver is a *field* of the method node, not a lexical ancestor.
  A generic scope-walker climbing ancestors emits `Audit` with no owner, which
  is a wrong qualified name rather than a missing one.
- **Rust**: `impl_item` exposes `type` and `trait` fields. Ancestor walking works
  here, but only by reading those fields — and `impl Auditable for OrderService`
  yields an `IMPLEMENTS` edge directly, which is a bonus the design should take.

`tags.scm` therefore reduces per-language cost by roughly 4× against a
hand-written parser. It does not eliminate it.

## 4. Architecture

```text
src/codeatlas/parsing/
├── registry.py                  UNCHANGED — four additional register() calls
└── query_backed/
    ├── engine.py        ~350    query execution, scope walking, SymbolRecord assembly
    ├── profile.py       ~120    LanguageProfile and LanguageAdapter contracts
    ├── queries/                 java/go/rust/scala .imports.scm — authored here
    └── languages/               java.py · go.py · rust.py · scala.py — ~150 each
src/codeatlas/extraction/
└── query_relations.py   ~250    captures -> SymbolReference
```

`registry.py` already dispatches on a parser's `supported_languages` frozenset,
so the four adapters register exactly as `PythonParser` does. Nothing changes in
the registry, the snapshot lifecycle, or the storage layer. The only edit
outside `parsing/` and `extraction/` is four new suffix entries in
`repositories/classification.py` (Section 10).

**The engine remains a pure function of one `ParseRequest`**, the invariant
`registry.py` states in its own docstring. It never reads a second file. Imports
are emitted as `SymbolReference`s carrying a target hint, and resolution happens
later against the whole snapshot. This is the existing two-stage split described
in `docs/operations/relations-and-graph.md`, not a new pattern, and it is what
keeps an unchanged file's references reusable across analyses.

## 5. The adapter contract

```python
@dataclass(frozen=True)
class LanguageProfile:
    language: str                          # "java"
    grammar: Language
    tags_query: Query                      # the grammar's shipped tags.scm
    imports_query: Query                   # authored in queries/
    kind_by_capture: Mapping[str, SymbolKind]
    scope_node_types: frozenset[str]

class LanguageAdapter(Protocol):
    def module_path(self, tree, source, relative_path) -> str: ...
    def qualified_name(self, node, name, scopes) -> str: ...
    def owner_hint(self, node, source) -> str | None: ...
    def imports(self, captures, source) -> Iterable[SymbolReference]: ...
    def visibility(self, node, name) -> Visibility: ...
```

Five methods per language. The measured cases land in `owner_hint` and
`visibility`:

| Language | `module_path` | `owner_hint` | `visibility` |
| --- | --- | --- | --- |
| Java | `package_declaration` | enclosing class chain | `public` / `private` modifiers |
| Go | `package_clause` + directory | **`receiver` field** | **leading uppercase = exported** |
| Rust | file path + `mod` declarations | **`impl_item.type`**; `trait` field yields `IMPLEMENTS` | `pub` |
| Scala | `package_clause` | object / class nesting | modifiers |

`SymbolKind` already carries every value these produce — `MODULE`, `PACKAGE`,
`CLASS`, `INTERFACE`, `ENUM`, `FUNCTION`, `METHOD`, `CONSTRUCTOR`, `PROPERTY`,
`FIELD`, `CONSTANT`, `TYPE_ALIAS`. **No contract change for symbols.**

## 6. Derivation, and the limitation this mechanism carries

`tags.scm`'s `reference.call` is a pattern match with **no receiver context**.
`python_relations.py` walks a real `ast` and knows what a call was invoked on; a
query capture frequently knows only the name. That is strictly less information
and must be stated rather than hidden.

| Edge | Derivation |
| --- | --- |
| Symbols (definitions) | Facts from the parse, as with Python — not derivation-bearing |
| `IMPORTS` | `static_resolved` when bound; otherwise `external` or `unresolved` |
| `CALLS`, bound unambiguously through the import graph | `static_resolved` |
| `CALLS`, unique in-file or in-package match only | `high_confidence_heuristic` |
| `CALLS`, several candidates | `ambiguous` — never guessed |
| `INHERITS` / `IMPLEMENTS` | `static_resolved` |

**Expect these four languages to resolve calls less completely than Python
does.** The ADR carries that as a declared language limitation in the same form
`tsjs_parser.py` uses for the absence of `tsc`. An edge the mechanism cannot
establish is absent or `ambiguous`; it is never fabricated.

## 7. Resolution: the one assumption this design does not prove

Everything above rests on measurements taken on 2026-08-19. **This section does
not.**

The design assumes `resolution.py` generalizes to these languages' module
semantics without change — that Java's `com.shop.orders` ↔ `com/shop/orders/`,
Go's package ↔ directory, and Rust's `crate::payments` ↔ file path all fall out
of the `module_suffix_to_file` index ADR-0064 built. That belief comes from
reading the resolver, not from running it.

**The implementation plan must test this in slice one, before three more
languages are built on it.** If per-language module rules are required,
`RESOLVER_VERSION` bumps from `1.4.0` alongside `PARSER_BUNDLE_VERSION`, and the
per-language cost estimate in Section 12 rises. Finding that out in week one is
cheap; finding it out in week four is not.

## 8. Testing and fixtures

Per language: unit tests for each adapter method; a **golden test** mapping a
sample file to exact `SymbolRecord`s including qualified names and line ranges;
an integration test that indexes a fixture repository and asserts symbol counts
and resolution states; malformed-input and parse-timeout tests. **Every fix and
every new assertion is mutation-checked** — the project's standing rule, and the
reason a test that passes on its first run is not yet evidence.

Rust needs specific parse-timeout attention: macro-heavy source can produce
pathological trees, and the timeout is the declared defence.

Four new fixtures (`java_app`, `go_app`, `rust_app`, `scala_app`) trip guards
that are hardcoded on purpose:

```
tests/evaluation/test_dataset.py:24    assert len(dataset.fixtures) == 7
tests/evaluation/test_dataset.py:25    assert len(dataset.query_cases) == 65
tests/evaluation/test_dataset.py:26    assert len(dataset.change_cases) == 28
tests/evaluation/test_engine_adapter.py:94
    assert corpus_fixtures - {"malicious_unsupported"} == set(SUPPORTED_FIXTURES)
```

The last is the important one: **a fixture not added to `SUPPORTED_FIXTURES`
fails the suite.** That is ADR-0017's lesson wired into a test so the same
silent gating cannot recur. All four guards are updated deliberately, in the
same diff as the fixtures they describe.

## 9. Evaluation corpus and baselines

New fixtures and new query cases are **additive coverage**. ADR-0003 forbids
editing an expectation to move a number; it does not forbid measuring more. Each
new case declares its expected symbols, relations, and evidence **before** the
engine runs against it — the rule that made the Phase 7 measurement credible.

Regenerate `baseline-phase-0`, `-3`, and `-4` once, at the end of the work.
**`baseline-phase-1` and `-2` stay frozen as history.**

**Aggregate metrics will move, and a drop is not automatically a regression.**
Adding four languages' worth of cases changes every denominator, and
`exact_symbol_resolution` — currently 1.0000 — will be measured over a larger
and harder set. The ADR states this in advance so that a lower number is read as
a wider measurement rather than as a defect, and so that nobody is tempted to
trim the corpus to protect a figure.

## 10. Versioning, migration, and rollback

| Item | Change |
| --- | --- |
| `PARSER_BUNDLE_VERSION` | **1.4.0 → 1.5.0.** Every existing snapshot goes stale; every user reindexes |
| `RESOLVER_VERSION` | **1.4.0, unchanged** — conditional on Section 7 |
| `SCHEMA_VERSION` | **14, unchanged.** No migration: every `SymbolKind` value exists and `language` is a free-text column |
| `contract_version` | **1.1, unchanged** — purely additive |
| `pyproject.toml` | Four pinned grammar dependencies |
| `classification.py` | Four entries: `.java`, `.go`, `.rs`, `.scala` |

**The forced reindex is the largest operational cost, and it recently became
affordable.** A cold index of this 706-file repository was ~343 s before
ADR-0064 and is **32.6 s** after it. A `PARSER_BUNDLE_VERSION` bump is a
reasonable thing to ask of users now in a way it was not a week ago, and the ADR
should say so.

**Rollback:** restore `PARSER_BUNDLE_VERSION` to `1.4.0` and remove the parsers.
Snapshots built under `1.5.0` then read as version-mismatched and are reindexed.
Rollback is safe and loses no data — there is no migration to reverse — but it
costs a second reindex.

## 11. Security

Tree-sitter executes nothing, so §4.4's no-execution invariant holds by
construction: no import, build, test, or tooling invocation is added.

The four new extensions must be added to the `malicious_unsupported` fixture and
to the path-safety suites, so that traversal, symlink, junction, reserved-name,
long-path, oversized-file, and invalid-Unicode handling is exercised for them as
it is for the existing languages. Grammar packages are pinned in `uv.lock` like
every other dependency.

## 12. Delivery order and checkpoints

**Java → Go → Rust → Scala**, each a complete vertical slice: adapter, import
query, fixture, evaluation cases, documentation.

Java goes first because its `tags.scm` was strongest and its package ↔ directory
mapping is the cleanest test of Section 7's unproven assumption.

**Checkpoint after slice one**, with the user: the seam is proven or disproven
there, and the estimate for the remaining three depends on the answer. Estimated
cost is roughly one week to the first working language, then 1.5–2 days per
language — against 2–4 weeks for the same four as hand-written parsers.

## 13. The ADR this requires

`AGENTS.md` §25 lists new programming-language support among the changes needing
documented need, discovery evidence, security and operational impact, a
migration and rollback plan, and explicit approval. A single ADR covers this
sub-project and must record:

1. the discovery evidence in Section 3, including the two languages that ship no
   query file and the five deferred on reference quality;
2. the absence of import captures, and the hybrid design that follows from it;
3. the declared limitation that query-derived calls carry no receiver context;
4. the `PARSER_BUNDLE_VERSION` bump, the forced reindex, and the rollback cost;
5. the advance statement that aggregate evaluation metrics will move, and that a
   wider measurement is not a regression;
6. that test edges, route detection, C#, and Kotlin are explicitly out of scope.
