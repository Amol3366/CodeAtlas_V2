# Phase 6 Deterministic Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build snapshot-correct exact, fuzzy, lexical, and graph retrieval that reaches at least 90% Recall@10 on the deterministic fixture benchmark without embeddings or answer generation.

**Architecture:** Immutable chunk content remains content-addressed, while snapshot-specific locations and retrieval headers move into projections. A staging snapshot is populated with files, projections, symbols, relations, and FTS rows, validated, then atomically activated. All retrievers emit one candidate contract, after which deterministic fusion, protected-exact handling, deduplication, and diagnostics produce stable results.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, Alembic, SQLite WAL/FTS5/recursive CTEs, RapidFuzz, Pydantic-free domain dataclasses, pytest, pytest-asyncio, Hypothesis, Ruff, mypy strict.

## Global Constraints

- Read the relevant `BLUEPRINT.md` section before each task; it is authoritative.
- Core retrieval must work with embeddings and answer generation disabled.
- Never execute repository code while scanning, parsing, indexing, or querying.
- Every current-code query binds to one active snapshot; stale content is removed, never down-ranked.
- Preserve `CALLS` as static certainty and `MAY_CALL` as heuristic uncertainty.
- Preserve the fixed logical chunk, chunk version, symbol, and embedding identity formulas.
- Use the coordinated SQLite writer for every mutation.
- Do not add a dependency; RapidFuzz and all required libraries are already locked.
- Do not mark an `AGENTS.md` checkbox complete without a passing test or recorded measurement.
- The current repository has an unborn, dirty worktree. Commit steps are approval gates: stage only the listed task files and do not create a commit until the user confirms the baseline/commit policy.

---

## File Structure

### Storage and indexing

- Modify `src/codeatlas/domain/entities.py`: persisted symbol, relation, and snapshot projection value objects.
- Modify `src/codeatlas/domain/identity.py`: stable file identity helper only; existing formulas remain unchanged.
- Modify `src/codeatlas/storage/sqlite/models.py`: composite snapshot projections, symbols, relations, and indexes.
- Modify `src/codeatlas/storage/sqlite/repositories.py`: snapshot-scoped stores and retrieval projection assembly.
- Create `src/codeatlas/storage/sqlite/fts.py`: FTS5 schema, population, sanitized search, and cleanup.
- Modify `src/codeatlas/storage/sqlite/database.py`: create FTS schema in test/bootstrap databases.
- Create `migrations/versions/9b6e2d18f4a1_phase_6_retrieval.py`: projection backfill, symbols, relations, indexes, and FTS5 migration.
- Modify `src/codeatlas/chunking/persist.py`: persist immutable versions plus snapshot projections.
- Modify `src/codeatlas/repositories/snapshot_manager.py`: require validation before activation.
- Create `src/codeatlas/indexing/relation_linker.py`: snapshot-wide unambiguous target resolution and derived links.
- Create `src/codeatlas/indexing/pipeline.py`: scanner-to-active-snapshot deterministic orchestration.

### Retrieval

- Create `src/codeatlas/retrieval/contracts.py`: scope, query entities, plan, candidates, results, and diagnostics.
- Create `src/codeatlas/retrieval/exact.py`: exact path, filename, qualified-name, and short-name retrieval.
- Create `src/codeatlas/retrieval/fuzzy.py`: deterministic RapidFuzz retrieval.
- Create `src/codeatlas/retrieval/lexical.py`: FTS candidate adapter.
- Create `src/codeatlas/retrieval/graph.py`: bounded recursive-CTE graph adapter.
- Create `src/codeatlas/analysis/query_analyzer.py`: deterministic intent and entity extraction.
- Create `src/codeatlas/retrieval/planner.py`: intent-to-channel plan construction.
- Create `src/codeatlas/retrieval/fusion.py`: RRF plus deterministic policy.
- Create `src/codeatlas/retrieval/deduplication.py`: canonical and evidence-level merging.
- Create `src/codeatlas/retrieval/service.py`: active-scope orchestration and diagnostics.
- Modify `src/codeatlas/retrieval/__init__.py`: stable public exports.
- Modify `src/codeatlas/settings/config.py`: graph and retrieval policy dataclasses/loaders.

### Tests and documentation

- Create `tests/unit/test_snapshot_chunk_projections.py`.
- Create `tests/unit/test_symbol_relation_storage.py`.
- Create `tests/integration/test_deterministic_indexing.py`.
- Create `tests/unit/test_exact_and_fuzzy_retrieval.py`.
- Create `tests/unit/test_fts_retrieval.py`.
- Create `tests/unit/test_graph_retrieval.py`.
- Create `tests/unit/test_query_analyzer_and_planner.py`.
- Create `tests/unit/test_fusion_and_deduplication.py`.
- Create `tests/integration/test_retrieval_snapshot_isolation.py`.
- Create `tests/evaluation/test_phase6_retrieval.py`.
- Modify `scripts/run_evaluation.py`.
- Modify `BLUEPRINT.md`: make snapshot projections authoritative for line/retrieval metadata.
- Modify `AGENTS.md`: record only proven Phase 6 progress and final measurements.

---

### Task 1: Make snapshot activation and chunk evidence correct

