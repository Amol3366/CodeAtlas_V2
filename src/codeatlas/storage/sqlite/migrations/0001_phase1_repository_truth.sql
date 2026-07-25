-- Phase 1 repository truth: repositories, snapshots, files, symbols, jobs.
-- Applied by codeatlas.storage.sqlite.migrations. Never edit an applied file;
-- add a new numbered migration instead.

CREATE TABLE repositories (
    repository_id  TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL,
    canonical_root TEXT NOT NULL UNIQUE,
    created_at     TEXT NOT NULL
);

CREATE TABLE snapshots (
    snapshot_id              TEXT PRIMARY KEY,
    repository_id            TEXT NOT NULL
        REFERENCES repositories(repository_id) ON DELETE CASCADE,
    state                    TEXT NOT NULL,
    git_head                 TEXT,
    git_branch               TEXT,
    git_dirty                INTEGER NOT NULL,
    working_tree_fingerprint TEXT NOT NULL,
    file_count               INTEGER NOT NULL,
    parsed_file_count        INTEGER NOT NULL,
    skipped_file_count       INTEGER NOT NULL,
    parse_error_count        INTEGER NOT NULL,
    parser_bundle_version    TEXT NOT NULL,
    index_version            TEXT NOT NULL,
    created_at               TEXT NOT NULL,
    activated_at             TEXT
);

-- Enforces "at most one active snapshot per repository" in the database rather
-- than in application code, so a bug cannot produce two active snapshots.
CREATE UNIQUE INDEX snapshots_one_active_per_repository
    ON snapshots(repository_id) WHERE state = 'active';
CREATE INDEX snapshots_by_repository ON snapshots(repository_id, state);

CREATE TABLE files (
    snapshot_id    TEXT NOT NULL
        REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    file_id        TEXT NOT NULL,
    relative_path  TEXT NOT NULL,
    display_path   TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL,
    line_count     INTEGER NOT NULL,
    language       TEXT NOT NULL,
    classification TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, file_id)
);

CREATE INDEX files_by_path ON files(snapshot_id, relative_path);

CREATE TABLE symbols (
    snapshot_id       TEXT NOT NULL,
    symbol_id         TEXT NOT NULL,
    symbol_version_id TEXT NOT NULL,
    file_id           TEXT NOT NULL,
    kind              TEXT NOT NULL,
    name              TEXT NOT NULL,
    qualified_name    TEXT NOT NULL,
    module_path       TEXT NOT NULL,
    signature         TEXT,
    start_line        INTEGER NOT NULL,
    end_line          INTEGER NOT NULL,
    start_byte        INTEGER NOT NULL,
    end_byte          INTEGER NOT NULL,
    content_hash      TEXT NOT NULL,
    visibility        TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, symbol_id),
    FOREIGN KEY (snapshot_id, file_id)
        REFERENCES files(snapshot_id, file_id) ON DELETE CASCADE
);

CREATE INDEX symbols_by_name ON symbols(snapshot_id, name);
CREATE INDEX symbols_by_qualified_name ON symbols(snapshot_id, qualified_name);

CREATE TABLE index_jobs (
    job_id        TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL
        REFERENCES repositories(repository_id) ON DELETE CASCADE,
    snapshot_id   TEXT NOT NULL,
    stage         TEXT NOT NULL,
    status        TEXT NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 1,
    started_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    diagnostics   TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX index_jobs_by_repository ON index_jobs(repository_id, status);
