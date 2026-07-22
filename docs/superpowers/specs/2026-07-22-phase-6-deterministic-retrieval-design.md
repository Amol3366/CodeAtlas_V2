# Phase 6 Deterministic Retrieval Design

## Status

Approved in conversation on 2026-07-22.

## Goal

Implement Phase 6 of CodeAtlas: deterministic, snapshot-correct file, symbol,
lexical, and graph retrieval with evidence-backed results and no dependency on
embeddings or an answer model.

The implementation must satisfy the Phase 6 checklist in `AGENTS.md` and the
retrieval, query-pipeline, and data-model requirements in `BLUEPRINT.md`.

## Scope

Phase 6 includes:

- a complete deterministic indexing path connecting the existing scanner,
  parsers, chunkers, and SQLite storage;
- snapshot-correct retrieval chunk projections;
- persisted symbols and relations;
- exact path, filename, qualified-symbol, and short-symbol retrieval;
- RapidFuzz identifier and path retrieval;
- FTS5 indexing and lexical retrieval;
- bounded graph traversal;
- deterministic query analysis and retrieval planning;
- Reciprocal Rank Fusion, boosts, penalties, exact-match preservation, and
  deduplication;
- structured retrieval diagnostics;
- deterministic benchmark evaluation and Phase 6 acceptance measurements.

Phase 6 does not add CLI, REST, or MCP adapters. Those are Phase 7. Git history
retrieval is Phase 8, filesystem watching is Phase 11, vector retrieval is Phase
12, and model-based reranking and answer generation are Phase 14. When a plan
references one of these unavailable channels, diagnostics must identify it
explicitly.

## Non-Negotiable Constraints

- All functionality works with `NoEmbeddingProvider` and `NoAnswerProvider`.
- Every current-code query is bound to exactly one active snapshot.
- Staging, failed, superseded, deleted, and inactive content cannot leak into
  current results.
- Exact matches cannot be removed by fusion, deduplication, reranking, or result
  limits.
- `CALLS` remains statically resolved certainty; `MAY_CALL` remains heuristic.
- Repository source is data and is never executed or treated as instructions.
- Chunk, symbol, content, and embedding identity formulas remain unchanged.
- SQLite remains the authoritative store and all writes use the coordinated
  writer.

## Architecture Decision

Use normalized snapshot projections.

Content-addressed artifacts remain reusable across snapshots. Snapshot-varying
data, including line locations and retrieval headers, is stored in a
snapshot-specific projection. This avoids duplicating immutable source content
while ensuring evidence always reports locations from the requested snapshot.

Rejected alternatives:

1. Duplicating all retrieval records per snapshot wastes storage and weakens
   cross-snapshot reuse.
2. Keeping only an active-snapshot search index complicates staging, rollback,
   crash recovery, and future historical queries.

## Storage Design

### Chunk versions

`chunk_versions` stores only data that is invariant for its content-addressed
identity:

- chunk version ID;
- logical chunk ID;
- content hash;
- parser version;
- chunker version;
- exact raw content;
- token count.

Line ranges and the current retrieval header must not be read from this table.
This corrects the existing defect where an unchanged symbol that moves after an
edit can reuse a chunk version containing stale line metadata.

This is an intentional corrective refinement of the field placement currently
shown in Blueprint sections 10.11 and 10.12. The implementation must update
those Blueprint sections in the same change so that the authoritative
specification and schema do not diverge.

### Snapshot chunk projections

`snapshot_chunk_membership` becomes the query-facing projection and contains:

- snapshot ID and chunk version ID as its identity;
- file ID;
- symbol ID, when applicable;
- parent chunk ID, when applicable;
- chunk type or role;
- current start and end lines;
- current retrieval content;
- serialized metadata and references;
- active-membership state.

The projection joins to `logical_chunks` and `chunk_versions` to assemble the
`RetrievalChunk` contract described by Blueprint section 10.6.

### Migration and existing data

The Alembic migration first adds nullable projection fields, backfills existing
memberships from their joined chunk-version rows, and only then applies required
constraints where the existing data can satisfy them. File, symbol, parent, and
metadata fields that cannot be reconstructed from the old schema remain
nullable until that snapshot is reindexed. Such incomplete legacy projections
must fail deterministic-readiness validation rather than produce misleading
evidence.

After successful backfill, snapshot-varying line and retrieval fields move out
of `chunk_versions`. Downgrade reconstructs the former columns from a
deterministic membership projection and documents that multiple snapshot
locations collapse to one legacy value. Migration tests cover both a fresh
database and a populated pre-Phase-6 database.

### Symbols

The new `symbols` table is snapshot scoped. Its logical symbol ID remains stable
across snapshots, while the composite `(snapshot_id, symbol_id)` identifies the
stored projection. It records:

- file ID;
- qualified and short names;
- symbol type and language;
- signature and docstring;
- parent symbol ID;
- start and end lines;
- exported state;
- parser confidence.

Indexes cover snapshot plus qualified name, short name, file, parent, and symbol
type.

### Relations

