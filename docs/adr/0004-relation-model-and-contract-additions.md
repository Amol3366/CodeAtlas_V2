# ADR-0004: Relation Model, Two-Stage Resolution, and Additive Contract Fields

- Status: accepted
- Date: 2026-07-26
- Decision owners: user (Phase 3 plan approval), implementing agent (record)
- Supersedes: none
- Refines: ADR-0001, ADR-0002

## Context

Phase 3 introduces the relation graph: who calls what, what imports what, what
inherits from what, which tests cover which symbol. Four things must be decided
before ten tasks depend on them, because each changes output shape and each is
far cheaper to fix now than after.

1. **How a relation is derived.** A call site names `capture`. Whether that is
   `PaymentService.capture`, `LedgerService.capture`, both, or something outside
   the repository is not knowable from the calling file alone.
2. **How relations survive incremental indexing.** `CLAUDE.md` Section 9
   requires that a changed file recalculate "necessary reverse relations". A
   design that reuses edges wholesale will eventually point at a symbol that no
   longer exists.
3. **How relations reach a client.** `CLAUDE.md` Section 11.1 fixes the response
   envelope at `contract_version` `"1.0"`, and Section 25 makes breaking that
   contract an approval-gated change.
4. **Whether TypeScript and JavaScript support needs separate approval.**
   Section 25 lists "new programming-language support" as approval-gated, while
   Section 20 already names TypeScript and JavaScript as Phase 3 deliverables.

## Decision

### 1. Extraction and resolution are two separate stages

```text
parse file ──▶ SymbolReference (source symbol, target *hint*, kind, line range)
                        │        pure function of one file  → reusable
                        ▼
              resolve across snapshot ──▶ RelationRecord (target_symbol_id or NULL)
                                          needs every file  → always recomputed
```

A `SymbolReference` records what the source file *said*: `total`, `"./orders"`,
`Order`. A `RelationRecord` records what that turned out to mean in this
snapshot. Extraction MUST be a pure function of one file's bytes; anything
requiring another file is resolution.

Resolution is recomputed for the whole snapshot on every index run. A reused
file's *references* are reused; its *resolved targets* are not.

### 2. Relation identity and storage

`relation_id` = `rel_` + `stable_hash(source_symbol_id, kind, target_hint,
start_line, part)`. Relations are snapshot-scoped rows, like chunks, and cascade
with snapshot deletion. A stable `relation_id` across snapshots for an unchanged
call site is what makes reuse observable and what will let Phase 4 say "this
edge is new".

`RESOLVER_VERSION` joins `PARSER_BUNDLE_VERSION`, `INDEX_VERSION`, and
`CHUNKER_VERSION` as a truth-bearing input to `snapshot_id`. Resolution logic
can change which edges exist without any parser changing, so it needs its own
invalidation handle.

`PARSER_BUNDLE_VERSION` moves to `"1.1.0"`, because parsers now emit references
and every previously derived symbol version is therefore stale.

### 3. Supported relations and their derivations

Only these are emitted in Phase 3. Anything else stays unimplemented rather than
approximated.

| Kind | Source | Derivation |
| --- | --- | --- |
| `CONTAINS` | structural nesting | `deterministic` |
| `IMPORTS` | import resolved to a repository file | `static_resolved` |
| `IMPORTS` | import whose target is outside the repository | `deterministic` (the statement is a fact; `target_symbol_id` is NULL) |
| `EXPORTS` | `export` / `__all__` | `deterministic` |
| `INHERITS` | base class resolved to one candidate | `static_resolved` |
| `IMPLEMENTS` | TS `implements` resolved to one candidate | `static_resolved` |
| `CALLS` | callee name resolving to exactly one candidate | `static_resolved` |
| `MAY_CALL` | callee name resolving to more than one candidate | `high_confidence_heuristic` |
| `REFERENCES` | type reference resolved to one candidate | `static_resolved` |
| `TESTS` | `TEST_CODE` symbol that imports **and** calls the target | `high_confidence_heuristic` |
| `DOCUMENTS` | document section naming an existing symbol | `low_confidence_heuristic` |

A name resolving to more than one candidate MUST NOT become a `CALLS` edge; it
becomes `MAY_CALL` with every candidate recorded and none promoted. A call
through a variable, an attribute of unknown type, a computed member, or
`getattr` is **not emitted at all**. Absence is reported as a limitation on the
answer; it is never filled with a guess.

A relation MUST NOT be emitted without a source line range that maps exactly
onto real source. An edge with no citable site is not evidence.

### 4. Contract additions are additive and optional

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

`contract_version` stays `"1.0"`. Every step cites evidence, so a path is
auditable edge by edge rather than as an opaque conclusion.

Three error codes are added — `EVIDENCE_NOT_FOUND`, `FILE_NOT_FOUND`,
`SYMBOL_NOT_FOUND` — each HTTP 404 and CLI exit 3. Ambiguity and absence of
relations remain abstentions with warnings, not errors.

### 5. TypeScript and JavaScript need no separate approval

`CLAUDE.md` Section 5 names Python, TypeScript, and JavaScript as the initial
supported product profile, and Section 20 assigns TS/JS parsing to Phase 3.
Section 25's "new programming-language support" gate is therefore read as
applying to languages **outside** the declared profile. Adding a fourth language
would require approval; completing the declared three does not. This reading is
recorded here so the exemption is explicit rather than assumed.

