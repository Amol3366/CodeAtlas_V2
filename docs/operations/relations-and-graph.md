# Relations and the Graph

How CodeAtlas decides what a name means, what it will and will not claim, and
how to read a graph answer.

## The two stages

Relation derivation is deliberately split in two.

```text
parse file ──▶ SymbolReference (source symbol, target *hint*, kind, line range)
                        │        pure function of one file  → reusable
                        ▼
              resolve across snapshot ──▶ RelationRecord (target_symbol_id or NULL)
                                          needs every file  → always recomputed
```

A **reference** is what one file said: `total`, `"./orders"`, `Order`. Producing
one reads only that file's bytes, so an unchanged file's references are copied
into the next snapshot untouched.

A **relation** is what that reference turned out to mean in a particular
snapshot. Resolution runs over the whole snapshot on every index run, and never
reuses a previous run's answer.

The asymmetry is the point. It is why an edge cannot outlive the symbol it points
at: nothing is carried forward that could go stale. `CLAUDE.md` Section 9's
"necessary reverse relations" requirement holds by construction rather than by
bookkeeping that can drift.

## Resolution order

First match wins, and the order is a *trust* ordering:

1. Same file, same enclosing scope.
2. Same file, module scope.
3. Imported into this file, followed to the target file.
4. Same package — a sibling module — by name.
5. Repository-wide, **only when the name is globally unique**.
6. Otherwise unresolved, or ambiguous when a level produced several candidates.

Step 5 is the only one that reaches across the repository on a bare name. A
non-unique bare name never becomes a `CALLS` edge.

## What each relation means

| Kind | Derivation | Emitted when |
| --- | --- | --- |
| `CONTAINS` | `deterministic` | structural nesting |
| `IMPORTS` | `static_resolved` | the specifier resolves to a repository file |
| `IMPORTS` | `deterministic` | the target is outside the repository (`target_symbol_id` is NULL, resolution is `external`) |
| `EXPORTS` | `deterministic` | `export` or `__all__` |
| `INHERITS` / `IMPLEMENTS` | `static_resolved` | the base resolves to exactly one candidate |
| `CALLS` | `static_resolved` | the callee name resolves to exactly one candidate |
| `MAY_CALL` | `high_confidence_heuristic` | the name resolves to more than one candidate |
| `REFERENCES` | `static_resolved` | a type reference resolves to one candidate |
| `TESTS` | `high_confidence_heuristic` | a `TEST_CODE` symbol both imports **and** calls the target |
| `DOCUMENTS` | `low_confidence_heuristic` | a document section names an existing symbol |

`TESTS` requires both an import and a call. A test that merely mentions a name is
not evidence that it tests it.

## What is deliberately not emitted

A call through a variable, an attribute of unknown type, a computed member, or
`getattr` produces **no edge at all**. Each unemitted category is counted and
surfaced as a parse diagnostic (`REFERENCE_DYNAMIC_CALL`,
`REFERENCE_DYNAMIC_ATTRIBUTE`, `REFERENCE_DYNAMIC_IMPORT`,
`REFERENCE_STAR_IMPORT`) so the gap is measurable rather than invisible.

Also not represented: `tsconfig.json` `paths` aliases, monorepo workspace
resolution, dynamic `import()`, `require()` with a computed specifier, re-export
chains beyond one hop, and all type inference.

## Reading a graph answer

Four rules govern every answer from `GraphQueryService`:

- A claim's derivation is the **weakest** derivation among its supporting edges.
  One `MAY_CALL` makes the whole path heuristic.
- A `DOCUMENTS` edge never supports a claim on its own. It is advisory discovery
  and travels only as supplementary evidence.
- An ambiguous root **abstains** and lists the candidates rather than picking one.
- Truncation appears as both a `GRAPH_TRUNCATED_*` warning and a limitation, so
  an incomplete answer says that it is incomplete.

"No callers found" and "callers were not analyzed" are different statements. The
summaries keep them apart, and the CLI exits 4 (partial) for both so a script can
branch on it.

## Traversal bounds

| Bound | Default | Maximum |
| --- | --- | --- |
| Depth | 2 | 5 |
| Visited nodes | 200 | 1,000 |
| Returned edges | 50 | 200 |
| Returned paths | 10 | 25 |

A request above a maximum is **refused**, not clamped: a caller asking for depth
50 has misunderstood something, and quietly giving them depth 5 would hide that.

Traversal is breadth-first with one batched store query per depth level — never
one per node — and is deterministically ordered by file path, start line, and
kind, so the same snapshot always produces the same answer.

## TypeScript and JavaScript accuracy

Python gets a second opinion from `ast`. TypeScript has no in-process
equivalent, and running `tsc` would execute repository tooling, which is
forbidden. Tree-sitter is therefore authoritative for TS/JS structure and spans,
and what it cannot see — inferred types, resolved module graphs, declaration
merging — CodeAtlas does not claim to know.

Module specifiers are compared **case-sensitively** on normalized relative paths.
On a case-insensitive Windows filesystem a case-only mismatch stays unresolved,
because silently matching would make the same repository resolve differently on
different platforms.

## Adapters

REST, CLI, and MCP call the same application services and return the same
contract models. `tests/contract/test_cross_adapter.py` compares all three
answers field by field for the same question, so an adapter that starts
post-processing a result fails the build.

MCP binds **stdio only**. No socket is opened and no port is bound.
