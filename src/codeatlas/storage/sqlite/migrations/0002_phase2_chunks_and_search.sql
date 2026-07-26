-- Phase 2: retrieval chunks, authoritative snapshot membership, and the FTS5
-- projections that back lexical search.
--
-- Additive and forward-only. Migration 0001 is applied and is not edited.

CREATE TABLE chunks (
    snapshot_id       TEXT NOT NULL,
    logical_chunk_id  TEXT NOT NULL,
    chunk_version_id  TEXT NOT NULL,
    file_id           TEXT NOT NULL,
    symbol_id         TEXT,
    role              TEXT NOT NULL,
    qualified_name    TEXT NOT NULL,
    heading_path      TEXT NOT NULL DEFAULT '',
    start_line        INTEGER NOT NULL,
    end_line          INTEGER NOT NULL,
    content_hash      TEXT NOT NULL,
    retrieval_text    TEXT NOT NULL,
    part_index        INTEGER NOT NULL DEFAULT 0,
    part_count        INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (snapshot_id, logical_chunk_id, part_index),
    FOREIGN KEY (snapshot_id, file_id)
        REFERENCES files(snapshot_id, file_id) ON DELETE CASCADE
);

CREATE INDEX chunks_by_file ON chunks(snapshot_id, file_id);
CREATE INDEX chunks_by_version ON chunks(chunk_version_id);
CREATE INDEX chunks_by_symbol ON chunks(snapshot_id, symbol_id);

-- Membership is authoritative for what an active snapshot contains. It is a
-- separate table so a later phase can retain physical rows while excluding them
-- from an active snapshot, which is what keeps stale vectors unreachable.
--
-- part_index is part of the key so an oversized symbol split into parts records
-- one membership row per part. Keying on the logical chunk alone would make the
-- second part of a split symbol a primary-key violation.
CREATE TABLE snapshot_chunk_membership (
    snapshot_id      TEXT NOT NULL
        REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    logical_chunk_id TEXT NOT NULL,
    chunk_version_id TEXT NOT NULL,
    part_index       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (snapshot_id, logical_chunk_id, part_index)
);

CREATE INDEX membership_by_version
    ON snapshot_chunk_membership(chunk_version_id);

-- External-content FTS5 tables are deliberately not used: the projection is
-- written explicitly so a partial index write cannot silently desynchronize
-- from `chunks`, and validation can compare row counts directly.
CREATE VIRTUAL TABLE chunk_search USING fts5(
    logical_chunk_id UNINDEXED,
    snapshot_id UNINDEXED,
    file_path,
    symbol_name,
    content,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE file_search USING fts5(
    file_id UNINDEXED,
    snapshot_id UNINDEXED,
    file_path,
    tokenize = 'unicode61'
);
