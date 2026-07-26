# Phase 3 — Polyglot Graph and Delivery Contracts

Status: `awaiting_user_approval`
Gate authority: user
Prerequisites: Phase 2 approved; `CLAUDE.md`; the blueprint
Activation gate: this plan must be approved by the user before P3-SETUP moves to
`in_progress`. No Phase 3 implementation may begin before that approval.

## Outcome

A symbol in Python, TypeScript, or JavaScript resolves to the same verified
evidence through the application service, REST, the CLI, and MCP; and the
questions "who calls this", "what does this import", "what is exported", and
"which tests cover this" are answered from stored relations with a bounded,
reported traversal — never from a guess and never from a model.

## Completion Gate (from `CLAUDE.md` Section 20)

Phase 3 may enter `awaiting_user_approval` only when all of the following hold
with verification evidence recorded in the handoff log:

1. Supported Python, TypeScript, and JavaScript symbols resolve consistently
   through the shared application services.
2. Supported relations resolve consistently through the same services.
3. REST, CLI, and MCP outputs pass the same evidence-contract tests.
4. Graph traversal is bounded in depth, visited nodes, and results, and reports
   truncation instead of hiding it.
5. Every relation carries a derivation label that matches how it was actually
   derived, and no heuristic edge is presented as deterministic.
6. Relation extraction is reused on unchanged files while resolution is
   recomputed for the whole snapshot, proven by counters.
7. Cross-file and cross-language edges cannot survive into a snapshot whose
   target symbol no longer exists.

## What Phase 2 Left in Place

Build on these; do not re-derive or duplicate them.

| Asset | Location | Phase 3 relevance |
| --- | --- | --- |
| `RelationKind` with 17 members | `contracts.py` | already defined; Phase 3 implements a declared subset and must not silently widen it |
| `SymbolKind` including `INTERFACE`, `TYPE_ALIAS`, `PROPERTY` | `contracts.py` | TS/JS symbols map onto existing kinds; no new kinds needed |
| `classify()` returning `typescript` / `javascript` for `.ts/.tsx/.js/.jsx/.mjs/.cjs` | `repositories/classification.py` | the language labels already exist; only a parser is missing |
| `ParserRegistry` refusing to shadow a language | `parsing/registry.py` | the TS/JS parser registers alongside Python and documents |
| `ParseResult` (symbols + diagnostics) | `parsing/registry.py` | extended with references, not replaced |
| `SymbolStore.find_exact`, `copy_from_snapshot` | `storage/sqlite/stores.py` | relation resolution and reuse build directly on these |
| `EvidenceBuilder`, `snapshot_reference`, `build_excerpt` | `application/evidence.py` | every graph answer emits evidence through this one builder |
| `LexicalSearchService` | `retrieval/lexical.py` | graph answers fall back to lexical when a symbol is ambiguous |
| `SnapshotRecoveryService` (rollback, orphan recovery, prune) | `application/recovery.py` | relations cascade with snapshot deletion; `prune` needs no change if foreign keys are declared correctly |
| Reuse counters (`ReuseStats`) | `application/indexing.py` | extended with reference/relation counters |
| `scripts/check_phase2.ps1` | `scripts/` | the model for `check_phase3.ps1` |

## Evidence Granularity — Decided

**Ruling (user, 2026-07-26): score containment separately.** Option C of the
three presented at the Phase 2 gate.

The Phase 2 gate measured a disagreement: the corpus expects sub-definition and
sub-section line ranges, while the engine emits whole structural units. Four
cases (`q009`, `q023`, `q027`, `q031`) name the right file with a containing or
overlapping range and were scored as misses, depressing `valid_evidence_rate`
from 0.8000 to 0.6923.

Neither side is corrected. The evaluation runner reports **two** metrics instead
of one:

| Metric | Counts a hit when |
| --- | --- |
| `exact_evidence_rate` | The predicted range equals the expected range |
| `containing_evidence_rate` | The predicted range contains the expected range in the same file |

`valid_evidence_rate` is retained as the stricter of the two so no historical
number silently changes meaning, and both are reported side by side in every
baseline from Phase 3 onward.

Why this is the right call rather than the cheap one: the product does not yet
know which granularity a reader wants. Narrowing the evidence would optimize for
the corpus before that question is answered, and widening the corpus would move
the target to meet the engine. Reporting both keeps the gap measured and visible
until a real consumer — the Phase 5 evidence drawer, most likely — settles it.

Consequences the tasks must honor:

- The gap stays open and stays instrumented. It is **not** resolved by this
  ruling, and P3-10 must report both metrics rather than quoting the flattering
  one.
- No engine change and no corpus edit. Phase 1 and Phase 2 evidence *output* is
  unchanged by this ruling.
- The baseline **artifact schema** does change, because two metrics are added.
  `scripts/check_phase2.ps1` will therefore stop passing, exactly as
  `check_phase1.ps1` did when the Phase 2 engine advanced. P3-SETUP marks it
  superseded and records why; the Phase 2 artifacts are kept unchanged as the
  record of that gate. Do not regenerate them.
- The Phase 3 gate is measured against `containing_evidence_rate` for the
  Section 19.3 recall targets, with `exact_evidence_rate` reported alongside it.
  Any gate claim must name which metric it used.
- Recorded as ADR-0003 in P3-SETUP, including the deferral: the granularity
  question returns for decision in Phase 5, when a UI consumer exists.

## Global Constraints

Phase 1 and Phase 2 constraints all still apply. Additions and emphases:

- Relation extraction MUST be a pure function of one file's bytes. Anything
  needing another file is *resolution*, not extraction, and happens later.
- A relation MUST NOT be emitted without a source line range that maps exactly
  onto real source. An edge with no citable site is not evidence.
- Resolution MUST be recomputed for the whole snapshot on every index run. A
  reused file's references are reused; its resolved targets are not.
- A name that resolves to more than one candidate MUST NOT become a `CALLS`
  edge. It becomes `MAY_CALL` with a heuristic derivation, or nothing.
- Traversal MUST be bounded and MUST report truncation. A silently truncated
  graph answer is a false negative presented as a complete one.
- The TS/JS parser MUST NOT execute, import, transpile, type-check, or resolve
  through a package manager. No `node`, no `tsc`, no `node_modules` resolution.
- MCP MUST bind to stdio only. No network listener, no new port.
- Migrations are forward-only and additive. `0001`–`0004` are applied and MUST
  NOT be edited; Phase 3 adds `0005` and `0006`.