**Files:**
- Modify: `src/codeatlas/domain/entities.py`
- Modify: `src/codeatlas/domain/identity.py`
- Modify: `src/codeatlas/storage/sqlite/models.py`
- Modify: `src/codeatlas/storage/sqlite/repositories.py`
- Modify: `src/codeatlas/chunking/persist.py`
- Modify: `src/codeatlas/repositories/snapshot_manager.py`
- Modify: `src/codeatlas/indexing/state_machine.py`
- Modify: `src/codeatlas/storage/sqlite/database.py`
- Create: `migrations/versions/9b6e2d18f4a1_phase_6_retrieval.py`
- Modify: `BLUEPRINT.md`
- Test: `tests/unit/test_snapshot_chunk_projections.py`
- Test: `tests/unit/test_state_machine.py`
- Test: `tests/unit/test_migrations.py`

**Interfaces:**
- Produces: `file_id(repository_id: str, normalized_path: str) -> str`.
- Produces: `SnapshotChunkProjection` with snapshot/file/symbol/line/retrieval metadata.
- Produces: `ChunkStore.retrieval_chunks(snapshot_id: str) -> list[RetrievalChunk]`.
- Changes: `SnapshotManager.activate()` accepts only a `VALIDATING` snapshot.
- Produces: `SnapshotManager.get(snapshot_id: str) -> Snapshot | None`.

- [ ] **Step 1: Write failing activation and shifted-line tests**

```python
async def test_activate_rejects_staging_snapshot(database: Database) -> None:
    repo = await seed_repository(database, "repo_activation")
    manager = SnapshotManager(database.writer)
    snapshot = await manager.create_staging(repo.id, snapshot_type=SnapshotType.DIRECTORY)

    with pytest.raises(SnapshotError, match="staging -> active"):
        await manager.activate(snapshot.id)


async def test_reused_chunk_reads_lines_from_active_snapshot(database: Database) -> None:
    repo = await seed_repository(database, "repo_projection")
    manager = SnapshotManager(database.writer)
    first = build_chunk(
        repository_id=repo.id,
        normalized_path="src/a.py",
        qualified_name="run",
        chunk_role=ChunkRole.SYMBOL_IMPLEMENTATION,
        parser_version="0.1.0",
        start_line=1,
        end_line=2,
        raw_content="def run():\n    return 1",
        retrieval_content="PATH: src/a.py\nLINES: 1-2\n\ndef run():\n    return 1",
    )
    moved = replace(
        first,
        start_line=11,
        end_line=12,
        retrieval_content="PATH: src/a.py\nLINES: 11-12\n\ndef run():\n    return 1",
    )
    snap_a = await activate_chunks(database, manager, repo.id, [first])
    snap_b = await activate_chunks(database, manager, repo.id, [moved])

    async with database.writer.read_session() as session:
        rows = await ChunkStore(session).retrieval_chunks(snap_b.id)

    assert snap_a.id != snap_b.id
    assert [(row.start_line, row.end_line) for row in rows] == [(11, 12)]
    assert "LINES: 11-12" in rows[0].retrieval_content
```

- [ ] **Step 2: Run the focused tests and confirm the existing defects**

Run: `uv run pytest tests/unit/test_state_machine.py tests/unit/test_snapshot_chunk_projections.py -v`

Expected: staging activation is incorrectly accepted and the reused version returns lines 1-2.

- [ ] **Step 3: Add projection entities, schema, mapping, and strict activation**

Use these exact domain shapes:

```python
@dataclass(frozen=True)
class SnapshotChunkProjection:
    snapshot_id: str
    chunk_version_id: str
    start_line: int
    end_line: int
    retrieval_content: str
    is_active: bool = True
    file_id: str | None = None
    symbol_id: str | None = None
    parent_chunk_id: str | None = None
    chunk_type: str | None = None
    metadata_json: str = "{}"


@dataclass(frozen=True)
class RetrievalChunk:
    logical_chunk_id: str
    chunk_version_id: str
    snapshot_id: str
    normalized_path: str
    content_hash: str
    raw_content: str
    retrieval_content: str
    start_line: int
    end_line: int
    token_count: int
    file_id: str | None = None
    symbol_id: str | None = None
```

Implement file identity without changing existing hashes:

```python
def file_id(repository_id: str, normalized_path: str) -> str:
    return "file_" + stable_hash(repository_id, normalized_path)
```

Replace the `PRE_ACTIVE` check with the state-machine transition:

```python
assert_transition(snapshot.status, SnapshotStatus.ACTIVE)
```

Move `start_line`, `end_line`, and `retrieval_content` into membership/projection persistence. Keep `raw_content` and new `token_count` on `ChunkVersion`. Change `files` to composite primary key `(snapshot_id, id)` so the stable `file_id(repository_id, normalized_path)` can recur across snapshots, and use the same composite ownership in file references. The migration must backfill old memberships before dropping the old version columns. Update Blueprint sections 10.11-10.12 to match the approved design.

- [ ] **Step 4: Verify focused tests and migration parity**

Run: `uv run pytest tests/unit/test_state_machine.py tests/unit/test_snapshot_chunk_projections.py tests/unit/test_migrations.py -v`

Expected: all tests pass, including fresh upgrade/downgrade and populated-schema backfill.

- [ ] **Step 5: Review gate and scoped commit**

Run: `uv run ruff check src/codeatlas/domain src/codeatlas/storage src/codeatlas/chunking src/codeatlas/repositories tests/unit/test_snapshot_chunk_projections.py tests/unit/test_state_machine.py tests/unit/test_migrations.py`

Expected: `All checks passed!`

After baseline/commit approval:

