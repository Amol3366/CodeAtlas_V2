-- Phase 3: resolved relations between symbols.
--
-- Additive and forward-only. Migrations 0001-0004 are applied and are not
-- edited.
--
-- Relations are snapshot-scoped rows, like chunks. Resolution is recomputed for
-- every snapshot rather than copied forward, so a row here always describes what
-- the targets meant in *this* snapshot.

CREATE TABLE relations (
    snapshot_id       TEXT NOT NULL
        REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    relation_id       TEXT NOT NULL,
    source_symbol_id  TEXT NOT NULL,
    -- NULL for every resolution state except 'resolved'. An external,
    -- unresolved, or ambiguous reference has no single symbol to name, and
    -- inventing one would turn a heuristic into an apparent fact.
    target_symbol_id  TEXT,
    file_id           TEXT NOT NULL,
    kind              TEXT NOT NULL,
    target_hint       TEXT NOT NULL,
    resolution        TEXT NOT NULL,
    derivation        TEXT NOT NULL,
    confidence        REAL NOT NULL,
    start_line        INTEGER NOT NULL,
    end_line          INTEGER NOT NULL,
    -- 1 when resolved, 0 when external or unresolved, >1 when ambiguous.
    candidate_count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (snapshot_id, relation_id)
);

-- The two traversal directions. Both are asserted with EXPLAIN QUERY PLAN in
-- tests/integration/test_relation_store.py rather than assumed, because
-- traversal is the hottest path in the phase and a missing index here degrades
-- silently into a table scan.
CREATE INDEX relations_by_source
    ON relations(snapshot_id, source_symbol_id, kind);
CREATE INDEX relations_by_target
    ON relations(snapshot_id, target_symbol_id, kind);
CREATE INDEX relations_by_file ON relations(snapshot_id, file_id);