- Exactly one task may be `in_progress` or `verifying`.
- Test-first: write the failing test, observe it fail, then implement.

## Non-Goals (explicitly deferred)

| Deferred item | Phase |
| --- | --- |
| Diff analysis, change impact, risk ordering, SARIF | 4 |
| Conversations, message persistence, SSE streaming, web UI | 5 |
| Filesystem watcher, packaging, upgrade/backup workflows | 6 |
| Embeddings, reranking, generation | 7 |
| Fuzzy identifier search (RapidFuzz) | 4+ |
| Type inference, generics resolution, cross-module type flow | out of scope for the product profile |
| `tsconfig.json` `paths` aliases and monorepo workspace resolution | 4+ — declared as a limitation in Phase 3 |
| Dynamic `import()`, `require()` with a computed specifier, re-export chains beyond one hop | 4+ — emitted as unresolved with a warning |
| Decorator-driven route relations (`ROUTES_TO` beyond a literal path match) | 4 |
| `READS`/`WRITES`/`QUERIES`/`DATABASE_*` relations | 4+ |
| New languages beyond Python, TypeScript, and JavaScript | requires `CLAUDE.md` Section 25 approval |

## Phase Architecture Decisions

Fixed for Phase 3 so tasks compose. Deviation requires an ADR and user approval.

### Extraction and resolution are two separate stages

This is the central decision of the phase and everything else follows from it.

```text
parse file ──▶ SymbolReference (source symbol, target *hint*, kind, line range)
                        │        pure function of one file  → reusable
                        ▼
              resolve across snapshot ──▶ RelationRecord (target_symbol_id or NULL)
                                          needs every file  → always recomputed
```

A reference records what the source file *said*: `total`, `"./orders"`,
`Order`. A relation records what that turned out to mean in this snapshot. The
split buys three properties that a single-stage design cannot have:

- **Reuse stays sound.** An unchanged file's references are byte-identical, so
  they copy forward. Its *targets* may have moved, so they are re-resolved.
- **Stale cross-file edges become impossible.** `CLAUDE.md` Section 9 requires
  "necessary reverse relations" to be recalculated when a file changes.
  Re-resolving everything satisfies that by construction rather than by
  bookkeeping that can drift.
- **Unresolved is a first-class state**, not a missing row. An import of
  `react` is a real fact about the file even though no symbol in the repository
  answers it.

Resolution is an in-memory pass over a name index built once per snapshot. It is
O(references), not O(references × symbols).

### Relation identity

| ID | Inputs |
| --- | --- |
| `relation_id` | `rel_` + `stable_hash(source_symbol_id, kind, target_hint, start_line, part)` |

Relations are snapshot-scoped rows, like chunks. `relation_id` is stable across
snapshots for an unchanged call site, which is what makes reuse observable and
what lets Phase 4 say "this edge is new".

### New version constant

`codeatlas.extraction.resolution.RESOLVER_VERSION = "1.0.0"`, joining
`PARSER_BUNDLE_VERSION`, `INDEX_VERSION`, and `CHUNKER_VERSION` as a
truth-bearing input to `snapshot_id`. Resolution logic can change which edges
exist without any parser changing, so it needs its own invalidation handle.

`PARSER_BUNDLE_VERSION` moves to `"1.1.0"`: parsers now emit references, so
every previously derived symbol version is stale.

### Supported relations and their derivations

Only these are emitted in Phase 3. Anything else stays unimplemented rather than
approximated.

| Kind | Source | Derivation | Notes |
| --- | --- | --- | --- |
| `CONTAINS` | structural nesting | `deterministic` | module → class → method |
| `IMPORTS` | import statement, resolved to a repository file | `static_resolved` | |
| `IMPORTS` | import statement, target outside the repository | `deterministic` | the statement is a fact; `target_symbol_id` is NULL, `resolution` is `external` |
| `EXPORTS` | `export` / `__all__` | `deterministic` | syntactic, no resolution needed |
| `INHERITS` | base class resolved to one candidate | `static_resolved` | |
| `IMPLEMENTS` | TS `implements` clause resolved to one candidate | `static_resolved` | |
| `CALLS` | call whose callee name resolves to exactly one candidate in scope | `static_resolved` | |
| `MAY_CALL` | call whose name resolves to more than one candidate | `high_confidence_heuristic` | every candidate is recorded; none is promoted |
| `REFERENCES` | type annotation or type reference resolved to one candidate | `static_resolved` | |
| `TESTS` | symbol in a `TEST_CODE` file that imports and calls the target | `high_confidence_heuristic` | import **and** call; a name match alone is not enough |
| `DOCUMENTS` | a document section whose text names a symbol that exists | `low_confidence_heuristic` | advisory discovery only, never a finding |

A call through a variable, an attribute of unknown type, a computed member, or
`getattr` is **not emitted at all**. Absence is reported as a limitation on the
answer; it is not filled with a guess.

### Traversal bounds

| Bound | Default | Maximum |
| --- | --- | --- |
| Depth | 2 | 5 |
| Visited nodes | 200 | 1,000 |
| Returned edges | 50 | 200 |
| Returned paths | 10 | 25 |

Traversal is breadth-first, cycle-safe by a visited set, and deterministically
ordered by `(depth, file path, start line, relation kind)` so the same snapshot
always produces the same answer. Hitting any bound appends a
`GRAPH_TRUNCATED_*` warning and a limitation naming the bound that was hit.

### Relation paths in the response contract

`QueryResponse` gains one optional field:

```python
class RelationStep(ContractModel):
    source: NonEmptyText
    kind: RelationKind
    target: NonEmptyText
    derivation: Derivation
    confidence: Confidence
    evidence_id: OpaqueId

class RelationPath(ContractModel):
    steps: list[RelationStep] = Field(min_length=1)

# QueryResponse
relation_paths: list[RelationPath] = Field(default_factory=list)
```

This is **additive and optional**, so `contract_version` stays `"1.0"` and no
existing consumer breaks. Every step cites evidence, so a path is auditable edge
by edge rather than as an opaque conclusion. `docs/api/contract-v1.schema.json`
is regenerated in P3-08 and the change is recorded in ADR-0004.

### Evidence becomes addressable

`GET /v1/evidence/{evidence_id}` is required by `CLAUDE.md` Section 12.3, and
Phase 5 needs it for citations. Evidence IDs are content-derived hashes and are
not reversible, so Phase 3 persists them.

