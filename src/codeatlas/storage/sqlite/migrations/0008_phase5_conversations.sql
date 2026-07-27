-- Phase 5: persistent conversations.
--
-- Additive and forward-only. Migrations 0001-0007 are applied and are not
-- edited.
--
-- Chat history is first-class application data, not a cache: it must survive a
-- backend restart, a re-index, and a snapshot supersession. Two consequences
-- shape this schema.
--
-- 1. `message_evidence` stores the evidence *fields* rather than referencing
--    live index rows, and nothing here references `snapshots`. A historical
--    message has to keep telling the truth it told; a join to a pruned snapshot
--    would either erase an old citation or silently re-resolve it against a
--    tree the answer never examined. The snapshot ID is kept as a plain column
--    so a reader can still see which snapshot the answer was bound to. This is
--    the same audit rule migration 0007 established for change analyses.
--
-- 2. Deleting a *repository* cascades to its conversations. Section 8.2 requires
--    an explicit policy, and this is it: conversations are derived content about
--    a repository, so removing the repository removes them. Deleting a
--    *conversation* is soft (`deleted_at`) and recoverable until Phase 6 defines
--    retention.

CREATE TABLE conversations (
    conversation_id        TEXT PRIMARY KEY,
    repository_id          TEXT NOT NULL
        REFERENCES repositories(repository_id) ON DELETE CASCADE,
    title                  TEXT NOT NULL,
    pinned_snapshot_policy TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    last_message_at        TEXT,
    archived_at            TEXT,
    deleted_at             TEXT
);

-- Listing orders by recent activity within one repository, which is the only
-- ordering the sidebar uses; `deleted_at` is in the index so the common query
-- (undeleted, newest first) is served without a scan.
CREATE INDEX conversations_by_activity
    ON conversations(repository_id, deleted_at, last_message_at DESC);

-- `sequence_number` starts at 1 and is unique per conversation: it orders the
-- thread and is the stream's resume key, so two messages at one position would
-- make both ordering and resumption ambiguous.
CREATE TABLE messages (
    message_id      TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL
        REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    status          TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    error_code      TEXT,
    created_at      TEXT NOT NULL,
    completed_at    TEXT,
    UNIQUE (conversation_id, sequence_number)
);

CREATE INDEX messages_by_sequence
    ON messages(conversation_id, sequence_number);

-- One row per *attempt*. A retry inserts a new run and leaves the previous one
-- untouched, because what was already attempted is part of the record: a user
-- looking at a retried answer can still see that the first attempt failed and
-- why.
CREATE TABLE message_runs (
    run_id                   TEXT PRIMARY KEY,
    message_id               TEXT NOT NULL
        REFERENCES messages(message_id) ON DELETE CASCADE,
    repository_id            TEXT NOT NULL,
    -- Not a foreign key: see the note at the top of this file.
    snapshot_id              TEXT NOT NULL,
    normalized_query         TEXT NOT NULL DEFAULT '',
    intent                   TEXT NOT NULL,
    retrieval_policy_version TEXT NOT NULL,
    status                   TEXT NOT NULL,
    latency_ms               REAL,
    warnings_json            TEXT NOT NULL DEFAULT '[]',
    created_at               TEXT NOT NULL,
    completed_at             TEXT
);

CREATE INDEX message_runs_by_message
    ON message_runs(message_id, created_at);

-- The citation ordinal is part of the key: citations are numbered in the answer
-- text, and two citations sharing a number would make "[1]" ambiguous to a
-- reader. As with `evidence` and `change_evidence`, the excerpt is not stored —
-- fetching re-reads and re-verifies the hash, so a row cannot outlive the
-- content it describes.
CREATE TABLE message_evidence (
    message_id       TEXT NOT NULL
        REFERENCES messages(message_id) ON DELETE CASCADE,
    citation_ordinal INTEGER NOT NULL,
    evidence_id      TEXT NOT NULL,
    file_path        TEXT NOT NULL,
    symbol           TEXT,
    start_line       INTEGER NOT NULL,
    end_line         INTEGER NOT NULL,
    content_hash     TEXT NOT NULL,
    derivation       TEXT NOT NULL,
    confidence       REAL NOT NULL,
    snapshot_id      TEXT NOT NULL,
    claim_ids_json   TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (message_id, citation_ordinal)
);

-- One rating per message: feedback is the user's current opinion, not a log of
-- how it changed, so a second rating replaces the first.
CREATE TABLE message_feedback (
    message_id  TEXT PRIMARY KEY
        REFERENCES messages(message_id) ON DELETE CASCADE,
    rating      TEXT NOT NULL,
    reason_code TEXT,
    comment     TEXT,
    created_at  TEXT NOT NULL
);