```powershell
git add BLUEPRINT.md migrations/versions/9b6e2d18f4a1_phase_6_retrieval.py src/codeatlas/domain/entities.py src/codeatlas/domain/identity.py src/codeatlas/storage/sqlite/models.py src/codeatlas/storage/sqlite/repositories.py src/codeatlas/storage/sqlite/database.py src/codeatlas/chunking/persist.py src/codeatlas/repositories/snapshot_manager.py src/codeatlas/indexing/state_machine.py tests/unit/test_snapshot_chunk_projections.py tests/unit/test_state_machine.py tests/unit/test_migrations.py
git commit -m "fix: make chunk evidence snapshot-specific"
```

---

### Task 2: Persist snapshot symbols, relations, and FTS projections

**Files:**
- Modify: `src/codeatlas/domain/entities.py`
- Modify: `src/codeatlas/storage/sqlite/models.py`
- Modify: `src/codeatlas/storage/sqlite/repositories.py`
- Create: `src/codeatlas/storage/sqlite/fts.py`
- Modify: `src/codeatlas/storage/sqlite/database.py`
- Modify: `migrations/versions/9b6e2d18f4a1_phase_6_retrieval.py`
- Test: `tests/unit/test_symbol_relation_storage.py`
- Test: `tests/unit/test_fts_retrieval.py`

**Interfaces:**
- Produces: `SymbolRecord`, `RelationRecord`, `FtsDocument`, `FtsHit`.
- Produces: `SymbolStore.replace_snapshot()`, `RelationStore.replace_snapshot()`.
- Produces: `FtsStore.replace_snapshot()`, `FtsStore.search()`, `FtsStore.delete_snapshot()`.

- [ ] **Step 1: Write failing persistence and FTS isolation tests**

```python
async def test_symbol_and_relation_rows_are_snapshot_scoped(database: Database) -> None:
    first, second = await seed_two_snapshots(database)
    symbol = symbol_record(first.id, "sym_capture", "PaymentService.capture")
    relation = relation_record(first.id, "rel_call", symbol.id, "Gateway.charge")
    async with database.writer.transaction() as session:
        await SymbolStore(session).replace_snapshot(first.id, [symbol])
        await RelationStore(session).replace_snapshot(first.id, [relation])

    async with database.writer.read_session() as session:
        assert await SymbolStore(session).find_qualified(second.id, "PaymentService.capture") == []
        assert await RelationStore(session).outbound(second.id, symbol.id) == []


async def test_fts_filters_by_snapshot(database: Database) -> None:
    async with database.writer.transaction() as session:
        store = FtsStore(session)
        await store.replace_snapshot("snap_old", [fts_document("snap_old", "old", "capture")])
        await store.replace_snapshot("snap_new", [fts_document("snap_new", "new", "refund")])

    async with database.writer.read_session() as session:
        rows = await FtsStore(session).search("snap_new", "capture", limit=10)

    assert rows == []
```

- [ ] **Step 2: Run tests and verify missing tables/stores**

Run: `uv run pytest tests/unit/test_symbol_relation_storage.py tests/unit/test_fts_retrieval.py -v`

Expected: collection fails because the records and stores do not exist.

- [ ] **Step 3: Implement records, ORM tables, stores, and safe FTS5**

Use these persisted contracts:

```python
@dataclass(frozen=True)
class SymbolRecord:
    id: str
    snapshot_id: str
    file_id: str
    qualified_name: str
    short_name: str
    symbol_type: SymbolType
    language: Language
    start_line: int
    end_line: int
    signature: str | None = None
    docstring: str | None = None
    parent_symbol_id: str | None = None
    exported: bool = True
    parser_confidence: float = 1.0


@dataclass(frozen=True)
class RelationRecord:
    id: str
    snapshot_id: str
    source_entity_id: str
    target_name: str
    relation_type: RelationType
    confidence: float
    derivation: Derivation
    evidence_start_line: int
    evidence_end_line: int
    target_entity_id: str | None = None
    evidence_file_id: str | None = None
```

Create FTS5 with bound parameters for values and sanitized tokens for MATCH:

```python
_TOKEN = re.compile(r"[\w./:-]+", re.UNICODE)


def fts_query(text: str) -> str:
    tokens = _TOKEN.findall(text)
    return " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)
```

The virtual table columns are `snapshot_id UNINDEXED`, `entity_id UNINDEXED`, `entity_kind UNINDEXED`, `normalized_path`, `qualified_name`, `short_name`, `signature`, `docstring`, `body`, and `retrieval_content`. `Database.create_all()` must call `create_fts_schema()` after ORM metadata creation.

- [ ] **Step 4: Run focused storage tests**

Run: `uv run pytest tests/unit/test_symbol_relation_storage.py tests/unit/test_fts_retrieval.py tests/unit/test_migrations.py -v`

Expected: all tests pass; malicious MATCH punctuation returns a safe result or empty list without SQL errors.

- [ ] **Step 5: Review gate and scoped commit**

Run: `uv run mypy src/codeatlas/domain src/codeatlas/storage`

Expected: `Success: no issues found`.

After baseline/commit approval, stage the files listed in this task and run:

```powershell
git commit -m "feat: persist snapshot retrieval entities"
```

---

### Task 3: Build and validate a complete deterministic snapshot

**Files:**
- Create: `src/codeatlas/indexing/relation_linker.py`
- Create: `src/codeatlas/indexing/pipeline.py`
- Modify: `src/codeatlas/storage/sqlite/repositories.py`
- Modify: `src/codeatlas/repositories/snapshot_manager.py`
- Test: `tests/integration/test_deterministic_indexing.py`
- Test: `tests/unit/test_symbol_relation_storage.py`