## Alternatives

- **Single-stage extraction that resolves during parsing.** Simpler and one pass
  fewer. Rejected because it makes extraction impure — a parser would need every
  other file — which destroys per-file reuse and makes a stale cross-file edge
  possible whenever a target moves. The two-stage split makes that class of bug
  structurally impossible rather than merely unlikely.
- **Resolve incrementally, updating only edges touching changed files.** Would
  be faster. Rejected because it satisfies Section 9's "necessary reverse
  relations" requirement by bookkeeping that can drift, and the bookkeeping is
  precisely the part that is hard to test. Full re-resolution is O(references)
  over an in-memory name index built once per snapshot, not O(references ×
  symbols), so the cost is bounded and measured rather than assumed.
- **Emitting a best-guess `CALLS` edge for an ambiguous name.** Rejected because
  it would let a heuristic masquerade as `static_resolved` evidence, violating
  `CLAUDE.md` Section 4.3. `MAY_CALL` keeps the finding available and honestly
  labeled.
- **A breaking `contract_version` bump to `"2.0"` for relation paths.** Rejected
  as unnecessary: an optional field with a default breaks no existing consumer,
  and Section 25 would require approval for the break.
- **Omitting relation paths from the response entirely** and exposing relations
  only through dedicated endpoints. Rejected because a trace-flow answer is not
  auditable unless the path travels with it.

## Consequences

- Every index run pays a full resolution pass. It is instrumented with counters
  so the cost is visible; if it becomes the dominant stage, that is a measured
  reason to revisit, not a guess.
- `RESOLVER_VERSION` and the `PARSER_BUNDLE_VERSION` bump both change
  `snapshot_id`, so every existing snapshot is superseded on first run after
  Phase 3. This is correct: the derived content genuinely differs.
- `SCHEMA_VERSION` moves 4 → 6 across migrations `0005` (relations) and `0006`
  (`snapshots.resolver_version` and the `evidence` table).
- `MAY_CALL` means some answers list several candidates. That is the honest
  output, and the UI must present it as such rather than silently taking the
  first.
- Unresolved and external references are stored as first-class rows. An import
  of `react` is a real fact about a file even though no repository symbol
  answers it.
- Deferred and declared as limitations rather than approximated: `tsconfig.json`
  `paths` aliases, monorepo workspace resolution, dynamic `import()`, `require()`
  with a computed specifier, re-export chains beyond one hop, decorator-driven
  routing, and all type inference.

## Security and Privacy

The TS/JS parser MUST NOT execute, import, transpile, type-check, or resolve
through a package manager: no `node`, no `tsc`, no `node_modules` resolution.
Parsing is tree-sitter over bytes, exactly as Python parsing is, preserving
`CLAUDE.md` Section 4.4's prohibition on executing repository code.

Import specifiers are untrusted strings from repository content. They are
resolved only through the existing `validate_relative_path` canonicalization and
must stay inside the approved repository root; a specifier that escapes is
recorded as `external` or `unresolved`, never followed.

The `evidence` table stores identifiers, a line range, a content hash, and a
derivation — **not the excerpt**. Fetching re-reads the file from disk and
re-verifies the hash, so a stored row can never outlive the content it
describes.

MCP binds to **stdio only**. No network listener and no new port, so
`CLAUDE.md` Section 18's loopback-by-default requirement is unaffected.

Adding `mcp` pulls a non-trivial transitive dependency set (including
`cryptography`, `pyjwt`, `python-multipart`, and `sse-starlette`). This enlarges
the supply-chain surface of a local-first product and is accepted because
Section 20 requires an MCP adapter in this phase; the additions are pinned in
`uv.lock`.

## Migration and Rollback

Forward: migrations `0005` and `0006` are additive and forward-only, consistent
with ADR-0002. Applied migrations `0001`–`0004` are not edited. Validation
before activation gains three checks — every relation's source symbol exists in
the snapshot, every resolved `target_symbol_id` exists in the snapshot, and no
relation cites a line outside its file's line count — so a snapshot carrying a
dangling edge cannot activate.

Verification: relation identity, store behavior, resolution counters, traversal
bounds, and cross-adapter contract equivalence each carry tests; the phase gate
requires them recorded with exit codes in the handoff log.

Rollback: as in ADR-0002, there is no schema downgrade. Reverting Phase 3 means
restoring the database from a pre-migration copy or deleting it and re-indexing.
Because `snapshot_id` changes with the new version constants, a re-index after
rollback rebuilds cleanly rather than colliding with Phase 3 rows. The contract
addition is optional, so a client written against Phase 3 continues to work
against a Phase 2 backend that simply never populates `relation_paths`.

## Approval

Approved by the user on 2026-07-26 as part of the Phase 3 execution plan
(`docs/plans/phases/phase-03-polyglot-graph-and-delivery-contracts.md`),
instructed as "start executing phase 3" after being shown the plan summary,
its planned migrations and version bumps, and the open items carried from the
Phase 2 gate. The scope approved is the Phase 3 plan as written, including the
decisions recorded above.