The new `relations` table is snapshot scoped with composite
`(snapshot_id, relation_id)` identity. It records:

- source entity ID;
- nullable resolved target entity ID;
- required target name for transparent unresolved references;
- relation type;
- confidence and derivation;
- evidence file and line range.

Indexes support snapshot-scoped inbound and outbound traversal, relation type,
and confidence filtering. Polymorphic entity references are validated by the
indexing service rather than represented as an invalid cross-table foreign key.

### FTS5

A SQLite FTS5 virtual table stores snapshot-scoped search projections for code,
tests, configuration, and documents. Each row includes unindexed identity and
scope columns plus searchable path, qualified name, short name, signature,
docstring/comment text, raw code or document text, and retrieval text.

FTS rows may exist for a staging snapshot, but every lexical query requires an
explicit snapshot filter. Failed snapshot rows are never eligible for active
scope and may be cleaned later without affecting correctness.

## Snapshot Activation

Indexing writes may be split into short transactions while the snapshot remains
in `staging`. The service then moves the snapshot to `validating` and checks:

- file, symbol, relation, chunk, projection, and FTS ownership;
- valid projection line ranges;
- required chunk projections and FTS coverage;
- absence of cross-snapshot relations;
- consistency of resolved relation targets;
- deterministic index readiness.

Only a validated snapshot may become active. The previous snapshot is
superseded in the same activation transaction. Any failure marks the new
snapshot failed, records diagnostics, and leaves the previous active snapshot
unchanged.

## Deterministic Indexing Flow

1. Register or resolve the repository and create a staging snapshot.
2. Scan a deterministic file manifest and persist snapshot file records.
3. Parse supported files and retain visible diagnostics for partial failures.
4. Build stable symbol-aligned chunks and reuse content-addressed artifacts.
5. Persist snapshot chunk projections and symbols.
6. Persist parser relations, including unresolved target names.
7. Run a snapshot-wide relation linker.
8. Populate FTS5 projections.
9. Validate all deterministic stores.
10. Activate the new snapshot atomically.

The relation linker resolves only unambiguous local targets. It may add
containment, route, test, document, and reference relations when evidence exists,
but it must record derivation and confidence. It never upgrades heuristic
evidence to static certainty. Ambiguous targets remain unresolved.

Phase 6 supports explicit full and content-reusing incremental snapshot builds.
It does not add continuous filesystem watching.

## Query Analysis and Planning

`QueryAnalyzer` performs deterministic normalization, intent classification,
and entity extraction. It recognizes the Blueprint intent enum and extracts:

- normalized and display paths;
- qualified and short symbol names;
- routes;
- configuration keys;
- Git references.

`RetrievalPlanner` maps intent to required channels and graph direction or
relation filters. Later-phase channels are represented in the plan but reported
as unavailable when they have no implementation.

The initial intent priority follows Blueprint section 7.3. Exact/navigation
intents avoid broad channels when a precise answer is available; callers and
dependency intents prioritize graph traversal; configuration and document
intents include lexical search.

## Candidate Contract

All retrievers return the same immutable candidate shape containing:

- repository and snapshot IDs;
- canonical entity and candidate kind;
- file path, symbol, and exact line range;
- content and content hash;
- channel and channel rank;
- raw channel score;
- match type and exact/protected flag;
- confidence and derivation;
- relation path, when applicable;
- generated, vendor, test, document-authority, and other ranking metadata.

Candidates do not contain claims beyond their stored evidence.

## Retrieval Channels

### Exact retrieval

Exact retrieval supports normalized full paths, filenames, qualified symbol
names, and short symbol names. Path comparisons use Windows-safe normalized
keys while preserving original casing for display. Exact candidates are marked
protected before leaving the retriever.

### Fuzzy retrieval

RapidFuzz operates over active-snapshot path and identifier projections. It uses
deterministic thresholds and stable tie-breaking. Fuzzy retrieval never labels a
candidate as exact.

### Lexical retrieval

FTS5 searches path/name, signature/docstring, source, configuration, and
documentation fields. Query construction escapes or tokenizes untrusted input
instead of interpolating raw FTS syntax. Results are joined back to the
snapshot-scoped authoritative tables before becoming candidates.

### Graph retrieval

Graph traversal uses bounded recursive CTEs. Each request specifies direction,
allowed relation types, maximum depth, maximum nodes, and minimum confidence,
defaulting to the configured values of depth 3, nodes 200, and confidence 0.45.
The traversal tracks visited nodes, suppresses cycles, returns evidence for each
edge, and reports truncation in diagnostics.

## Snapshot Filtering

Every storage method requires a snapshot ID rather than accepting an optional
scope. Current-query application services first resolve the repository's active
snapshot and pass that immutable scope to every selected retriever.

Filtering is enforced twice:

1. in each SQL or FTS candidate query;
2. in a defensive candidate filter before fusion.

Any rejected candidate is counted in diagnostics. A candidate from a different
snapshot is never merely penalized; it is removed.

## Fusion and Ranking