**Interfaces:**
- Consumes: repository scanner, parser registry, code/document/config chunkers, stores from Tasks 1-2.
- Produces: `RelationLinker.link(symbols, relations, chunks) -> tuple[RelationRecord, ...]`.
- Produces: `DeterministicIndexer.index(repository: Repository) -> Snapshot`.
- Produces: `SnapshotValidator.validate(snapshot_id: str) -> tuple[IndexDiagnostic, ...]`.
- Produces: `build_file_records(repository, snapshot, manifest) -> tuple[FileRecord, ...]`.
- Produces: `build_artifacts(repository, snapshot, manifest) -> SnapshotArtifacts`.
- Produces: `persist_artifacts(database, artifacts) -> None` and `populate_fts(database, artifacts) -> None`.
- Produces: `IndexDiagnostic(message: str, code: str, entity_id: str | None)`.

- [ ] **Step 1: Write a failing fixture-index integration test**

```python
async def test_python_fixture_builds_queryable_snapshot(
    database: Database, copy_fixture: Callable[[str], Path]
) -> None:
    root = copy_fixture("python_repo")
    repository = RepositoryService().register(str(root))
    indexer = DeterministicIndexer(database)

    snapshot = await indexer.index(repository)

    assert snapshot.status is SnapshotStatus.ACTIVE
    async with database.writer.read_session() as session:
        symbols = await SymbolStore(session).find_qualified(snapshot.id, "PaymentService.capture")
        relations = await RelationStore(session).inbound(snapshot.id, symbols[0].id)
        chunks = await ChunkStore(session).for_snapshot(snapshot.id)
    assert len(symbols) == 1
    assert chunks
    assert all(relation.snapshot_id == snapshot.id for relation in relations)
```

- [ ] **Step 2: Run the integration test and verify the pipeline is absent**

Run: `uv run pytest tests/integration/test_deterministic_indexing.py::test_python_fixture_builds_queryable_snapshot -v`

Expected: collection fails because `DeterministicIndexer` does not exist.

- [ ] **Step 3: Implement indexing, linking, validation, and failure rollback**

Use the application boundary:

```python
class DeterministicIndexer:
    def __init__(self, database: Database, *, repository_service: RepositoryService | None = None):
        self._database = database
        self._repositories = repository_service or RepositoryService()

    async def index(self, repository: Repository) -> Snapshot:
        manager = SnapshotManager(self._database.writer)
        snapshot = await manager.create_staging(
            repository.id,
            snapshot_type=SnapshotType.DIRECTORY,
            parser_bundle_version=PARSER_BUNDLE_VERSION,
            chunker_version=CHUNKER_VERSION,
            retrieval_policy_version="0.1.0",
        )
        try:
            scan = self._repositories.scan(repository)
            artifacts = await build_artifacts(repository, snapshot, scan.manifest)
            linked = RelationLinker().link(
                artifacts.symbols, artifacts.relations, artifacts.chunks
            )
            artifacts = replace(artifacts, relations=linked)
            await persist_artifacts(self._database, artifacts)
            await populate_fts(self._database, artifacts)
            await manager.begin_validation(snapshot.id)
            diagnostics = await SnapshotValidator(self._database).validate(snapshot.id)
            if diagnostics:
                messages = "; ".join(item.message for item in diagnostics)
                raise SnapshotError(f"Snapshot validation failed: {messages}")
            await manager.activate(snapshot.id)
            active = await manager.get(snapshot.id)
            if active is None:
                raise SnapshotError(f"Activated snapshot disappeared: {snapshot.id}")
            return active
        except Exception:
            await manager.fail(snapshot.id)
            raise
```

`SnapshotArtifacts` is a frozen dataclass containing `snapshot`, `files`, `chunks`, `symbols`, `relations`, and `diagnostics` tuples. Generate stable file IDs with `file_id(repository.id, entry.normalized_path)`. Parse Python/TypeScript/JavaScript through `default_registry`; chunk Markdown with `DocumentChunker`; chunk JSON/YAML/TOML with `ConfigurationChunker`. Persist parser diagnostics. `SnapshotManager.get()` reads the final stored snapshot after activation.

The linker builds maps by qualified and short name. It assigns `target_entity_id` only when one candidate exists, preserves the incoming type/confidence/derivation, and leaves ambiguous targets unresolved. Derived `TESTS` and `DOCUMENTS` relations use `NAMING_CONVENTION` or `LEXICAL_MATCH`, never `STATIC_RESOLVED`.

- [ ] **Step 4: Test success, determinism, and failed activation**

Run: `uv run pytest tests/integration/test_deterministic_indexing.py tests/unit/test_symbol_relation_storage.py -v`

Expected: fixture indexing passes twice with identical logical IDs; an injected FTS failure marks the new snapshot failed and leaves the previous active snapshot unchanged.

- [ ] **Step 5: Review gate and scoped commit**

Run: `uv run ruff check src/codeatlas/indexing tests/integration/test_deterministic_indexing.py`

Expected: `All checks passed!`

After baseline/commit approval, stage Task 3 files and run:

```powershell
git commit -m "feat: build deterministic retrieval snapshots"
```

---

### Task 4: Define retrieval contracts and exact/fuzzy channels

**Files:**
- Create: `src/codeatlas/retrieval/contracts.py`
- Create: `src/codeatlas/retrieval/exact.py`
- Create: `src/codeatlas/retrieval/fuzzy.py`
- Modify: `src/codeatlas/storage/sqlite/repositories.py`
- Modify: `src/codeatlas/settings/config.py`
- Test: `tests/unit/test_exact_and_fuzzy_retrieval.py`