An `evidence` table stores `evidence_id`, `snapshot_id`, `file_id`, line range,
`content_hash`, and `derivation` — **not the excerpt**. Fetching re-reads the
file from disk and re-verifies the hash, exactly as query-time evidence already
does, so a stored row can never outlive the content it describes. Rows are
upserted when a response is built, cascade with snapshot deletion, and add one
short transaction per query.

### Snapshot lifecycle addition

```text
discovered -> scanning -> parsing -> chunking -> resolving -> indexing -> validating -> active
```

`RESOLVING` is a new `SnapshotState`. Validation gains three checks: every
relation's source symbol exists in the snapshot; every resolved
`target_symbol_id` exists in the snapshot; no relation cites a line outside its
file's line count.

### Error codes added

| Code | Meaning | HTTP | CLI exit |
| --- | --- | --- | --- |
| `EVIDENCE_NOT_FOUND` | No such evidence in the active snapshot | 404 | 3 |
| `FILE_NOT_FOUND` | No such file in the active snapshot | 404 | 3 |
| `SYMBOL_NOT_FOUND` | No such symbol in the active snapshot | 404 | 3 |

Ambiguity and absence of relations remain abstentions with warnings, not errors.

### Module map additions

```text
src/codeatlas/
├── domain/
│   └── relations.py            # SymbolReference, RelationRecord, ResolutionState
├── parsing/
│   └── tsjs_parser.py          # TypeScript/JavaScript symbols and references
├── extraction/
│   ├── __init__.py
│   ├── python_relations.py     # references from a Python ast module
│   ├── tsjs_relations.py       # references from a TS/JS tree-sitter tree
│   └── resolution.py           # RESOLVER_VERSION, SnapshotResolver
├── retrieval/
│   └── graph.py                # BoundedGraphTraversal
├── application/
│   └── graph_queries.py        # callers, callees, dependencies, exports, tests, docs
├── mcp/
│   ├── __init__.py
│   ├── server.py               # stdio server
│   └── tools.py                # versioned tool schemas over ApplicationServices
├── api/routers/
│   ├── entities.py             # /v1/evidence, /v1/files, /v1/symbols
│   └── graph.py                # /v1/symbols/{id}/relations
└── storage/sqlite/
    ├── migrations/0005_phase3_relations.sql
    ├── migrations/0006_phase3_evidence.sql
    └── stores.py               # + RelationStore, EvidenceStore
```

## Task Board

| Task     | Deliverable                                                | Dependencies   | Status    |
| -------- | ---------------------------------------------------------- | -------------- | --------- |
| P3-SETUP | Dependencies, ADR-0003 (granularity), ADR-0004 (contract)   | Phase 2        | `pending` |
| P3-01    | Relation domain, identity, migration `0005`, `RelationStore` | P3-SETUP      | `pending` |
| P3-02    | Python reference extraction                                 | P3-01          | `pending` |
| P3-03    | TypeScript/JavaScript parser (symbols)                      | P3-SETUP       | `pending` |
| P3-04    | TypeScript/JavaScript reference extraction                  | P3-02, P3-03   | `pending` |
| P3-05    | Snapshot resolution and indexing integration                | P3-04          | `pending` |
| P3-06    | Bounded graph traversal                                     | P3-05          | `pending` |
| P3-07    | Graph query application services                            | P3-06          | `pending` |
| P3-08    | Complete REST and CLI adapters, evidence addressing         | P3-07          | `pending` |
| P3-09    | Initial versioned MCP adapter                               | P3-08          | `pending` |
| P3-10    | Cross-adapter contract suite, baseline, docs, phase gate    | P3-09          | `pending` |

---

## P3-SETUP — Dependencies, Decisions, and Version Bumps

**Why first:** the decisions and version bumps change output shape, and all of
them are cheaper to make before ten tasks depend on them than after.

**Files**

- Modify: `pyproject.toml`, `uv.lock`
- Create: `docs/adr/0003-evidence-granularity.md`
- Create: `docs/adr/0004-relation-model-and-contract-additions.md`
- Modify: `src/codeatlas/evaluation/runner.py` (dual evidence metrics)
- Modify: `tests/evaluation/test_runner.py`
- Modify: `src/codeatlas/parsing/registry.py` (`PARSER_BUNDLE_VERSION = "1.1.0"`)
- Modify: `src/codeatlas/domain/snapshot.py` (`RESOLVING` state, `resolver_version`)
- Modify: `scripts/check_phase2.ps1` (mark superseded),
  `docs/evaluation/phase-2-baseline-environment.md` (record why)

**Dependencies added**

```toml
"tree-sitter-typescript>=0.23,<0.24",
"tree-sitter-javascript>=0.23,<0.24",
"mcp>=1.2,<2",
```

Pin exactly as resolved and check the lockfile in. `tree_sitter_typescript` and
`tree_sitter_javascript` need MyPy `ignore_missing_imports` overrides alongside
the existing `tree_sitter_python` entry.

`CLAUDE.md` Section 25 lists "new programming-language support" as requiring
approval; Section 20 already approves TypeScript and JavaScript for this phase.
Record that reading in ADR-0004 so the exemption is explicit, not assumed.

**Steps**

- [ ] **Step 1: Write ADR-0003** recording the user's ruling — score containment
  separately — its rationale, its consequences, and its deferral to Phase 5.
- [ ] **Step 2: Write the failing runner tests** for `exact_evidence_rate` and
  `containing_evidence_rate`, including the case that distinguishes them: a
  prediction whose range strictly contains the expected range scores 0 on the
  first and 1 on the second. Then implement both metrics.
- [ ] **Step 3: Write ADR-0004** covering the relation model, the two-stage
  extraction/resolution split, the derivation table, the additive contract
  fields, and the language-support reading.
- [ ] **Step 4: Add the dependencies** with `uv add`, verify the lockfile is
  reproducible, and confirm all three grammars load in a throwaway script.
- [ ] **Step 5: Bump `PARSER_BUNDLE_VERSION`, add the `RESOLVING` state**, and
  confirm the existing suite still passes with the new snapshot IDs.
- [ ] **Step 6: Run the full gate** and append the handoff.

**Acceptance**

- Both ADRs are written and ADR-0003 records the user's actual ruling, not an
  assumption.
- The runner reports both evidence metrics, and a test proves they differ on a
  containing-but-not-equal prediction.
- `uv sync --all-groups --frozen` succeeds and all three grammars load.
- The Phase 2 suite passes unchanged apart from snapshot-ID-derived values.

---

## P3-01 — Relation Domain, Migration `0005`, and `RelationStore`

