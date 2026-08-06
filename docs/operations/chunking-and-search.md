# Chunking, Search, Rollback, and Retention

What Phase 2 added, and the rules a reader needs in order to trust its output.

## Chunks

A chunk is a bounded, citable region of a file, cut along the file's own
structure rather than at a fixed size.

| Role | What it covers |
| --- | --- |
| `file_summary` | One per file: path, language, classification, symbol names, line count. Deterministic metadata only — no prose, no model. |
| `symbol` | One class, function, method, constant, module, or document container. |
| `symbol_part` | A split of a symbol too large to carry whole. |
| `document_section` | A Markdown heading and the body beneath it. |
| `config_key` | One top-level JSON, YAML, or TOML key and its block. |

### Sizing

Phase 2 has no tokenizer, so characters are a declared proxy at roughly four
characters per token. Recalibrating these against a real tokenizer is a
`CHUNKER_VERSION` bump.

| Bound | Characters |
| --- | ---: |
| Target minimum | 1,200 |
| Target maximum | 4,800 |
| Hard maximum | 7,200 |
| Minimum useful | 320 |
| Overlap when splitting | 720 |

A symbol over the hard maximum splits at `ast` statement boundaries; a document
section splits at paragraph boundaries. Splits are always line-aligned, so every
part still maps exactly onto real source lines. Each part repeats the definition
it belongs to and carries `part_index`/`part_count`.

### Identity, and why unchanged work is reused

- `logical_chunk_id` = hash(repository, path, qualified name, role). Survives
  edits.
- `chunk_version_id` = hash(logical chunk, content hash, parser version, chunker
  version). Changes when content or logic changes.

A container — a module or a class — is hashed over its **outline**: its
definition header and the ordered names of its members. Editing a method body
therefore changes that method's chunk and nothing else. Adding or removing a
member changes the container and the file summary. That property is what makes
incremental reuse safe, and it is asserted by test rather than assumed.

## Search

Three services, all returning the same contract `QueryResponse` as exact lookup:

| Service | Finds |
| --- | --- |
| `search_text` | Text inside chunk retrieval text |
| `search_files` | File paths |
| `search_symbols` | Exact symbol first, lexical symbol names only as fallback |

### Derivation labels

| Outcome | Evidence derivation | Claim derivation | Confidence |
| --- | --- | --- | ---: |
| Exact symbol resolution | `deterministic` | `static_resolved` | 0.99 |
| Lexical match | `high_confidence_heuristic` | `high_confidence_heuristic` | 0.7 |

Lexical search finds text, not verified meaning. The bytes really are at those
lines, but the judgment that they answer the question was made by a ranking
function — so the label says so. **An exact match is never displaced by a
lexical one.**

Current presentation behavior as of 2026-08-04: `LEXICAL_QUERY_RELAXED` means
the query was reduced to searchable literal terms instead of treated as a
structured code relation. It is a warning about retrieval strategy, not an
answer failure. `EVIDENCE_EXCERPT_TRUNCATED` means a cited excerpt was shortened
for display while the evidence id, file path, and line range remain the
authoritative reference.

### Query safety

User text never reaches FTS5 as syntax. It is NFC-normalized, case-folded, split
into literal terms (keeping `_`, `.`, `-` inside identifiers), capped at 16
terms and 256 characters, quoted, and joined with `AND`. `*`, `NEAR`, `OR`, `^`,
and `:` supplied by a user are ordinary characters. A query with nothing
matchable is `SEARCH_QUERY_INVALID`, never a wildcard and never a crash.

## Rollback and retention

- **Rollback** promotes the most recent superseded snapshot back to active and
  demotes the current one, in one transaction. With no target it is
  `NO_ROLLBACK_TARGET` (HTTP 409, CLI exit 3).
- **Recovery** runs at service construction: any snapshot a crashed process left
  in a non-terminal state is marked `failed`. The active snapshot is never
  touched.
- **Retention** keeps the active snapshot plus one superseded snapshot, so
  rollback always has somewhere to go. `prune` is explicit; nothing runs it
  automatically yet.

Deleting a snapshot cascades to its files, symbols, chunks, and membership. The
FTS5 projections are virtual tables with no foreign keys, so they are cleared
explicitly — a cascade cannot reach them.

## Interfaces

```text
GET  /v1/search/files?repository_id=&q=&limit=
GET  /v1/search/symbols?repository_id=&q=&limit=
GET  /v1/search/text?repository_id=&q=&limit=
POST /v1/repositories/{repository_id}/rollback
```

```powershell
codeatlas search <repository_id> <query> [--kind text|files|symbols] [--json]
codeatlas rollback <repository_id>
```

CLI exit codes are unchanged: 0 success, 2 invalid input, 3 unavailable,
4 partial or abstained, 5 policy failure, 6 internal failure.

## What Phase 2 still does not do

- No relations, graph traversal, TypeScript, JavaScript, MCP, change analysis,
  watcher, embeddings, or generation.
- Reuse is decided per file, not per symbol: editing one method re-derives every
  chunk in that file.
- A renamed file is a delete plus an add, because the file ID derives from the
  path.
- Ranking is unweighted BM25; a path match and a body match rank alike.
- YAML support is top-level keys and line ranges only. Anything else yields a
  `PARSE_UNSUPPORTED` diagnostic rather than a guess. No YAML dependency exists.
- Setext (underlined) Markdown headings are not recognized; only ATX (`#`).