**Interfaces:**
- Produces: `ActiveScope`, `CandidateKind`, `RetrievalChannel`, `MatchType`, `RetrievalCandidate`, `ChannelResult`.
- Produces: `ChannelDiagnostics(rejected_snapshot_count, truncated, error)`.
- Produces: `ExactRetriever.search(scope, entities, limit) -> ChannelResult`.
- Produces: `FuzzyRetriever.search(scope, entities, limit) -> ChannelResult`.

- [ ] **Step 1: Write failing exact, fuzzy, and stable-order tests**

```python
async def test_exact_symbol_and_path_candidates_are_protected(indexed_python_repo: IndexedRepo) -> None:
    entities = QueryEntities(paths=("src/services/payment_service.py",), symbols=("PaymentService.capture",))
    result = await ExactRetriever(indexed_python_repo.database).search(
        indexed_python_repo.scope, entities, limit=10
    )
    assert {candidate.match_type for candidate in result.candidates} == {MatchType.EXACT}
    assert all(candidate.protected for candidate in result.candidates)


async def test_fuzzy_results_are_stable_and_never_exact(indexed_python_repo: IndexedRepo) -> None:
    entities = QueryEntities(symbols=("PaymentServce.captur",))
    retriever = FuzzyRetriever(indexed_python_repo.database, score_cutoff=70.0)
    first = await retriever.search(indexed_python_repo.scope, entities, limit=10)
    second = await retriever.search(indexed_python_repo.scope, entities, limit=10)
    assert first.candidates == second.candidates
    assert first.candidates[0].symbol == "PaymentService.capture"
    assert all(not candidate.protected for candidate in first.candidates)
```

- [ ] **Step 2: Run tests and verify missing contracts/retrievers**

Run: `uv run pytest tests/unit/test_exact_and_fuzzy_retrieval.py -v`

Expected: collection fails on missing retrieval modules.

- [ ] **Step 3: Implement immutable candidates and both channels**

Use this candidate core:

```python
@dataclass(frozen=True)
class RetrievalCandidate:
    id: str
    repository_id: str
    snapshot_id: str
    kind: CandidateKind
    entity_id: str
    normalized_path: str
    display_path: str
    start_line: int
    end_line: int
    content: str
    content_hash: str
    channel: RetrievalChannel
    channel_rank: int
    raw_score: float
    match_type: MatchType
    protected: bool = False
    symbol: str | None = None
    confidence: float = 1.0
    derivation: Derivation = Derivation.STATIC_RESOLVED
    relation_path: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ChannelDiagnostics:
    rejected_snapshot_count: int = 0
    truncated: bool = False
    error: str | None = None


@dataclass(frozen=True)
class ChannelResult:
    channel: RetrievalChannel
    candidates: tuple[RetrievalCandidate, ...]
    diagnostics: ChannelDiagnostics = ChannelDiagnostics()

    @property
    def error(self) -> str | None:
        return self.diagnostics.error
```

Exact path lookup compares normalized full paths; filename lookup compares the final path component case-insensitively. Symbol lookup checks qualified name before short name. Fuzzy retrieval uses `rapidfuzz.process.extract`, a configured cutoff, and stable ties `(score desc, normalized_path, start_line, entity_id)`.

- [ ] **Step 4: Run focused channel tests**

Run: `uv run pytest tests/unit/test_exact_and_fuzzy_retrieval.py -v`

Expected: exact path, filename, qualified name, short name, misspellings, cutoff, and stable-order tests pass.

- [ ] **Step 5: Review gate and scoped commit**

Run: `uv run mypy src/codeatlas/retrieval/contracts.py src/codeatlas/retrieval/exact.py src/codeatlas/retrieval/fuzzy.py`

Expected: `Success: no issues found`.

After approval, stage Task 4 files and run:

```powershell
git commit -m "feat: add exact and fuzzy retrieval"
```

---

### Task 5: Add FTS5 lexical retrieval

**Files:**
- Create: `src/codeatlas/retrieval/lexical.py`
- Modify: `src/codeatlas/storage/sqlite/fts.py`
- Test: `tests/unit/test_fts_retrieval.py`

**Interfaces:**
- Consumes: `FtsStore.search(snapshot_id, query, limit)` and `RetrievalCandidate`.
- Produces: `LexicalRetriever.search(scope, question, limit) -> ChannelResult`.

- [ ] **Step 1: Add failing lexical relevance and hostile-query tests**

```python
async def test_lexical_search_finds_docstrings_code_and_documents(indexed_python_repo: IndexedRepo) -> None:
    result = await LexicalRetriever(indexed_python_repo.database).search(
        indexed_python_repo.scope, "idempotency capture", limit=10
    )
    assert any(candidate.symbol == "PaymentService.capture" for candidate in result.candidates)
    assert any(candidate.kind is CandidateKind.DOCUMENT for candidate in result.candidates)


@pytest.mark.parametrize("query", ['capture OR "', "NEAR((capture", "*:*", "capture -refund"])
async def test_lexical_query_is_not_raw_fts_syntax(indexed_python_repo: IndexedRepo, query: str) -> None:
    result = await LexicalRetriever(indexed_python_repo.database).search(
        indexed_python_repo.scope, query, limit=10
    )
    assert result.error is None
```

- [ ] **Step 2: Run tests and verify lexical adapter is absent**

Run: `uv run pytest tests/unit/test_fts_retrieval.py -v`

Expected: collection fails on missing `LexicalRetriever`.

- [ ] **Step 3: Implement lexical candidate conversion**

Convert SQLite `bm25` into a descending score with `score = 1.0 / (1.0 + max(0.0, bm25_value))`, assign rank after stable sorting, and join each FTS row back to its authoritative snapshot projection. Drop any FTS row whose entity no longer exists in that snapshot and record the rejection count in `ChannelResult`.