**Files**

- Create: `src/codeatlas/domain/relations.py`
- Modify: `src/codeatlas/domain/ids.py` (`relation_id`)
- Create: `src/codeatlas/storage/sqlite/migrations/0005_phase3_relations.sql`
- Modify: `src/codeatlas/storage/sqlite/migrations.py` (`SCHEMA_VERSION = 5`)
- Modify: `src/codeatlas/storage/sqlite/stores.py` (add `RelationStore`)
- Create: `tests/unit/test_relation_ids.py`
- Create: `tests/integration/test_relation_store.py`
- Modify: `tests/integration/test_migrations.py`

**Interfaces produced**

```python
# domain/relations.py
class ResolutionState(StrEnum):
    RESOLVED = "resolved"      # target_symbol_id names a symbol in this snapshot
    EXTERNAL = "external"      # the target is real but outside the repository
    UNRESOLVED = "unresolved"  # the target could not be determined
    AMBIGUOUS = "ambiguous"    # more than one candidate; recorded, not chosen

@dataclass(frozen=True)
class SymbolReference:
    """What one file said, before anything else was consulted."""
    source_symbol_id: str
    file_id: str
    kind: RelationKind
    target_hint: str          # "total", "./orders", "IdempotencyStore.claim"
    module_hint: str          # "" unless the reference names a module
    start_line: int
    end_line: int

@dataclass(frozen=True)
class RelationRecord:
    relation_id: str
    source_symbol_id: str
    target_symbol_id: str | None
    file_id: str
    kind: RelationKind
    target_hint: str
    resolution: ResolutionState
    derivation: Derivation
    confidence: float
    start_line: int
    end_line: int
    candidate_count: int      # 1 when resolved; >1 when ambiguous

# storage/sqlite/stores.py
class RelationStore:
    def add_many(self, snapshot_id: str, relations: Sequence[RelationRecord]) -> None: ...
    def list_for_snapshot(self, snapshot_id: str) -> tuple[RelationRecord, ...]: ...
    def list_for_file(self, snapshot_id: str, file_id: str) -> tuple[RelationRecord, ...]: ...
    def outgoing(self, snapshot_id: str, symbol_ids: Sequence[str],
                 kinds: Sequence[RelationKind] | None = None) -> tuple[RelationRecord, ...]: ...
    def incoming(self, snapshot_id: str, symbol_ids: Sequence[str],
                 kinds: Sequence[RelationKind] | None = None) -> tuple[RelationRecord, ...]: ...
    def count_for_snapshot(self, snapshot_id: str) -> int: ...
    def dangling_endpoints(self, snapshot_id: str) -> tuple[str, ...]: ...
    def delete_for_snapshot(self, snapshot_id: str) -> None: ...
```

`outgoing` and `incoming` take a **sequence** of symbol IDs so traversal expands
a whole frontier in one query. A per-node query would be the N+1 pattern
`CLAUDE.md` Section 10.3 forbids, and traversal is the hottest path in the phase.

**Schema notes**

- Primary key `(snapshot_id, relation_id)`.
- `FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id) ON DELETE CASCADE`
  so `prune` and `rollback` need no change.
- Indexes on `(snapshot_id, source_symbol_id, kind)` and
  `(snapshot_id, target_symbol_id, kind)` — the two traversal directions, both
  measured in P3-06 with `EXPLAIN QUERY PLAN`.
- `resolution`, `derivation` stored as text; `candidate_count` integer.

**Steps**

- [ ] **Step 1: Write the failing store tests** — round-trip, `outgoing`/
  `incoming` filtering by kind, batch expansion returning edges for several
  source IDs in one call, cascade on snapshot deletion, `dangling_endpoints`
  finding a relation whose target symbol is absent.
- [ ] **Step 2: Run and confirm failure.**
- [ ] **Step 3: Implement** the domain module, `relation_id`, migration `0005`,
  and `RelationStore`.
- [ ] **Step 4: Assert both indexes are used** by `EXPLAIN QUERY PLAN` in a test,
  not by inspection.
- [ ] **Step 5: Run the gate** and append the handoff.

**Acceptance**

- Relations round-trip with every field intact, including `resolution` and
  `candidate_count`.
- Deleting a snapshot removes its relations by cascade.
- Both traversal directions use an index, proven by a query-plan assertion.

---

## P3-02 — Python Reference Extraction

**Files**

- Create: `src/codeatlas/extraction/__init__.py`
- Create: `src/codeatlas/extraction/python_relations.py`
- Modify: `src/codeatlas/parsing/registry.py` (`ParseResult.references`)
- Modify: `src/codeatlas/parsing/python_parser.py`
- Create: `tests/unit/test_python_relations.py`

**Behavior**

Extraction walks the `ast` module that `PythonParser` already builds — no second
parse — and emits references only for what the syntax states outright:

| Python syntax | Reference |
| --- | --- |
| `import a.b` / `from a.b import c` | `IMPORTS`, `module_hint="a.b"`, `target_hint="c"` |
| `class C(Base)` | `INHERITS`, `target_hint="Base"` |
| `f(...)` where `f` is a bare name | `CALLS`, `target_hint="f"` |
| `obj.method(...)` | `CALLS`, `target_hint="method"`, recorded with the receiver text in `module_hint` |
| `self.method(...)` | `CALLS`, `target_hint="<enclosing class>.method"` — the receiver type is known |
| `x: T` / `-> T` | `REFERENCES`, `target_hint="T"` |
| `__all__ = [...]` | `EXPORTS` per literal string entry |
| nesting | `CONTAINS` |

`self.method(...)` is the one case where a receiver's type is known without
inference, because `self` is bound by the enclosing class. Every other attribute
call carries the receiver as a hint and lets resolution decide; it does not
assume the receiver's type.

Not emitted: calls through a variable, `getattr`, dynamic import, star-import
targets, comprehension-scoped shadowing, or anything requiring type inference.
Each unemitted category is counted and surfaced as a diagnostic so the gap is
visible rather than silent.

**Steps**

- [ ] **Step 1: Write failing extraction tests** against the `python_app`
  fixture, asserting the exact reference set for `service.py` including
  `PaymentService.capture` → `claim` and `service` → `idempotency`, and
  asserting that a call through a local variable produces **no** reference.
- [ ] **Step 2: Run and confirm failure.**
- [ ] **Step 3: Implement** the extractor and thread `references` through
  `ParseResult`.