Candidate groups are fused with Reciprocal Rank Fusion:

`RRF(candidate) = sum(1 / (rrf_k + channel_rank))`

The default `rrf_k` is 60. Deterministic policy then applies documented boosts
for exact symbols, exact paths, direct relations, tests, and authoritative
documents, plus penalties for generated/vendor content, low-confidence
relations, and duplicates.

Tie-breaking is stable and uses normalized path, start line, candidate kind,
and canonical ID.

### Exact-match preservation

Protected exact candidates are always retained. Deduplication may merge an exact
candidate with an equivalent canonical candidate, but the merged result keeps
all exact-match provenance and protected status. If protected exact candidates
exceed a requested result limit, all are returned and diagnostics report the
overflow.

## Deduplication

Deduplication runs in this order:

1. canonical entity identity;
2. symbol identity;
3. overlapping lines in the same file and evidence role;
4. equivalent content hash and evidence role;
5. document path plus heading ancestry.

Distinct symbols are not merged merely because their source content is equal.
Every merge retains channel provenance, the strongest confidence, relation
paths, and protected status.

## Diagnostics

Retrieval returns results with structured diagnostics containing:

- normalized query, active snapshot, intent, and extracted entities;
- selected and unavailable channels;
- per-channel candidate IDs, ranks, counts, and scores;
- snapshot-filter rejections;
- pre-fusion and post-fusion counts and scores;
- applied boosts and penalties;
- deduplication merge records;
- graph depth/node limits and truncation;
- exact-match limit overflow;
- parse, persistence, linking, and FTS validation problems when relevant.

Elapsed timings may be present for observability but are excluded from any
determinism comparison.

## Failure Handling

- Parse failure in one file produces diagnostics and does not crash unrelated
  files.
- A deterministic-store or validation failure prevents activation.
- An FTS query syntax issue becomes a safe diagnostic and empty lexical group,
  not arbitrary SQL.
- Ambiguous relation resolution remains visible as an unresolved target.
- Graph bound exhaustion returns bounded results plus a truncation diagnostic.
- Missing later-phase providers are reported and deterministic retrieval
  continues.

## Implementation Slices

1. Snapshot projection schema migration and shifted-line regression.
2. Symbol/relation persistence and deterministic repository indexing.
3. Exact retrieval.
4. RapidFuzz retrieval.
5. FTS5 population and lexical retrieval.
6. Bounded graph traversal and relation linking.
7. Query analysis and planning.
8. RRF fusion, exact preservation, deduplication, and diagnostics.
9. Evaluation integration, full verification, and checklist updates.

Each slice is implemented test-first. Upstream Phase 1-5 defects are repaired in
the slice that exposes them only when they prevent a Phase 6 invariant or exit
criterion; unrelated cleanup remains out of scope.

## Testing Strategy

### Unit tests

- analyzer normalization, intent rules, and entity extraction;
- exact and fuzzy scoring and stable ties;
- FTS query sanitization;
- RRF calculations, boosts, penalties, and protected exact results;
- each deduplication identity rule;
- graph direction, confidence, depth, nodes, cycles, and fan-out;
- relation linker ambiguity and derivation preservation.

### Integration tests

- migration upgrade, downgrade, and ORM parity;
- an unchanged chunk moving to different lines returns the new snapshot lines;
- complete fixture indexing and deterministic repeated results;
- symbol, relation, chunk projection, and FTS snapshot ownership;
- staging, failed, superseded, deleted, and inactive leakage equals zero in
  exact, fuzzy, lexical, graph, and fused results;
- failed indexing leaves the prior active snapshot queryable;
- exact results survive adverse fusion, deduplication, and result limits;
- adversarial graph cycles and fan-out remain within configured bounds.

### Evaluation

The evaluation runner indexes the fixture repositories and scores a fixed
deterministic subset: `LOCATE`, `EXPLAIN`, `TRACE_FLOW`, `FIND_CALLERS`,
`FIND_DEPENDENCIES`, `FIND_TESTS`, `FIND_DOCUMENTS`, `CONFIGURATION`, and
`GENERAL_PROJECT`. `HISTORY` and future `IMPACT_ANALYSIS` questions are excluded
from the Phase 6 gate because their authoritative channels arrive in Phase 8;
they remain visibly pending rather than being counted as successes.

Phase 6 acceptance requires:

- primary-evidence Recall@10 at least 0.90 on the deterministic subset;
- exact matches never removed;
- active-snapshot leakage exactly zero;
- graph bounds respected on adversarial fixtures;
- all functionality passing with embeddings and answer generation disabled.

## Verification and Completion

Before Phase 6 is marked complete:

1. run migration upgrade and downgrade tests;
2. run focused Phase 6 unit and integration tests;
3. run the evaluation runner and record its measurements;
4. run the full pytest suite;
5. run Ruff checks and formatting checks;
6. run strict mypy on `src/codeatlas`;
7. update Phase 6 checkboxes and status in `AGENTS.md` only for items proven by
   tests or recorded measurements.

No success claim is made from checklist text alone.