```python
class LexicalRetriever:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def search(self, scope: ActiveScope, question: str, limit: int) -> ChannelResult:
        query = fts_query(question)
        if not query:
            return ChannelResult(RetrievalChannel.LEXICAL, ())
        async with self._database.writer.read_session() as session:
            hits = await FtsStore(session).search(scope.snapshot_id, query, limit=limit)
        candidates = tuple(
            RetrievalCandidate(
                id=f"lexical:{hit.entity_id}",
                repository_id=scope.repository_id,
                snapshot_id=scope.snapshot_id,
                kind=CandidateKind(hit.entity_kind),
                entity_id=hit.entity_id,
                normalized_path=hit.normalized_path,
                display_path=hit.display_path,
                start_line=hit.start_line,
                end_line=hit.end_line,
                content=hit.content,
                content_hash=hit.content_hash,
                channel=RetrievalChannel.LEXICAL,
                channel_rank=rank,
                raw_score=1.0 / (1.0 + max(0.0, hit.bm25_score)),
                match_type=MatchType.LEXICAL,
                symbol=hit.qualified_name,
            )
            for rank, hit in enumerate(hits, start=1)
        )
        return ChannelResult(RetrievalChannel.LEXICAL, candidates)
```

- [ ] **Step 4: Run lexical tests**

Run: `uv run pytest tests/unit/test_fts_retrieval.py -v`

Expected: code, docstring, configuration, and document searches pass; hostile inputs do not become FTS operators.

- [ ] **Step 5: Review gate and scoped commit**

Run: `uv run ruff check src/codeatlas/storage/sqlite/fts.py src/codeatlas/retrieval/lexical.py tests/unit/test_fts_retrieval.py`

Expected: `All checks passed!`

After approval, stage Task 5 files and run:

```powershell
git commit -m "feat: add snapshot-scoped lexical retrieval"
```

---

### Task 6: Add bounded recursive graph retrieval

**Files:**
- Create: `src/codeatlas/retrieval/graph.py`
- Modify: `src/codeatlas/storage/sqlite/repositories.py`
- Modify: `src/codeatlas/settings/config.py`
- Test: `tests/unit/test_graph_retrieval.py`

**Interfaces:**
- Produces: `GraphDirection`, `GraphRequest`, `GraphTraversalResult`.
- Produces: `GraphRetriever.search(scope, request) -> ChannelResult`.

- [ ] **Step 1: Write failing direction, confidence, cycle, and fan-out tests**

```python
async def test_graph_traversal_respects_all_bounds(graph_fixture: GraphFixture) -> None:
    request = GraphRequest(
        seed_ids=("sym_root",),
        direction=GraphDirection.OUTBOUND,
        relation_types=(RelationType.CALLS, RelationType.MAY_CALL),
        max_depth=2,
        max_nodes=5,
        minimum_confidence=0.45,
    )
    result = await GraphRetriever(graph_fixture.database).search(graph_fixture.scope, request)
    assert len({candidate.entity_id for candidate in result.candidates}) <= 5
    assert all(len(candidate.relation_path) <= 2 for candidate in result.candidates)
    assert all(candidate.confidence >= 0.45 for candidate in result.candidates)
    assert result.diagnostics.truncated is True
```

- [ ] **Step 2: Run tests and verify graph adapter is absent**

Run: `uv run pytest tests/unit/test_graph_retrieval.py -v`

Expected: collection fails on missing graph contracts.

- [ ] **Step 3: Implement recursive CTE storage query and adapter**

Use bound parameters for snapshot, seed IDs, depth, confidence, and limit. Construct the allowed-relation `IN` clause with SQLAlchemy expanding parameters. The recursive row carries `node_id`, `depth`, `path`, `relation_path`, `confidence`, and a delimited visited string; reject a next node already present in visited. Fetch `max_nodes + 1`, trim to `max_nodes`, and set `truncated` when the extra row exists.

```python
@dataclass(frozen=True)
class GraphRequest:
    seed_ids: tuple[str, ...]
    direction: GraphDirection
    relation_types: tuple[RelationType, ...]
    max_depth: int = 3
    max_nodes: int = 200
    minimum_confidence: float = 0.45
```

- [ ] **Step 4: Run graph tests including adversarial fixture**

Run: `uv run pytest tests/unit/test_graph_retrieval.py -v`

Expected: inbound/outbound results are correct; low-confidence edges are excluded; cycles terminate; depth and node limits hold.

- [ ] **Step 5: Review gate and scoped commit**

Run: `uv run mypy src/codeatlas/retrieval/graph.py src/codeatlas/storage/sqlite/repositories.py`

Expected: `Success: no issues found`.

After approval, stage Task 6 files and run:

```powershell
git commit -m "feat: add bounded graph retrieval"
```

---

### Task 7: Analyze queries and build deterministic plans

**Files:**
- Create: `src/codeatlas/analysis/query_analyzer.py`
- Create: `src/codeatlas/retrieval/planner.py`
- Modify: `src/codeatlas/retrieval/contracts.py`
- Test: `tests/unit/test_query_analyzer_and_planner.py`

**Interfaces:**
- Produces: `QueryAnalysis(intent, entities, normalized_question)`.
- Produces: `RetrievalPlan(channels, graph_request, unavailable_channels)`.
- Produces: `QueryAnalyzer.analyze(question: str) -> QueryAnalysis`.
- Produces: `RetrievalPlanner.create(analysis: QueryAnalysis) -> RetrievalPlan`.