- [ ] **Step 4: Add a malformed-file test** — a file `ast` rejects yields
  recovered symbols and zero references, never a partial reference set from a
  broken tree.
- [ ] **Step 5: Run the gate** and append the handoff.

**Acceptance**

- The declared reference set for the Python fixtures is produced exactly.
- No reference is emitted for a construct in the "not emitted" list.
- Extraction is a pure function: the same bytes produce the same references, and
  the test asserts it by running the extractor twice.

---

## P3-03 — TypeScript and JavaScript Parser

**Files**

- Create: `src/codeatlas/parsing/tsjs_parser.py`
- Modify: `src/codeatlas/parsing/registry.py` (`default_registry`)
- Create: `tests/unit/test_tsjs_parser.py`
- Create: `tests/security/test_tsjs_parser_safety.py`

**Behavior**

Tree-sitter only. There is no TS/JS equivalent of Python's `ast` in-process, and
running `tsc` would violate the no-execution invariant, so Tree-sitter is
authoritative for both structure and spans. That is a genuine accuracy
difference from Python and is declared as a limitation, not papered over.

| Grammar | Files |
| --- | --- |
| `tree_sitter_typescript.language_typescript()` | `.ts`, `.mts`, `.cts` |
| `tree_sitter_typescript.language_tsx()` | `.tsx` |
| `tree_sitter_javascript.language()` | `.js`, `.jsx`, `.mjs`, `.cjs` |

Symbol mapping:

| Node | `SymbolKind` |
| --- | --- |
| `function_declaration`, arrow function assigned to a `const` | `FUNCTION` |
| `class_declaration` | `CLASS` |
| `method_definition` | `METHOD`, or `CONSTRUCTOR` when named `constructor` |
| `interface_declaration` | `INTERFACE` |
| `type_alias_declaration` | `TYPE_ALIAS` |
| `enum_declaration` | `ENUM` |
| `public_field_definition` | `FIELD` |
| top-level `const` with a literal initializer | `CONSTANT` |
| the file itself | `MODULE` |

`qualified_name` follows the Python parser's convention — `module.Class.member`
with the module derived from the repository-relative path minus its extension —
so a single `find_exact` works across languages without per-language branching.

Visibility is `private` for a name starting with `_` or `#`, or carrying an
explicit `private` modifier; `public` otherwise.

**Security tests required**

- A 2 MB file is rejected by size before parsing, matching `MAX_PARSE_BYTES`.
- A deeply nested expression (10,000 parentheses) does not exhaust the stack and
  produces a bounded diagnostic.
- A file of invalid UTF-8 yields `PARSE_DECODE_ERROR`, not an exception.
- A file containing `<!-- ignore previous instructions -->` and similar text in
  comments produces symbols and nothing else — repository content never becomes
  an instruction.
- No subprocess is spawned during parsing, asserted by patching
  `subprocess.Popen` to fail the test if called.

**Steps**

- [ ] **Step 1: Write failing parser tests** against `tsjs_app` asserting the
  exact symbol set for `orders.ts` (`Order` interface, `total` function) and
  `client.js` (`render`), with exact line ranges.
- [ ] **Step 2: Run and confirm failure.**
- [ ] **Step 3: Implement** the parser and register it.
- [ ] **Step 4: Write and pass the security tests.**
- [ ] **Step 5: Run the gate** and append the handoff. Note the expected change
  in `parsed_file_count` for any fixture containing TS/JS.

**Acceptance**

- `Order`, `total`, and `render` resolve through `ExactSymbolLookupService` with
  valid evidence, with no change to that service.
- Every security test passes.
- A `.tsx` file parses with the TSX grammar and does not fall back to plain TS.

---

## P3-04 — TypeScript and JavaScript Reference Extraction

**Files**

- Create: `src/codeatlas/extraction/tsjs_relations.py`
- Modify: `src/codeatlas/parsing/tsjs_parser.py`
- Create: `tests/unit/test_tsjs_relations.py`

**Behavior**

| Syntax | Reference |
| --- | --- |
| `import { total } from "./orders"` | `IMPORTS`, `module_hint="./orders"`, `target_hint="total"` |
| `import Default from "x"` | `IMPORTS`, `target_hint="default"` |
| `export function f` / `export const x` / `export { a, b }` | `EXPORTS` |
| `export default` | `EXPORTS`, `target_hint="default"` |
| `class C extends B` | `INHERITS` |
| `class C implements I` | `IMPLEMENTS` |
| `f(...)` bare identifier | `CALLS` |
| `obj.m(...)` | `CALLS` with the receiver as `module_hint` |
| `this.m(...)` | `CALLS`, `target_hint="<enclosing class>.m"` |
| `x: T`, `function f(): T`, `new T()` | `REFERENCES` |

Module specifier resolution rules, applied in P3-05 but declared here because the
extractor must record enough to make them possible:

- `./x` and `../x` resolve relative to the source file's directory.
- Extensions are tried in order `.ts`, `.tsx`, `.d.ts`, `.js`, `.jsx`, `.mjs`,
  `.cjs`, then `x/index.*`.
- A bare specifier (`react`, `@scope/pkg`) is `EXTERNAL`. No `node_modules`
  lookup ever happens.
- `tsconfig.json` `paths` aliases are **not** honored; a specifier matching none
  of the above is `UNRESOLVED` with a warning naming the limitation.
- Comparison is case-sensitive on normalized relative paths. On a
  case-insensitive Windows filesystem a case-only mismatch stays `UNRESOLVED`
  with a warning, because silently matching would make the same repository
  resolve differently on different platforms.

**Steps**

- [ ] **Step 1: Write failing tests** asserting `client.js` imports `total` from
  `./orders`, `render` calls `total`, `orders.ts` exports `Order` and `total`,
  and `total` references `Order` — the four edges the corpus declares for
  `tsjs_app`.
- [ ] **Step 2: Run and confirm failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Add a Windows-path test** for a case-only specifier mismatch.
- [ ] **Step 5: Run the gate** and append the handoff.

**Acceptance**

- Every relation the corpus declares for `tsjs_app` is extracted as a reference.
- A bare specifier is `EXTERNAL`, not `UNRESOLVED`, and neither reads
  `node_modules`.
- The case-only mismatch test passes on Windows.

---

## P3-05 — Snapshot Resolution and Indexing Integration

**Files**

