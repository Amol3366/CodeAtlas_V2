-- Phase 2: give the chunk search projection a part index.
--
-- `chunks` is keyed by (snapshot_id, logical_chunk_id, part_index), because an
-- oversized symbol splits into parts that share one logical chunk. The search
-- projection created in 0002 carried only the logical chunk ID, so joining a
-- hit back to its row would multiply results for a split symbol and would make
-- the projection row count disagree with the chunk row count that validation
-- compares. Both are corrected by keying the projection the same way.
--
-- FTS5 cannot add a column in place, so the table is recreated. Nothing is lost:
-- no code populates the projection until this migration lands, and any snapshot
-- that predates it has no rows here.
--
-- 0002 is left untouched, so a database already at version 2 upgrades cleanly
-- instead of silently disagreeing with a rewritten migration.

DROP TABLE IF EXISTS chunk_search;

CREATE VIRTUAL TABLE chunk_search USING fts5(
    logical_chunk_id UNINDEXED,
    part_index UNINDEXED,
    snapshot_id UNINDEXED,
    file_path,
    symbol_name,
    content,
    tokenize = 'unicode61'
);