- [ ] **Step 1: Write table-driven failing intent/entity tests**

```python
@pytest.mark.parametrize(
    ("question", "intent", "symbol"),
    [
        ("Where is PaymentService.capture defined?", IntentType.LOCATE, "PaymentService.capture"),
        ("Which code calls PaymentService.capture?", IntentType.FIND_CALLERS, "PaymentService.capture"),
        ("What does PaymentService.capture depend on?", IntentType.FIND_DEPENDENCIES, "PaymentService.capture"),
        ("Which tests reference AuthService.authenticate?", IntentType.FIND_TESTS, "AuthService.authenticate"),
        ("Which configuration controls database_url?", IntentType.CONFIGURATION, "database_url"),
    ],
)
def test_query_analyzer(question: str, intent: IntentType, symbol: str) -> None:
    result = QueryAnalyzer().analyze(question)
    assert result.intent is intent
    assert symbol in (*result.entities.symbols, *result.entities.config_keys)
```

- [ ] **Step 2: Run tests and verify analyzer/planner are absent**

Run: `uv run pytest tests/unit/test_query_analyzer_and_planner.py -v`

Expected: collection fails on missing analyzer and planner.

- [ ] **Step 3: Implement ordered deterministic rules and Blueprint priorities**

Rules are evaluated from most specific to least specific: impact, callers, dependencies, tests, documents, trace, configuration, architecture, database, history, locate, explain, general. Entity extraction uses compiled regexes for quoted paths, path-like tokens, dotted identifiers, route patterns, config keys, and Git-like refs. Preserve original extracted text while storing a normalized comparison form.

Planner mapping must include:

```python
_CHANNELS: dict[IntentType, tuple[RetrievalChannel, ...]] = {
    IntentType.LOCATE: (RetrievalChannel.EXACT, RetrievalChannel.FUZZY, RetrievalChannel.LEXICAL),
    IntentType.FIND_CALLERS: (RetrievalChannel.EXACT, RetrievalChannel.GRAPH),
    IntentType.FIND_DEPENDENCIES: (RetrievalChannel.EXACT, RetrievalChannel.GRAPH),
    IntentType.FIND_TESTS: (RetrievalChannel.EXACT, RetrievalChannel.GRAPH, RetrievalChannel.LEXICAL),
    IntentType.FIND_DOCUMENTS: (RetrievalChannel.EXACT, RetrievalChannel.LEXICAL),
    IntentType.CONFIGURATION: (RetrievalChannel.EXACT, RetrievalChannel.LEXICAL),
}
```

Plans for `HISTORY` list `git_history` as unavailable; plans never silently claim the channel ran.

- [ ] **Step 4: Run analyzer and planner tests**

Run: `uv run pytest tests/unit/test_query_analyzer_and_planner.py -v`

Expected: all Blueprint intent samples and extracted path/symbol/config/Git entities pass.

- [ ] **Step 5: Review gate and scoped commit**

Run: `uv run ruff check src/codeatlas/analysis/query_analyzer.py src/codeatlas/retrieval/planner.py tests/unit/test_query_analyzer_and_planner.py`

Expected: `All checks passed!`

After approval, stage Task 7 files and run:

```powershell
git commit -m "feat: analyze and plan deterministic queries"
```

---

### Task 8: Fuse, protect, deduplicate, and orchestrate results

**Files:**
- Create: `src/codeatlas/retrieval/fusion.py`
- Create: `src/codeatlas/retrieval/deduplication.py`
- Create: `src/codeatlas/retrieval/service.py`
- Modify: `src/codeatlas/retrieval/contracts.py`
- Modify: `src/codeatlas/retrieval/__init__.py`
- Test: `tests/unit/test_fusion_and_deduplication.py`
- Test: `tests/integration/test_retrieval_snapshot_isolation.py`

**Interfaces:**
- Produces: `FusionPolicy`, `ScoredCandidate`, `RetrievalDiagnostics`, `RetrievalResult`.
- Produces: `fuse(groups, policy) -> tuple[ScoredCandidate, ...]` using Reciprocal Rank Fusion.
- Produces: `deduplicate(candidates) -> DeduplicationResult`.
- Produces: `apply_limit(candidates, limit) -> tuple[ScoredCandidate, ...]`.
- Produces: `RetrievalService.search(repository_id, question, limit=10) -> RetrievalResult`.

- [ ] **Step 1: Write failing RRF, exact-preservation, dedupe, and leakage tests**

```python
def test_exact_candidate_survives_limit_and_deduplication() -> None:
    exact = candidate("exact", protected=True, channel_rank=50, entity_id="sym_capture")
    stronger = candidate("lexical", protected=False, channel_rank=1, entity_id="sym_capture")
    noise = tuple(candidate(f"n{i}", protected=False, channel_rank=i + 1) for i in range(20))

    merged = deduplicate(fuse(((exact,), (stronger, *noise)), FusionPolicy(rrf_k=60)))
    selected = apply_limit(merged.candidates, limit=1)

    assert any(row.entity_id == "sym_capture" and row.protected for row in selected)
    assert len(selected) >= 1


async def test_every_channel_rejects_inactive_snapshot(indexed_two_snapshot_repo: IndexedRepo) -> None:
    result = await RetrievalService(indexed_two_snapshot_repo.database).search(
        indexed_two_snapshot_repo.repository.id, "PaymentService.capture", limit=10
    )
    assert result.scope.snapshot_id == indexed_two_snapshot_repo.active_snapshot.id
    assert all(row.snapshot_id == result.scope.snapshot_id for row in result.candidates)
    assert not any("deleted_marker" in row.content for row in result.candidates)
```

