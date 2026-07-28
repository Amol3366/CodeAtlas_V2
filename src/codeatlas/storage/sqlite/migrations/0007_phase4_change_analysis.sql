-- Phase 4: persisted change analyses.
--
-- Additive and forward-only. Migrations 0001-0006 are applied and are not
-- edited.
--
-- An analysis is an *audit record*, not a cache. It survives snapshot pruning
-- and re-indexing, because "what did CodeAtlas say about this change, and on
-- what evidence" must remain answerable after the snapshot it examined has been
-- superseded. That is why nothing here references `snapshots(snapshot_id)`:
-- a foreign key would delete the audit trail exactly when the tree moves on.
-- The target snapshot ID is kept as a plain column so a reader can still tell
-- which snapshot the analysis was bound to, even once that snapshot is gone.
--
-- Deleting a *repository* does cascade. An analysis of a repository the user
-- removed has no subject left, and retaining it would keep derived content
-- about a repository the user asked CodeAtlas to forget.

CREATE TABLE change_analyses (
    analysis_id           TEXT PRIMARY KEY,
    repository_id         TEXT NOT NULL
        REFERENCES repositories(repository_id) ON DELETE CASCADE,
    kind                  TEXT NOT NULL,
    status                TEXT NOT NULL,
    overall_risk          TEXT NOT NULL,
    base_ref              TEXT NOT NULL,
    target_ref            TEXT NOT NULL,
    base_commit           TEXT,
    target_commit         TEXT,
    -- Not a foreign key: see the note above.
    target_snapshot_id    TEXT,
    changed_file_count    INTEGER NOT NULL DEFAULT 0,
    changed_symbol_count  INTEGER NOT NULL DEFAULT 0,
    finding_count         INTEGER NOT NULL DEFAULT 0,
    changed_files_json    TEXT NOT NULL DEFAULT '[]',
    impact_edges_json     TEXT NOT NULL DEFAULT '[]',
    test_gaps_json        TEXT NOT NULL DEFAULT '[]',
    warnings_json         TEXT NOT NULL DEFAULT '[]',
    limitations_json      TEXT NOT NULL DEFAULT '[]',
    timing_json           TEXT NOT NULL DEFAULT '{}',
    created_at            TEXT NOT NULL,
    completed_at          TEXT
);

CREATE INDEX change_analyses_by_repository
    ON change_analyses(repository_id, created_at DESC);

CREATE TABLE change_changed_symbols (
    analysis_id       TEXT NOT NULL
        REFERENCES change_analyses(analysis_id) ON DELETE CASCADE,
    ordinal           INTEGER NOT NULL,
    qualified_name    TEXT NOT NULL,
    symbol_kind       TEXT NOT NULL,
    change_kind       TEXT NOT NULL,
    file_path         TEXT NOT NULL,
    base_file_path    TEXT,
    base_start_line   INTEGER,
    base_end_line     INTEGER,
    target_start_line INTEGER,
    target_end_line   INTEGER,
    signature_changed INTEGER NOT NULL DEFAULT 0,
    public            INTEGER NOT NULL DEFAULT 0,
    derivation        TEXT NOT NULL,
    confidence        REAL NOT NULL,
    PRIMARY KEY (analysis_id, ordinal)
);

-- `rank` preserves the risk ordering the engine produced. Re-deriving it on
-- read would let a later change to the ordering rules silently rewrite what a
-- stored analysis said, which is the opposite of what an audit record is for.
CREATE TABLE change_findings (
    analysis_id       TEXT NOT NULL
        REFERENCES change_analyses(analysis_id) ON DELETE CASCADE,
    finding_id        TEXT NOT NULL,
    rank              INTEGER NOT NULL,
    code              TEXT NOT NULL,
    severity          TEXT NOT NULL,
    title             TEXT NOT NULL,
    description       TEXT NOT NULL,
    derivation        TEXT NOT NULL,
    confidence        REAL NOT NULL,
    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    remediation       TEXT,
    limitations_json  TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (analysis_id, finding_id)
);

CREATE INDEX change_findings_by_rank ON change_findings(analysis_id, rank);

-- Analysis evidence carries a `side` rather than a snapshot ID. The base side
-- of a working-tree analysis has no stored snapshot, only a commit, and
-- labeling it with one would present a historical citation as current.
--
-- As with `evidence`, the excerpt is not stored: fetching re-reads and
-- re-verifies the hash, so a row cannot outlive the content it describes.
CREATE TABLE change_evidence (
    analysis_id  TEXT NOT NULL
        REFERENCES change_analyses(analysis_id) ON DELETE CASCADE,
    evidence_id  TEXT NOT NULL,
    side         TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    symbol       TEXT,
    start_line   INTEGER NOT NULL,
    end_line     INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    derivation   TEXT NOT NULL,
    confidence   REAL NOT NULL,
    PRIMARY KEY (analysis_id, evidence_id)
);