- Create: `src/codeatlas/extraction/resolution.py`
- Modify: `src/codeatlas/application/indexing.py`
- Modify: `src/codeatlas/domain/ids.py` (`snapshot_id` takes `resolver_version`)
- Create: `src/codeatlas/storage/sqlite/migrations/0006_phase3_evidence.sql`
  (adds `snapshots.resolver_version`; the `evidence` table lands in P3-08 in the
  same migration file, written once here)
- Create: `tests/integration/test_resolution.py`
- Modify: `tests/integration/test_incremental_indexing.py`

**Interfaces produced**

```python
# extraction/resolution.py
RESOLVER_VERSION: str = "1.0.0"

@dataclass(frozen=True)
class ResolutionStats:
    references: int
    resolved: int
    external: int
    unresolved: int
    ambiguous: int

class SnapshotResolver:
    def resolve(self, files: Sequence[FileRecord], symbols: Sequence[SymbolRecord],
                references: Sequence[SymbolReference]
                ) -> tuple[tuple[RelationRecord, ...], ResolutionStats]: ...
```

**Resolution order** — first match wins, and the order is the trust ordering:

1. Same file, same enclosing scope.
2. Same file, module scope.
3. Imported into this file: follow the file's own `IMPORTS` references to a
   target file, then look up the name there.
4. Same package (sibling module) by qualified name.
5. Repository-wide unique match by name.
6. Otherwise `UNRESOLVED`, or `AMBIGUOUS` when steps 1–5 produced more than one
   candidate at the same level.

Step 5 is the only one that can reach across the repository on a bare name, and
it applies **only when the name is globally unique**. A non-unique bare name is
`AMBIGUOUS` and becomes `MAY_CALL`, never `CALLS`.

`TESTS` edges are derived after resolution: for each symbol in a `TEST_CODE`
file, if it both imports and calls a target symbol, emit `TESTS` from the test
symbol to the target. Both conditions are required — a test that merely mentions
a name is not evidence that it tests it.

`DOCUMENTS` edges are derived from `DOCUMENT_SECTION` chunks: a section whose
text contains an identifier that resolves to exactly one symbol yields a
`low_confidence_heuristic` edge. This is advisory discovery, and P3-07 must
never let it support a claim on its own.

**Indexing integration**

`_stage` gains a `resolving` stage between chunking and indexing:

- reused files contribute their copied references;
- reparsed files contribute freshly extracted ones;
- resolution runs over the union, for the whole snapshot, every run;
- `ReuseStats` gains `references_reused`, `references_extracted`,
  `relations_resolved`.

Validation gains the three checks named in the architecture decisions.

**Steps**

- [ ] **Step 1: Write the failing cross-file test** — `render` → `total` resolves
  across `client.js` and `orders.ts`, and the resolved `target_symbol_id` is
  `total`'s actual symbol ID in that snapshot.
- [ ] **Step 2: Write the failing staleness test** — index, delete `total` from
  `orders.ts`, re-index; assert the `render` → `total` edge is now `UNRESOLVED`
  and that **no** relation in the snapshot has a `target_symbol_id` absent from
  the snapshot's symbols. This is gate condition 7.
- [ ] **Step 3: Write the failing reuse test** — edit one method body; assert
  `references_reused > 0`, `references_extracted` covers only the edited file,
  and `relations_resolved` equals the whole snapshot's reference count. This is
  gate condition 6.
- [ ] **Step 4: Run and confirm failure.**
- [ ] **Step 5: Implement** the resolver, then the indexing integration.
- [ ] **Step 6: Run the gate** and append the handoff. Snapshot IDs change again
  because `resolver_version` joins the identity inputs.

**Acceptance**

- Cross-file and cross-language edges resolve to real symbol IDs.
- A removed target leaves an `UNRESOLVED` edge and never a dangling one.
- Reuse and full re-resolution both hold in the same run, proven by counters.
- Ambiguous names produce `MAY_CALL`, never `CALLS`.

---

## P3-06 — Bounded Graph Traversal

**Files**

- Create: `src/codeatlas/retrieval/graph.py`
- Create: `tests/unit/test_graph_traversal.py`
- Create: `tests/integration/test_graph_bounds.py`

**Interfaces produced**

```python
# retrieval/graph.py
@dataclass(frozen=True)
class TraversalLimits:
    max_depth: int = 2
    max_visited: int = 200
    max_edges: int = 50
    max_paths: int = 10

@dataclass(frozen=True)
class TraversalResult:
    edges: tuple[RelationRecord, ...]
    paths: tuple[tuple[RelationRecord, ...], ...]
    visited_count: int
    max_depth_reached: int
    truncated_by: tuple[str, ...]   # "depth" | "visited" | "edges" | "paths"

class BoundedGraphTraversal:
    def expand(self, snapshot_id: str, roots: Sequence[str],
               direction: Literal["outgoing", "incoming"],
               kinds: Sequence[RelationKind] | None = None,
               limits: TraversalLimits | None = None) -> TraversalResult: ...
```

**Behavior**

- Breadth-first, one batched store query per depth level — never one per node.
- A visited set makes cycles terminate; a self-referential module is a normal
  case, not an error.
- Ordering is deterministic: `(depth, file path, start line, kind)`.
- Every bound that is hit is named in `truncated_by`. A caller that reports a
  complete answer while `truncated_by` is non-empty is a bug the contract tests
  in P3-10 must catch.
- Limits above the declared maxima are rejected with `InvalidRequestError`, not
  silently clamped — a caller asking for depth 50 should be told no.

**Steps**

- [ ] **Step 1: Write failing tests** for depth limiting, cycle termination,
  visited-count reporting, deterministic ordering across repeated runs, and each
  of the four truncation reasons independently.
- [ ] **Step 2: Write a failing query-count test** asserting the number of store
  queries is proportional to depth, not to node count. Instrument by counting
  `RelationStore.outgoing` calls.
- [ ] **Step 3: Run and confirm failure.**
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Run the gate** and append the handoff.

**Acceptance**

- Traversal terminates on a cyclic graph.
- Every bound reports its truncation.
- Query count scales with depth, not node count.
- Repeated traversal of the same snapshot returns byte-identical results.

---

## P3-07 — Graph Query Application Services

**Files**

- Create: `src/codeatlas/application/graph_queries.py`
- Modify: `src/codeatlas/application/evidence.py` (relation-step evidence)
- Modify: `src/codeatlas/contracts.py` (`RelationStep`, `RelationPath`)
- Modify: `src/codeatlas/application/container.py`
- Create: `tests/integration/test_graph_queries.py`
- Create: `tests/contract/test_relation_contract.py`

**Interfaces produced**