- [ ] **Step 2: Run tests and verify fusion/service modules are absent**

Run: `uv run pytest tests/unit/test_fusion_and_deduplication.py tests/integration/test_retrieval_snapshot_isolation.py -v`

Expected: collection fails on missing fusion and service modules.

- [ ] **Step 3: Implement RRF, policy, merge rules, diagnostics, and service**

Use exact RRF:

```python
score = sum(1.0 / (policy.rrf_k + rank) for rank in candidate.channel_ranks.values())
```

Apply named boosts/penalties from immutable policy values and store every applied adjustment in diagnostics. Deduplicate in the approved order: canonical entity, symbol, same-file line overlap, content hash plus evidence role, document path plus heading ancestry. Merged rows retain all channels, maximum confidence, relation paths, and `protected = any(source.protected)`.

`RetrievalService` resolves the active snapshot once, executes only planned channels, rejects any candidate whose snapshot differs, fuses, deduplicates, applies stable ordering, and then applies the limit. Protected candidates are always included; overflow is recorded.

- [ ] **Step 4: Run fusion and isolation tests**

Run: `uv run pytest tests/unit/test_fusion_and_deduplication.py tests/integration/test_retrieval_snapshot_isolation.py -v`

Expected: RRF values, boosts, penalties, deterministic ties, protected overflow, all dedupe rules, unavailable-channel diagnostics, and zero leakage pass.

- [ ] **Step 5: Review gate and scoped commit**

Run: `uv run mypy src/codeatlas/retrieval src/codeatlas/analysis`

Expected: `Success: no issues found`.

After approval, stage Task 8 files and run:

```powershell
git commit -m "feat: fuse deterministic retrieval evidence"
```

---

### Task 9: Wire benchmark measurement and close Phase 6 with evidence

**Files:**
- Create: `tests/evaluation/test_phase6_retrieval.py`
- Modify: `scripts/run_evaluation.py`
- Modify: `AGENTS.md`
- Modify: `docs/superpowers/plans/2026-07-22-phase-6-deterministic-retrieval.md`

**Interfaces:**
- Consumes: `DeterministicIndexer` and `RetrievalService`.
- Produces: `evaluate_phase6_questions() -> Phase6Metrics`.
- Produces: recorded Recall@10, exact-preservation, leakage, and graph-bound metrics.

- [ ] **Step 1: Write the failing evaluation gate**

```python
def test_phase6_deterministic_recall_meets_target(phase6_metrics: Phase6Metrics) -> None:
    assert phase6_metrics.question_count == 35
    assert phase6_metrics.primary_evidence_recall_at_10 >= 0.90
    assert phase6_metrics.active_snapshot_leakage == 0
    assert phase6_metrics.exact_candidates_removed == 0
    assert phase6_metrics.graph_bound_violations == 0
```

Evidence matching uses required fixture `file_path` plus symbol when supplied. A question succeeds when every required primary-evidence item appears in the top ten. The fixed Phase 6 intent set is `LOCATE`, `EXPLAIN`, `TRACE_FLOW`, `FIND_CALLERS`, `FIND_DEPENDENCIES`, `FIND_TESTS`, `FIND_DOCUMENTS`, `CONFIGURATION`, and `GENERAL_PROJECT`; the single `HISTORY` item remains pending.

- [ ] **Step 2: Run the evaluation test and record the initial measured gap**

Run: `uv run pytest tests/evaluation/test_phase6_retrieval.py -v`

Expected: the test either lacks the metrics adapter or reports Recall@10 below 0.90; retain the per-question failures for targeted fixes.

- [ ] **Step 3: Implement evaluation wiring and make evidence-based corrections**

Add `Phase6Metrics` and async fixture indexing to `scripts/run_evaluation.py`. Print passed/failed question IDs, per-intent recall, total Recall@10, exact removals, leakage, and graph violations. Correct only observed retrieval, linking, analyzer, or fixture-ground-truth defects; add a regression test beside the responsible component before each correction.

The command output must end with this shape:

```text
Phase 6 deterministic retrieval:
  questions: 35
  primary evidence Recall@10: 0.xxx
  exact candidates removed: 0
  active snapshot leakage: 0
  graph bound violations: 0
  status: PASS
```

- [ ] **Step 4: Run complete verification**

Run these commands independently:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src/codeatlas
uv run python scripts/run_evaluation.py
uv run pytest tests/unit/test_migrations.py -v
```

Expected: pytest passes; Ruff and mypy report no issues; evaluation reports Phase 6 PASS with Recall@10 at least 0.90 and all zero-count invariants; the temp-database migration round-trip succeeds without touching a user database.

- [ ] **Step 5: Update progress only from the recorded evidence**

Set the Phase 6 overview and section to `DONE`, add the completion date, check each proven build/exit item, and include test names or measurement values beside the checkbox. If any gate fails, keep Phase 6 `IN PROGRESS` and leave the corresponding box unchecked.

- [ ] **Step 6: Final review gate and scoped commit**

After baseline/commit approval, stage all Phase 6 files plus `AGENTS.md` and run:

```powershell
git commit -m "feat: complete deterministic retrieval phase"
```

---

## Execution Checkpoints

- After Task 1: review the migration and snapshot invariants before adding tables that depend on them.
- After Task 3: inspect an indexed fixture directly in SQLite before building retrievers.
- After Task 6: review candidate contracts and graph bounds before query orchestration.
- After Task 8: run all Phase 6 tests before tuning against the benchmark.
- After Task 9: do not declare completion unless every verification command has fresh passing output.