```python
# application/graph_queries.py
@dataclass(frozen=True)
class GraphQueryRequest:
    repository_id: str
    symbol: str
    request_id: str
    max_depth: int = 2
    limits: TraversalLimits | None = None

class GraphQueryService:
    def callers(self, request: GraphQueryRequest) -> QueryResponse: ...
    def callees(self, request: GraphQueryRequest) -> QueryResponse: ...
    def dependencies(self, request: GraphQueryRequest) -> QueryResponse: ...
    def dependents(self, request: GraphQueryRequest) -> QueryResponse: ...
    def exports(self, request: GraphQueryRequest) -> QueryResponse: ...
    def related_tests(self, request: GraphQueryRequest) -> QueryResponse: ...
    def related_documents(self, request: GraphQueryRequest) -> QueryResponse: ...
    def trace(self, request: GraphQueryRequest) -> QueryResponse: ...
```

**Behavior**

Each method resolves the root symbol exactly first — reusing
`ExactSymbolLookupService`, not reimplementing it — then traverses, then emits a
`QueryResponse` through the shared `EvidenceBuilder`.

Trust rules, each with a test:

- A claim's derivation is the **weakest** derivation among the edges supporting
  it. One `MAY_CALL` in a path makes the whole path heuristic.
- A `DOCUMENTS` edge alone never supports a claim; it may only appear as
  supplementary evidence beside a stronger edge.
- An ambiguous root symbol abstains with a warning listing the candidates. It
  does not pick the first one.
- Truncation from `TraversalResult.truncated_by` becomes both a warning and a
  limitation on the response, so an incomplete answer says so.
- A root with no relations abstains explicitly — "no callers found in this
  snapshot" — which is a different statement from "not analyzed", and the
  summary must distinguish them.

**Steps**

- [ ] **Step 1: Write the failing corpus-aligned tests** — `q005` (`capture`
  calls `claim`), `q016` (`render` calls `total`), `q017` (`orders` exports),
  `q007` (test relates to `capture`), `q010`/`q015` (imports).
- [ ] **Step 2: Write the failing trust tests** — weakest-derivation
  propagation, `DOCUMENTS`-only abstention, ambiguous-root abstention, and
  truncation surfacing.
- [ ] **Step 3: Run and confirm failure.**
- [ ] **Step 4: Add `RelationStep`/`RelationPath` to `contracts.py`** and the
  optional `relation_paths` field to `QueryResponse`.
- [ ] **Step 5: Implement** the service and wire it into `ApplicationServices`.
- [ ] **Step 6: Run the gate** and append the handoff.

**Acceptance**

- Every relation case the corpus declares for the supported fixtures is answered
  with the declared relation path.
- Every claim's derivation is no stronger than its weakest supporting edge.
- Truncated and empty results are both explicit and distinguishable.

---

## P3-08 — Complete REST and CLI Adapters

**Files**

- Create: `src/codeatlas/api/routers/entities.py`
- Create: `src/codeatlas/api/routers/graph.py`
- Modify: `src/codeatlas/api/app.py`, `src/codeatlas/api/errors.py`
- Modify: `src/codeatlas/storage/sqlite/stores.py` (add `EvidenceStore`)
- Modify: `src/codeatlas/application/evidence.py` (persist on build)
- Modify: `src/codeatlas/cli/main.py`
- Modify: `src/codeatlas/domain/errors.py` (three `*_NOT_FOUND` codes)
- Modify: `scripts/export_contract_schema.py`, `docs/api/contract-v1.schema.json`
- Modify: `tests/contract/test_rest_api.py`, `tests/end_to_end/test_cli_workflow.py`

**Endpoints completed** (from `CLAUDE.md` Sections 12.1 and 12.3)

```text
GET  /v1/evidence/{evidence_id}
GET  /v1/files/{file_id}
GET  /v1/symbols/{symbol_id}
GET  /v1/symbols/{symbol_id}/relations?kind=&direction=&depth=
GET  /v1/repositories/{repository_id}/files
GET  /v1/repositories/{repository_id}/diagnostics
GET  /v1/repositories/{repository_id}/snapshots/active
POST /v1/query
```

`POST /v1/query` accepts a typed `mode` — `symbol`, `text`, `files`, `callers`,
`callees`, `dependencies`, `exports`, `tests`, `documents`, `trace` — and
dispatches to the matching application service. It is one endpoint over the
services that already exist, not a new pipeline. An unknown mode is
`UNSUPPORTED_QUERY_MODE`, which already exists and already maps correctly.

`GET /v1/repositories/{id}/semantic-status` returns a Phase 7 placeholder with
`semantic_coverage: 0.0` and an explicit "not enabled" state. It reports the
truth that no semantic index exists; it does not pretend one is pending.

**CLI commands completed**

```powershell
codeatlas callers <repository_id> <symbol> [--depth N] [--json]
codeatlas callees <repository_id> <symbol> [--depth N] [--json]
codeatlas deps <repository_id> <symbol> [--direction in|out] [--json]
codeatlas exports <repository_id> <module> [--json]
codeatlas tests <repository_id> <symbol> [--json]
codeatlas trace <repository_id> <symbol> [--depth N] [--json]
codeatlas evidence <evidence_id> [--json]
codeatlas files <repository_id> [--json]
codeatlas diagnostics <repository_id> [--json]
```

Exit codes are unchanged. A truncated result exits 4 (partial), not 0 — a script
must be able to tell a bounded answer from a complete one.

**Steps**

- [ ] **Step 1: Write the failing REST contract tests** for each endpoint,
  including 404 shapes for all three `*_NOT_FOUND` codes and the error envelope.
- [ ] **Step 2: Write the failing evidence-addressing test** — run a query, take
  an `evidence_id` from the response, fetch it, and get the same file, lines,
  and hash back. Then edit the file and assert the fetch reports drift rather
  than returning stale content.
- [ ] **Step 3: Run and confirm failure.**
- [ ] **Step 4: Implement** `EvidenceStore`, migration `0006`'s `evidence`
  table, the routers, and the CLI commands.
- [ ] **Step 5: Regenerate the contract schema** and assert the export is
  current in a test, so a drifted schema fails the build rather than shipping.
- [ ] **Step 6: Run the gate** and append the handoff.

**Acceptance**

- Every endpoint in `CLAUDE.md` Sections 12.1 and 12.3 exists or has a recorded
  reason for deferral.
- A fetched evidence ID returns identical content to the query that produced it,
  and reports drift when the file changes.
- The exported schema matches the models, enforced by test.
- The API still binds to loopback only, re-asserted by the existing security
  test.

---

## P3-09 — Initial Versioned MCP Adapter

**Files**

- Create: `src/codeatlas/mcp/__init__.py`, `server.py`, `tools.py`
- Modify: `pyproject.toml` (`codeatlas-mcp` console script)
- Create: `tests/contract/test_mcp_tools.py`
- Create: `tests/security/test_mcp_bounds.py`

**Tools exposed** (from `CLAUDE.md` Section 13, minus change analysis)

| Tool | Wraps |
| --- | --- |
| `register_repository`, `list_repositories`, `get_repository` | `RegisterRepositoryService` |
| `get_status`, `get_diagnostics` | `RepositoryStatusService` |
| `resolve_symbol`, `resolve_file` | `ExactSymbolLookupService` |
| `search_files`, `search_symbols`, `search_text` | `LexicalSearchService` |
| `get_callers`, `get_callees`, `get_dependencies`, `get_exports`, `get_related_tests`, `get_related_documents`, `trace_flow` | `GraphQueryService` |
| `get_evidence` | `EvidenceStore` |

`analyze_change` is **not** registered in Phase 3. A tool that exists and returns
"unimplemented" is worse than an absent tool, because an agent will call it.

**Requirements**

- Stdio transport only. A test asserts no socket is opened.
- Every tool input is a Pydantic model with explicit bounds — max query length,
  max results, max depth — validated before reaching a service.
- Every tool output carries `contract_version` and serializes the same
  `QueryResponse` the REST adapter returns. The P3-10 contract suite asserts
  byte-identical evidence across all three adapters.
- Errors return the `ErrorEnvelope` shape, never a stack trace.
- A tool returns warnings and unsupported states explicitly rather than omitting
  them, as Section 13 requires.
- Tool schemas carry a version so a client can detect a change.

**Steps**

- [ ] **Step 1: Write the failing tool-contract tests** — every tool is
  registered, has a schema, and rejects out-of-bounds input.
- [ ] **Step 2: Write the failing security tests** — no socket, no repository
  content in server logs, bounded output size, and repository text treated as
  data rather than instruction.
- [ ] **Step 3: Run and confirm failure.**
- [ ] **Step 4: Implement** the server and tools over `ApplicationServices`.
- [ ] **Step 5: Run the gate** and append the handoff.

**Acceptance**

- Every listed tool works against a real indexed fixture.
- No tool duplicates repository logic; each one adapts a service.
- Out-of-bounds input is rejected with the standard error envelope.
- Nothing binds to a network socket.

---

## P3-10 — Cross-Adapter Contract Suite, Baseline, Docs, Phase Gate

**Files**

- Create: `tests/contract/test_cross_adapter_equivalence.py`
- Create: `scripts/run_phase3_baseline.py`, `scripts/check_phase3.ps1`
- Create: `docs/evaluation/baseline-phase-3.json`, `.md`,
  `docs/evaluation/phase-3-baseline-environment.md`
- Create: `docs/operations/relations-and-graph.md`
- Modify: `src/codeatlas/evaluation/engine_adapter.py`
- Modify: `docs/security/threat-model.md`, `README.md`
- Modify: `docs/plans/PLAN.md`, this plan

**The cross-adapter suite** is the phase's defining test. For a table of
(fixture, symbol, query mode), it runs the same question through the application
service, REST, the CLI, and MCP, and asserts that the evidence lists are
identical — same IDs, same paths, same line ranges, same derivations, same
order. Not "equivalent"; identical. Any adapter that reformats, re-ranks, or
re-derives shows up here.

**Evaluation adapter** gains the graph intents: `CALLERS`, `DEPENDENCIES`,
`EXPORTS`, `RELATED_TESTS`, `TRACE_FLOW`, and the `tsjs_app` fixture. Cases still
outside scope keep abstaining. Report the honest deltas against the Phase 2
baseline, including any metric that regresses, with a per-case explanation as
Phase 2 did.

**Gate targets** (`CLAUDE.md` Section 19.3) to measure and report:

| Metric | Target | Measured against |
| --- | ---: | --- |
| Valid file-and-line evidence | 100% | both metrics, reported side by side |
| Active-snapshot leakage | 0 | — |
| Exact symbol lookup on fixtures | ≥ 98% | symbol identity, not line range |
| Direct dependency impact recall | ≥ 90% | `containing_evidence_rate` |
| Primary evidence Recall@10 | ≥ 90% | `containing_evidence_rate` |
| Unsupported factual claim rate | < 2% | — |
| Contract-valid REST/MCP responses | 100% | — |

Per ADR-0003, every gate claim names which evidence metric it used, and
`exact_evidence_rate` is reported beside `containing_evidence_rate` in all cases
so the granularity gap stays visible.

A target that is missed is reported as missed, with the measurement and the
reason. Do not adjust the corpus to meet a number.

**Steps**

- [ ] **Step 1: Write the cross-adapter equivalence suite** and make it pass.
- [ ] **Step 2: Extend the evaluation adapter** to the graph intents and
  `tsjs_app`.
- [ ] **Step 3: Generate the Phase 3 baseline** with timings excluded, and
  record artifact hashes and the environment.
- [ ] **Step 4: Write `check_phase3.ps1`** covering tests, Ruff, MyPy, dataset
  validity, schema-export currency, and the Phase 3 baseline.
- [ ] **Step 5: Write `docs/operations/relations-and-graph.md`** — the relation
  table, derivation rules, resolution order, traversal bounds, and an explicit
  list of what Phase 3 still does not do.
- [ ] **Step 6: Update the threat model** for TS/JS parsing and MCP.
- [ ] **Step 7: Run the full gate**, record commands, exit codes, and results,
  and set Phase 3 to `awaiting_user_approval`.

**Acceptance**

- All four adapters return identical evidence for the same question.
- The baseline is reproducible and its deltas are explained case by case.
- Every gate metric is measured and reported, including any that misses.
- `check_phase3.ps1` exits 0.

---

## Verification Commands

```powershell
uv run pytest -q
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
uv run python scripts/run_phase3_baseline.py --dataset tests/evaluation/cases --check
powershell -ExecutionPolicy Bypass -File scripts/check_phase3.ps1
```

## Task Status Transitions

| Task | Status | Recorded |
| --- | --- | --- |
| P3-SETUP | `pending` | awaiting plan approval |
| P3-01 … P3-10 | `pending` | awaiting plan approval |
